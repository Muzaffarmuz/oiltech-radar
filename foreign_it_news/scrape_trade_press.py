#!/usr/bin/env python3
"""
Новости про 12 иностранных нефтегазовых компаний из отраслевых лент + Google News RSS
(не с корпоративных сайтов компаний).

Фильтры:
  - упоминание одной из 12 компаний
  - дата >= 2026-01-01 (если дата есть; без даты — оставляем с пометкой)
  - IT/digital keyword (по умолчанию) и опционально Lab LLM

Запуск из корня:
  py -3 foreign_it_news/scrape_trade_press.py --keyword-only
  py -3 foreign_it_news/trade_press/enrich_bodies.py --playwright

Важно: Google News RSS почти не даёт текста (только title). После сбора
нужен enrich_bodies.py — он резолвит URL издателя и качает тело статьи.

Креды Lab — из .env. Результаты: foreign_it_news/out_trade/ (it_focus.json)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._lab_credentials import (  # noqa: E402
    ensure_no_proxy,
    lab_api_key,
    lab_base_url,
    lab_model,
)

ensure_no_proxy()
BASE_URL = lab_base_url()
API_KEY = lab_api_key()
MODEL_NAME = lab_model("gpt-oss-120b")


from gartner.config import Settings  # noqa: E402
from gartner.custom_sources.article_extract import extract_article_page  # noqa: E402
from gartner.custom_sources.engine import ArticleRecord, write_articles_raw  # noqa: E402
from gartner.custom_sources.fetch import fetch_html_safe  # noqa: E402
from gartner.custom_sources.llm_gates import LlmBudget  # noqa: E402
from gartner.llm import LLMClient, extract_json_object, get_response_text  # noqa: E402

from foreign_it_news.adapters.base import (  # noqa: E402
    has_it_hint_wide,
    is_noise_title,
    parse_date,
)
from foreign_it_news.trade_press.companies import match_companies  # noqa: E402
from foreign_it_news.trade_press.rss_parse import (  # noqa: E402
    FeedItem,
    fetch_feed,
    google_news_feeds,
    normalize_published,
)

HERE = Path(__file__).resolve().parent
FEEDS_PATH = HERE / "trade_press" / "feeds.json"
OUT_DIR = HERE / "out_trade"
RUN_TAG = "trade-press"


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{RUN_TAG} {ts}] {msg}", flush=True)


IT_PROMPT = """
You filter oil & gas trade-press articles for an IT / automation technology radar.
Return ONLY JSON: {"keep": true|false, "reason": "short"}

keep=true ONLY if the PRIMARY topic is digital / IT / automation related to oil & gas
companies (software, AI/ML, cloud, cyber, digital twin, robotics, SCADA/IoT, data platforms,
autonomous operations, industrial software, IT partnerships).

keep=false for: pure commodity prices, earnings, M&A without digital angle, geopolitics,
shipping schedules, generic energy opinion, articles where a major is only name-dropped.
""".strip()


def load_static_feeds() -> list[dict[str, str]]:
    return json.loads(FEEDS_PATH.read_text(encoding="utf-8"))


def make_llm() -> LLMClient:
    client = LLMClient(
        Settings(API_KEY=API_KEY, BASE_URL=BASE_URL, LLM_MODEL=MODEL_NAME)
    )
    if client._client is not None:
        try:
            client._client = client._client.with_options(timeout=45.0)
        except Exception:
            pass
    return client


def lab_judge(rec_title: str, rec_text: str, url: str) -> tuple[bool | None, str]:
    from openai import OpenAI

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=45.0)
    payload = {
        "title": rec_title[:300],
        "url": url,
        "text_preview": rec_text[:1200],
    }
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": IT_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            max_tokens=160,
        )
        raw = extract_json_object(get_response_text(response))
    except Exception as exc:
        return None, f"error:{type(exc).__name__}"
    if not raw or "keep" not in raw:
        return None, "bad_response"
    return bool(raw.get("keep")), str(raw.get("reason") or "")[:240]


def _is_junk_source(item: FeedItem) -> bool:
    blob = f"{item.link} {item.source_hint} {item.feed_name} {item.title}".lower()
    junk = (
        "royaldutchshellplc.com",
        "royal dutch shell plc .com",
        "royal dutch shell plc.com",
        "shell.com.donor",
        "ghost in the shell",
        "simply wall st",
        "mlq.ai",  # агрегатор сделок/отчётности
    )
    return any(j in blob for j in junk)


# жёсткая витрина it_focus — только явный ИТ в headline
STRONG_IT_TITLE = re.compile(
    r"\b(ai|artificial intelligence|digital|automation|robot(?:ics)?|drone|uav|"
    r"cyber|cloud|software|scada|iot|digital twin|machine learning|data center|"
    r"supercomput|hpc|smart field|digital oilfield|autonomous|analytics|"
    r"platform|sensor|4ir|genai|agentic)\b",
    re.I,
)


def _headline_only(title: str) -> str:
    """Google News: 'Headline - Source' — источник часто содержит слово Digital."""
    t = (title or "").strip()
    if " - " in t:
        t = t.rsplit(" - ", 1)[0]
    return t


def enrich_article(item: FeedItem) -> tuple[str, str, str]:
    """title, text, date — из RSS; при возможности дотягиваем тело страницы."""
    title = item.title
    text = item.summary
    datatime = normalize_published(item.published)
    if item.link and "news.google.com" not in item.link:
        html, err = fetch_html_safe(item.link, timeout=22.0)
        if html:
            rec = extract_article_page(html, item.link, source_name=item.feed_id)
            if rec:
                title = rec.title or title
                text = rec.text or text
                if rec.datatime:
                    datatime = normalize_published(rec.datatime) or rec.datatime
    return title, text, datatime


def main() -> int:
    parser = argparse.ArgumentParser(description="Trade press / Google News → 12 foreign majors IT news")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--no-google", action="store_true", help="не использовать Google News RSS")
    parser.add_argument("--only-feeds", default="", help="id лент через запятую")
    parser.add_argument("--max-per-feed", type=int, default=80)
    parser.add_argument("--keyword-only", action="store_true", help="без Lab LLM")
    parser.add_argument("--skip-it-filter", action="store_true", help="только компания+дата, без IT")
    parser.add_argument("--fetch-body", action="store_true", help="докачивать HTML каждой статьи (медленно)")
    parser.add_argument(
        "--enrich-kept",
        action="store_true",
        help="после keyword-фильтра докачать тело только для прошедших статей",
    )
    parser.add_argument("--allow-undated", action="store_true", help="оставлять статьи без даты")
    parser.add_argument(
        "--min-date",
        default="2025-01-01",
        help="минимальная дата YYYY-MM-DD (для trade press по умолчанию 2025: у Shell/Conoco много digital за 2025)",
    )
    args = parser.parse_args()
    min_date = date_cls.fromisoformat(args.min_date)

    feeds = load_static_feeds()
    if not args.no_google:
        feeds = feeds + google_news_feeds()
    if args.only_feeds.strip():
        want = {x.strip().lower() for x in args.only_feeds.split(",") if x.strip()}
        feeds = [f for f in feeds if f["id"].lower() in want]
        if not feeds:
            print(f"Нет лент по --only-feeds {want}", file=sys.stderr)
            return 2

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    per_dir = out_dir / "by_company"
    per_dir.mkdir(parents=True, exist_ok=True)

    llm = make_llm()
    use_llm = (not args.keyword_only) and (not args.skip_it_filter) and llm.enabled
    log(f"START pid={os.getpid()} feeds={len(feeds)} llm={use_llm} keyword_only={args.keyword_only}")
    log(f"model={MODEL_NAME} out={out_dir}")

    all_items: list[FeedItem] = []
    feed_stats: list[dict[str, Any]] = []
    for i, feed in enumerate(feeds, 1):
        log(f"==== feed {i}/{len(feeds)} · {feed['id']} · {feed['name']} ====")
        items, err = fetch_feed(feed["url"], feed_id=feed["id"], feed_name=feed["name"])
        if err:
            log(f"  FAIL: {err[:140]}")
            feed_stats.append({"id": feed["id"], "ok": False, "error": err, "n": 0})
            continue
        items = items[: args.max_per_feed]
        # Google News feed уже заточен под одну компанию — всё равно прогоняем матчер
        log(f"  items={len(items)}")
        all_items.extend(items)
        feed_stats.append({"id": feed["id"], "ok": True, "n": len(items)})

    # unique by link/title
    seen: set[str] = set()
    uniq: list[FeedItem] = []
    for it in all_items:
        key = (it.link or it.title).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        uniq.append(it)
    log(f"unique items={len(uniq)}")

    budget = LlmBudget(kind_limit=0, title_limit=0, keep_limit=400, theme_limit=0)
    kept: list[dict[str, Any]] = []
    stats = {
        "listed": len(uniq),
        "no_company": 0,
        "dropped_date": 0,
        "dropped_noise": 0,
        "dropped_keyword": 0,
        "dropped_it": 0,
        "kept": 0,
    }

    for idx, item in enumerate(uniq, 1):
        if idx == 1 or idx % 25 == 0 or idx == len(uniq):
            log(f"  … {idx}/{len(uniq)} kept={stats['kept']} no_co={stats['no_company']} drop_kw={stats['dropped_keyword']}")

        if args.fetch_body:
            title, text, datatime = enrich_article(item)
        else:
            title, text, datatime = item.title, item.summary, normalize_published(item.published)

        blob = f"{title}\n{text}\n{item.source_hint}"
        companies = match_companies(blob)
        if not companies:

            stats["no_company"] += 1
            continue

        d = parse_date(datatime)
        if d is None:
            if not args.allow_undated:
                stats["dropped_date"] += 1
                continue
        elif d < min_date:
            stats["dropped_date"] += 1
            continue

        if is_noise_title(title) or is_noise_title(item.source_hint) or _is_junk_source(item):
            stats["dropped_noise"] += 1
            continue

        if not args.skip_it_filter:
            # широкий пул: компания может быть только в тексте; ИТ — 1 маркер
            if not has_it_hint_wide(title, text):
                stats["dropped_keyword"] += 1
                continue
            if use_llm:
                if not budget.take("keep"):
                    stats["dropped_it"] += 1
                    continue
                decision, reason = lab_judge(title, text, item.link)
                if decision is not True:
                    stats["dropped_it"] += 1
                    continue
                it_gate, it_reason = "keep", reason
            else:
                it_gate, it_reason = "keyword_wide", ""
        else:
            it_gate, it_reason = "disabled", ""

        head = _headline_only(title or "")
        for co in companies:
            in_title = bool(
                re.search(re.escape(co.name.split()[0]), head, re.I)
                or (co.id == "exxonmobil" and re.search(r"exxon", head, re.I))
                or (
                    co.id == "conocophillips"
                    and re.search(r"conocophillips|conoco|\bCOP\b", head, re.I)
                )
                or (co.id == "totalenergies" and re.search(r"totalenergies|total energies|\btotal\b", head, re.I))
                or (co.id == "occidental" and re.search(r"oxy|occidental", head, re.I))
                or (co.id == "bp" and re.search(r"(?<![a-z])bp(?![a-z])", head, re.I))
                or (co.id == "shell" and re.search(r"\bshell\b", head, re.I))
                or (co.id == "adnoc" and re.search(r"\badnoc\b", head, re.I))
                or (co.id == "aramco" and re.search(r"\baramco\b", head, re.I))
                or (co.id == "equinor" and re.search(r"\bequinor\b", head, re.I))
                or (co.id == "eni" and re.search(r"(?<![a-z])eni(?![a-z])", head, re.I))
                or (co.id == "petrobras" and re.search(r"\bpetrobras\b", head, re.I))
                or (co.id == "chevron" and re.search(r"\bchevron\b", head, re.I))
            )
            kept.append(
                {
                    "company_id": co.id,
                    "company": co.name,
                    "title": title,
                    "text": text,
                    "datatime": datatime,
                    "source": item.source_hint or item.feed_name,
                    "feed_id": item.feed_id,
                    "feed_name": item.feed_name,
                    "link": item.link,
                    "it_gate": it_gate,
                    "it_reason": it_reason,
                    "adapter": False,
                    "trade_press": True,
                    "company_in_title": in_title,
                    "pool": "wide",
                }
            )
        stats["kept"] += 1

    if args.enrich_kept and kept:
        log(f"enrich-kept: fetching bodies for {len(kept)} rows …")
        # unique links
        by_link: dict[str, list[dict[str, Any]]] = {}
        for row in kept:
            by_link.setdefault(row["link"] or row["title"], []).append(row)
        for i, (link, rows) in enumerate(by_link.items(), 1):
            if i == 1 or i % 20 == 0 or i == len(by_link):
                log(f"  enrich {i}/{len(by_link)}")
            if not link.startswith("http") or "news.google.com" in link:
                continue
            html, _ = fetch_html_safe(link, timeout=22.0)
            if not html:
                continue
            rec = extract_article_page(html, link, source_name=rows[0].get("feed_id") or "trade")
            if not rec:
                continue
            for row in rows:
                row["title"] = rec.title or row["title"]
                row["text"] = rec.text or row["text"]
                if rec.datatime:
                    row["datatime"] = normalize_published(rec.datatime) or rec.datatime
                row["enriched"] = True

    # write per company + combined
    by_co: dict[str, list[dict[str, Any]]] = {}
    for row in kept:
        by_co.setdefault(row["company_id"], []).append(row)

    for cid, rows in by_co.items():
        records = [
            ArticleRecord(
                title=r["title"],
                text=r["text"],
                datatime=r.get("datatime") or "",
                source=r.get("source") or r.get("feed_id") or cid,
                link=r["link"],
            )
            for r in rows
        ]
        write_articles_raw(records, per_dir / cid)
        (per_dir / f"{cid}_report.json").write_text(
            json.dumps({"company_id": cid, "n": len(rows), "articles": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    combined = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "min_date": min_date.isoformat(),
        "feeds": feed_stats,
        "stats": stats,
        "n_articles": len(kept),
        "articles": kept,
        "keyword_only": args.keyword_only or not use_llm,
        "model": MODEL_NAME if use_llm else None,
    }
    (out_dir / "all_articles.json").write_text(
        json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # широкий пул = all_articles; витрина = компания в title + явный ИТ в headline
    focused = []
    for r in kept:
        head = _headline_only(r.get("title") or "")
        if not r.get("company_in_title"):
            continue
        if not STRONG_IT_TITLE.search(head):
            continue
        focused.append({**r, "pool": "focus"})

    (out_dir / "wide_pool.json").write_text(
        json.dumps(
            {
                "generated_at": combined["generated_at"],
                "note": "Широкий пул: компания в title или тексте + мягкий ИТ-фильтр",
                "n_articles": len(kept),
                "by_company": {k: len(v) for k, v in by_co.items()},
                "articles": kept,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (out_dir / "it_focus.json").write_text(
        json.dumps(
            {
                "generated_at": combined["generated_at"],
                "note": "Узкая витрина: компания в заголовке + ИТ-слово в заголовке",
                "n_articles": len(focused),
                "articles": focused,
                "by_company": {
                    cid: sum(1 for r in focused if r["company_id"] == cid)
                    for cid in sorted({r["company_id"] for r in focused})
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    (out_dir / "summary.json").write_text(
        json.dumps(
            {
                "generated_at": combined["generated_at"],
                "n_wide": len(kept),
                "n_articles": len(kept),
                "n_focus": len(focused),
                "stats": stats,
                "feeds": feed_stats,
                "by_company": {k: len(v) for k, v in by_co.items()},
                "focus_by_company": {
                    cid: sum(1 for r in focused if r["company_id"] == cid)
                    for cid in sorted({r["company_id"] for r in focused})
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    focus_counts: dict[str, int] = {}
    for r in focused:
        focus_counts[r["company_id"]] = focus_counts.get(r["company_id"], 0) + 1
    log(f"DONE wide={len(kept)} focus={len(focused)} → {out_dir}")
    log(f"stats={stats}")
    log(f"wide_by_company={ {k: len(v) for k, v in by_co.items()} }")
    log(f"focus_by_company={focus_counts}")
    return 0 if kept else 1


if __name__ == "__main__":
    raise SystemExit(main())
