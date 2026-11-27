#!/usr/bin/env python3
"""
Сбор новостей иностранных нефтегазовых компаний.

Для источников с ручным адаптером (сейчас: chevron, eni, conocophillips, petrobras)
используется sitemap/лента → extract → keyword IT → Lab LLM.
Остальные — старый generic crawl (пока).

Запуск из корня проекта:
  py -3 foreign_it_news/scrape_foreign_it_news.py --only chevron,eni,conocophillips,petrobras
  py -3 foreign_it_news/scrape_foreign_it_news.py --adapters-only
  py -3 foreign_it_news/scrape_foreign_it_news.py --skip-it-gate

Креды Lab — из .env (LAB_API_KEY / API_KEY, LAB_BASE_URL / BASE_URL).
Результаты: foreign_it_news/out/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import date, datetime
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
from gartner.custom_sources.engine import ArticleRecord, write_articles_raw  # noqa: E402
from gartner.custom_sources.llm_gates import LlmBudget, llm_ready  # noqa: E402
from gartner.custom_sources.pipeline import discover_source, scrape_discovered  # noqa: E402
from gartner.llm import LLMClient  # noqa: E402

from foreign_it_news.adapters import ADAPTERS, get_adapter  # noqa: E402
from foreign_it_news.adapters.base import run_adapter  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out"
SOURCES_PATH = HERE / "sources.json"
MIN_DATE = date(2026, 1, 1)

# префикс всех логов — видно, что жив именно этот скрапер
RUN_TAG = "foreign-it-scraper"


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{RUN_TAG} {ts}] {msg}", flush=True)


def make_llm() -> LLMClient:
    client = LLMClient(
        Settings(
            API_KEY=API_KEY,
            BASE_URL=BASE_URL,
            LLM_MODEL=MODEL_NAME,
        )
    )
    # иначе зависания Lab без ответа блокируют весь прогон
    if client._client is not None:
        try:
            client._client = client._client.with_options(timeout=90.0)
        except Exception:
            pass
    return client


IT_PROMPT = """
You filter oil & gas company press releases for an IT / automation technology radar.
Return ONLY JSON: {"keep": true|false, "reason": "short"}

keep=true ONLY if the PRIMARY topic is digital / IT / automation in oil & gas, e.g.:
software platforms, digital twin, AI/ML for subsurface or operations, cloud/data platforms,
cybersecurity programs, robotics/UAVs as the story focus, autonomous operations,
IoT/sensor analytics, SCADA/MES upgrades, remote monitoring systems, industrial software,
automation of drilling/production/refining, major IT/digital partnerships.

keep=false if digital tools are only incidental (e.g. drones briefly mentioned in a CSR/land
restoration / community / sports / people story), or for: financial results, dividends,
buybacks, board appointments, pure exploration FID without digital angle, LNG cargo logistics
without IT, legal/HR-only notes, podcasts/marketing fluff, empty promo pages.
""".strip()


def load_sources() -> list[dict[str, str]]:
    return json.loads(SOURCES_PATH.read_text(encoding="utf-8"))


def parse_article_date(value: str) -> date | None:
    raw = (value or "").strip()
    if not raw:
        return None
    head = raw.replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d"):
        chunk = head[: len("2026-01-01T00:00:00")] if "T" in fmt or " " in fmt else head[:10]
        try:
            return datetime.strptime(chunk, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _lab_chat_json(prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Прямой chat.completions к Lab (как ping_lab_chat) — без responses API."""
    from openai import OpenAI

    from gartner.llm import extract_json_object, get_response_text

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=45.0)
    body = json.dumps(payload, ensure_ascii=False)
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": body},
        ],
        max_tokens=180,
    )
    return extract_json_object(get_response_text(response))


def judge_it_automation(
    llm: LLMClient, rec: ArticleRecord, *, budget: LlmBudget
) -> tuple[bool | None, str]:
    """(decision, reason). decision None — бюджет/сбой."""
    if not llm_ready(llm):
        return None, "llm_not_ready"
    if not budget.take("keep"):
        return None, "budget"
    try:
        raw = _lab_chat_json(
            IT_PROMPT,
            {
                "title": (rec.title or "")[:300],
                "date": rec.datatime or "",
                "url": rec.link or "",
                "text_preview": (rec.text or "")[:1200],
            },
        )
    except Exception as exc:
        budget.used["errors"] = budget.used.get("errors", 0) + 1
        return None, f"error:{type(exc).__name__}:{exc}"[:180]
    if not raw or "keep" not in raw:
        return None, "bad_response"
    keep = bool(raw.get("keep"))
    reason = str(raw.get("reason") or "")[:240]
    if not keep:
        budget.used["drop"] = budget.used.get("drop", 0) + 1
    return keep, reason


def rec_to_dict(rec: ArticleRecord, *, company: str, company_id: str) -> dict[str, Any]:
    return {
        "company_id": company_id,
        "company": company,
        "title": rec.title,
        "text": rec.text,
        "datatime": rec.datatime,
        "source": rec.source,
        "link": rec.link,
    }


def scrape_one(
    src: dict[str, str],
    llm: LLMClient,
    *,
    max_articles: int,
    max_hub_pages: int,
    skip_it_gate: bool,
    require_oilgas: bool,
) -> dict[str, Any]:
    company_id = src["id"]
    name = src["name"]
    url = src["start_url"]
    report: dict[str, Any] = {
        "company_id": company_id,
        "company": name,
        "start_url": url,
        "ok": False,
        "error": None,
        "discovered": {},
        "raw_n": 0,
        "from_2026_n": 0,
        "kept_it_n": 0,
        "dropped_date": 0,
        "dropped_it": 0,
        "undated": 0,
        "llm_stats": {},
        "articles": [],
    }

    log(f"  → discover: {url}")
    discover_budget = LlmBudget(kind_limit=12, title_limit=4, keep_limit=4, theme_limit=2)
    discovered = discover_source(url, llm=llm, budget=discover_budget)
    theme = discovered.get("theme") or {}
    hubs = discovered.get("hubs") or []
    report["discovered"] = {
        "domain": discovered.get("domain"),
        "theme": theme,
        "hubs": [h.get("url") for h in hubs[:8]],
        "pages_fetched": discovered.get("pages_fetched"),
        "needs_browser": discovered.get("needs_browser"),
        "protection": discovered.get("protection"),
        "llm_stats": discovered.get("llm_stats"),
    }
    log(
        f"  ← discover done: domain={discovered.get('domain')} "
        f"hubs={len(hubs)} theme_ok={bool(theme.get('accepted'))} "
        f"browser={bool(discovered.get('needs_browser'))}"
    )

    if require_oilgas and not theme.get("accepted"):
        report["error"] = f"сайт отклонён по тематике: {theme.get('reason') or theme}"
        log(f"  ✕ skip: {report['error']}")
        return report

    log(f"  → scrape (max_articles={max_articles}, hub_pages={max_hub_pages}) …")
    scrape_budget = LlmBudget(
        kind_limit=40,
        title_limit=40,
        keep_limit=max(max_articles + 40, 80),
        theme_limit=0,
    )
    articles, stats = scrape_discovered(
        discovered,
        max_articles=max_articles,
        llm=llm,
        budget=scrape_budget,
        max_hub_pages=max_hub_pages,
        force_browser=bool(discovered.get("needs_browser")),
    )
    report["raw_n"] = len(articles)
    report["llm_stats"] = {
        "discover": discover_budget.as_dict(),
        "scrape": stats.get("llm_stats") or scrape_budget.as_dict(),
        "links_found": stats.get("links_found"),
        "browser": stats.get("browser"),
    }
    log(f"  ← scrape done: raw={len(articles)} links_found={stats.get('links_found')}")

    it_budget = LlmBudget(
        kind_limit=0,
        title_limit=0,
        keep_limit=max(len(articles) + 10, 50),
        theme_limit=0,
    )
    kept: list[dict[str, Any]] = []
    total = len(articles)
    if skip_it_gate:
        log(f"  → filter dates (IT-gate off), n={total}")
    else:
        log(f"  → filter dates + IT-gate LLM, n={total}")

    for idx, rec in enumerate(articles, 1):
        if idx == 1 or idx % 10 == 0 or idx == total:
            log(f"  … article {idx}/{total} kept={len(kept)} drop_date={report['dropped_date']} drop_it={report['dropped_it']}")
        d = parse_article_date(rec.datatime)
        if d is None:
            report["undated"] += 1
            report["dropped_date"] += 1
            continue
        if d < MIN_DATE:
            report["dropped_date"] += 1
            continue
        report["from_2026_n"] += 1

        if not skip_it_gate:
            decision, reason = judge_it_automation(llm, rec, budget=it_budget)
            if decision is False:
                report["dropped_it"] += 1
                continue
            # decision True или None (сбой/бюджет) — оставляем, помечаем
            row = rec_to_dict(rec, company=name, company_id=company_id)
            row["it_gate"] = {True: "keep", None: "skip_or_error"}.get(decision, "keep")
            row["it_reason"] = reason
        else:
            row = rec_to_dict(rec, company=name, company_id=company_id)
            row["it_gate"] = "disabled"

        kept.append(row)


def scrape_one_adapter(
    src: dict[str, str],
    llm: LLMClient,
    *,
    max_articles: int,
    skip_it_gate: bool,
) -> dict[str, Any]:
    company_id = src["id"]
    name = src["name"]
    adapter = get_adapter(company_id)
    assert adapter is not None
    log(f"  → adapter={company_id}")
    it_budget = LlmBudget(kind_limit=0, title_limit=0, keep_limit=max(max_articles + 20, 80), theme_limit=0)

    def _judge(rec: ArticleRecord) -> tuple[bool | None, str]:
        return judge_it_automation(llm, rec, budget=it_budget)

    result = run_adapter(
        company_id=company_id,
        company=name,
        list_items=adapter["list_articles"],
        max_articles=max_articles,
        skip_it_gate=skip_it_gate,
        judge_it=_judge,
        log=log,
    )
    return {
        "company_id": company_id,
        "company": name,
        "start_url": src.get("start_url"),
        "ok": not result.errors or result.listed > 0,
        "error": "; ".join(result.errors[:3]) if result.errors and result.listed == 0 else None,
        "mode": "adapter",
        "listed_n": result.listed,
        "raw_n": result.fetched,
        "from_2026_n": result.from_2026,
        "kept_it_n": result.kept_it,
        "dropped_date": result.dropped_date,
        "dropped_keyword": result.dropped_keyword,
        "dropped_it": result.dropped_it,
        "extract_fail": result.extract_fail,
        "llm_stats": {"it_gate": it_budget.as_dict()},
        "articles": result.articles,
    }

    report["kept_it_n"] = len(kept)
    report["articles"] = kept
    report["ok"] = True
    report["llm_stats"]["it_gate"] = it_budget.as_dict()
    log(f"  ✓ company done: kept_it={len(kept)} from_2026={report['from_2026_n']}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Foreign majors → IT/automation news from 2026 via Oil Radar parser + Lab LLM")
    parser.add_argument("--only", default="", help="id через запятую: chevron,eni")
    parser.add_argument("--max-articles", type=int, default=80, help="макс. статей на источник при scrape")
    parser.add_argument("--max-hub-pages", type=int, default=8, help="глубина пагинации хабов (generic)")
    parser.add_argument("--skip-it-gate", action="store_true", help="не фильтровать ИТ LLM (оставить всё после даты)")
    parser.add_argument(
        "--keyword-only",
        action="store_true",
        help="для адаптеров: IT только по keyword-prefilter, без Lab LLM",
    )
    parser.add_argument("--allow-non-oilgas", action="store_true", help="generic: не отклонять theme.accepted=false")
    parser.add_argument(
        "--adapters-only",
        action="store_true",
        help=f"только ручные адаптеры: {','.join(sorted(ADAPTERS))}",
    )
    parser.add_argument(
        "--generic-only",
        action="store_true",
        help="игнорировать адаптеры, старый crawl",
    )
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="папка результатов")
    args = parser.parse_args()

    llm = make_llm()
    if not llm.enabled:
        print(
            f"LLM выключен при явных кредах: model={MODEL_NAME} url={BASE_URL}",
            file=sys.stderr,
        )
        return 2

    sources = load_sources()
    if args.adapters_only:
        sources = [s for s in sources if s["id"].lower() in ADAPTERS]
    if args.only.strip():
        want = {x.strip().lower() for x in args.only.split(",") if x.strip()}
        sources = [s for s in sources if s["id"].lower() in want]
        if not sources:
            print(f"Нет источников по --only {want}", file=sys.stderr)
            return 2

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    per_dir = out_dir / "by_company"
    per_dir.mkdir(parents=True, exist_ok=True)

    log(f"START pid={os.getpid()} model={MODEL_NAME} @ {BASE_URL}")
    log(f"NO_PROXY={os.environ.get('NO_PROXY')}")
    log(f"adapters={sorted(ADAPTERS)} adapters_only={args.adapters_only} generic_only={args.generic_only}")
    log(f"sources={len(sources)} min_date={MIN_DATE.isoformat()} out={out_dir}")

    all_articles: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []

    for i, src in enumerate(sources, 1):
        log(f"==== source {i}/{len(sources)} · {src['id']} · {src['name']} ====")
        log(f"url={src['start_url']}")
        use_adapter = (not args.generic_only) and get_adapter(src["id"]) is not None
        try:
            if use_adapter:
                report = scrape_one_adapter(
                    src,
                    llm,
                    max_articles=args.max_articles,
                    skip_it_gate=args.skip_it_gate or args.keyword_only,
                )
                if args.keyword_only:
                    for row in report.get("articles") or []:
                        row["it_gate"] = "keyword"
            else:
                report = scrape_one(
                    src,
                    llm,
                    max_articles=args.max_articles,
                    max_hub_pages=args.max_hub_pages,
                    skip_it_gate=args.skip_it_gate,
                    require_oilgas=not args.allow_non_oilgas,
                )
        except Exception as exc:
            report = {
                "company_id": src["id"],
                "company": src["name"],
                "start_url": src["start_url"],
                "ok": False,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "articles": [],
            }
            log(f"  ERROR: {exc}")

        articles = report.get("articles") or []
        slim = {k: v for k, v in report.items() if k != "articles"}
        summaries.append(slim)
        all_articles.extend(articles)

        company_path = per_dir / src["id"]
        # raw в формате парсера + полный отчёт
        if articles:
            records = [
                ArticleRecord(
                    title=a["title"],
                    text=a["text"],
                    datatime=a.get("datatime") or "",
                    source=a.get("source") or src["id"],
                    link=a["link"],
                )
                for a in articles
            ]
            write_articles_raw(records, company_path)
        (per_dir / f"{src['id']}_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log(
            f"  summary mode={report.get('mode', 'generic')} listed={report.get('listed_n', '-')} "
            f"raw={report.get('raw_n', 0)} from2026={report.get('from_2026_n', 0)} "
            f"kept_it={report.get('kept_it_n', 0)} drop_kw={report.get('dropped_keyword', 0)} "
            f"err={report.get('error')}"
        )

    combined = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "min_date": MIN_DATE.isoformat(),
        "llm_model": MODEL_NAME,
        "base_url": BASE_URL,
        "skip_it_gate": args.skip_it_gate,
        "sources": summaries,
        "n_articles": len(all_articles),
        "articles": all_articles,
    }
    (out_dir / "all_articles.json").write_text(
        json.dumps(combined, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "summary.json").write_text(
        json.dumps(
            {
                "generated_at": combined["generated_at"],
                "n_articles": len(all_articles),
                "sources": summaries,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    log(f"DONE articles={len(all_articles)} → {out_dir / 'all_articles.json'}")
    return 0 if any(s.get("ok") for s in summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
