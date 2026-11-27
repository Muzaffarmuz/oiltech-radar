"""Lab LLM: разметка статей 5 сайтов в потоки investments / policy.

Lab: http://d.dgx:54000/v1 · qwen3-32b · <LAB_API_KEY>

Запуск из корня репозитория:

  # связь
  python scripts/tag_flows_lab.py --ping

  # тест
  python scripts/tag_flows_lab.py --limit 30 --workers 4

  # полный (Interfax по умолчанию ≤1 новость/день, иначе ~11k вызовов)
  python scripts/tag_flows_lab.py --workers 4 --resume

  # все статьи Interfax
  python scripts/tag_flows_lab.py --interfax-per-day 0 --workers 4 --resume

  # залить ответы в SQLite (merge с уже стоящими метками)
  python scripts/tag_flows_lab.py --resume --apply

Без --apply пишет только sidecar:
  data/runs/flow_tags/tagged_lab_investments_policy.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts._lab_credentials import lab_base_url, lab_api_key, lab_model, ensure_no_proxy
ensure_no_proxy()
BASE_URL = lab_base_url()
API_KEY = lab_api_key()
MODEL_NAME = "qwen3-32b"


from gartner.config import FLOW_TAGS_DIR, Settings, ensure_dirs  # noqa: E402
from gartner.flow_tags import normalize_flow_tags  # noqa: E402
from gartner.llm import LLMClient  # noqa: E402
from gartner.pipeline.heuristic_flow_split import (  # noqa: E402
    DEFAULT_SOURCES,
    apply_tags_to_db,
    classify_article,
    load_source_articles,
)

OUT_PATH = FLOW_TAGS_DIR / "tagged_lab_investments_policy.json"
DECISIONS_PATH = FLOW_TAGS_DIR / "lab_investments_policy_decisions.jsonl"
REPORT_PATH = FLOW_TAGS_DIR / "tagged_lab_investments_policy_report.json"
TEXT_LIMIT = 4500

PROMPT = """
Ты размечаешь статью для OilTech Radar. Нужны только ДВА потока (можно оба, можно один).
Если ни один не подходит по смыслу текста — всё равно выбери БЛИЖАЙШИЙ один
(для обзора корпуса лучше не оставлять пусто).

Потоки:
- policy: политика и рынок — санкции, законы, регулятор, тарифы, ставка ЦБ, аварии,
  экспорт/импорт, цены, решения властей, рыночные условия.
- investments: инвестиции и стартапы — сделки, раунды, гранты, капвложения, IPO,
  покупка доли, проектное финансирование, новый игрок с капиталом.

Дополнительно можно поставить digital вместе с потоком, если в тексте есть
конкретная ИТ/цифровая технология (не общий лозунг «цифровизация»).

Верни ТОЛЬКО JSON:
{
  "tags": ["policy"],
  "reasons": {"policy": "короткая фраза"}
}
В tags только: policy, investments, digital.
"""


def make_client() -> LLMClient:
    return LLMClient(
        Settings(API_KEY=API_KEY, BASE_URL=BASE_URL, LLM_MODEL=MODEL_NAME)
    )


def one_interfax_per_day(articles: list[dict[str, Any]], per_day: int) -> list[dict[str, Any]]:
    if per_day <= 0:
        return articles
    kept_day: Counter[str] = Counter()
    out: list[dict[str, Any]] = []
    for row in articles:
        src = str(row.get("source") or "").lower().removeprefix("www.")
        if src != "interfax.ru":
            out.append(row)
            continue
        day = str(row.get("datatime") or "")[:10]
        if kept_day[day] >= per_day:
            continue
        kept_day[day] += 1
        out.append(row)
    return out


def load_decisions(path: Path) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return found
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            link = str(row.get("link") or "")
            if link:
                found[link] = row
    return found


def append_decision(path: Path, row: dict[str, Any], lock: threading.Lock) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def parse_tags(raw: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    tags_raw = raw.get("tags") or []
    if not isinstance(tags_raw, list):
        raise ValueError("tags")
    cleaned = normalize_flow_tags([str(t).strip() for t in tags_raw if str(t).strip()])
    # гарантируем хотя бы один из двух потоков
    if "policy" not in cleaned and "investments" not in cleaned:
        cleaned = normalize_flow_tags([*cleaned, "policy"])
    reasons_raw = raw.get("reasons") or {}
    reasons: dict[str, str] = {}
    if isinstance(reasons_raw, dict):
        for tag in cleaned:
            reason = str(reasons_raw.get(tag) or "").strip()
            if reason:
                reasons[tag] = reason[:200]
    return cleaned, reasons


def llm_tag(client: LLMClient, article: dict[str, Any]) -> dict[str, Any]:
    text = str(article.get("text") or "")
    if len(text) > TEXT_LIMIT:
        text = text[:TEXT_LIMIT]
    try:
        raw = client.json_call(
            PROMPT,
            {
                "title": article.get("title"),
                "source": article.get("source"),
                "datatime": article.get("datatime"),
                "text": text,
            },
            max_retries=2,
        )
        tags, reasons = parse_tags(raw)
        return {
            "link": article["link"],
            "title": article["title"],
            "datatime": article.get("datatime"),
            "source": article.get("source"),
            "article_id": article.get("article_id"),
            "flow_tags": tags,
            "tag_reasons": reasons,
            "method": "llm",
            "existing_tags": article.get("existing_tags") or [],
        }
    except Exception as exc:
        fallback = classify_article(
            title=str(article.get("title") or ""),
            text=str(article.get("text") or ""),
            source=str(article.get("source") or ""),
        )
        return {
            "link": article["link"],
            "title": article["title"],
            "datatime": article.get("datatime"),
            "source": article.get("source"),
            "article_id": article.get("article_id"),
            "flow_tags": fallback["flow_tags"],
            "tag_reasons": {
                **fallback["tag_reasons"],
                "_error": f"{type(exc).__name__}: {exc}",
            },
            "method": "llm_error_heuristic",
            "existing_tags": article.get("existing_tags") or [],
        }


def merge_row(row: dict[str, Any]) -> dict[str, Any]:
    existing = [str(t) for t in (row.get("existing_tags") or [])]
    tags = normalize_flow_tags([*existing, *[str(t) for t in (row.get("flow_tags") or [])]])
    out = dict(row)
    out["flow_tags"] = tags
    return out


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_tag: Counter[str] = Counter()
    by_source: dict[str, Counter[str]] = {}
    methods: Counter[str] = Counter()
    for row in rows:
        methods[str(row.get("method") or "?")] += 1
        src = str(row.get("source") or "?")
        by_source.setdefault(src, Counter())
        for t in row.get("flow_tags") or []:
            by_tag[str(t)] += 1
            if str(t) in ("investments", "policy"):
                by_source[src][str(t)] += 1
    return {
        "articles": len(rows),
        "by_tag": dict(by_tag),
        "by_source": {s: dict(c) for s, c in sorted(by_source.items())},
        "methods": dict(methods),
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Lab LLM → investments/policy")
    p.add_argument("--sources", default=",".join(DEFAULT_SOURCES))
    p.add_argument("--only-untagged", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--interfax-per-day", type=int, default=1)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--ping", action="store_true")
    p.add_argument("--out", type=Path, default=OUT_PATH)
    p.add_argument("--decisions", type=Path, default=DECISIONS_PATH)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    ensure_dirs()
    client = make_client()
    if not client.enabled:
        print("LLM disabled", file=sys.stderr)
        return 2

    if args.ping:
        try:
            print("Lab OK:", client.json_call('Верни {"ok": true}', {"x": 1}, max_retries=1))
            return 0
        except Exception as exc:
            print("Lab FAIL:", type(exc).__name__, exc, file=sys.stderr)
            return 1

    sources = tuple(s.strip() for s in str(args.sources).split(",") if s.strip())
    articles = load_source_articles(
        sources,
        only_untagged=bool(args.only_untagged),
        limit=0,
    )
    before_ifx = sum(1 for a in articles if str(a.get("source") or "").endswith("interfax.ru"))
    articles = one_interfax_per_day(articles, int(args.interfax_per_day))
    after_ifx = sum(1 for a in articles if str(a.get("source") or "").endswith("interfax.ru"))
    print(f"Interfax: {after_ifx} из {before_ifx} (per-day={args.interfax_per_day})")
    if args.limit > 0:
        articles = articles[: int(args.limit)]
    print(f"к разметке: {len(articles)}")

    done = load_decisions(args.decisions) if args.resume else {}
    todo = [a for a in articles if a["link"] not in done]
    print(f"уже в decisions: {len(done)} · запрос: {len(todo)} · workers={args.workers}")

    lock = threading.Lock()
    t0 = time.time()
    ok = err = 0

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = {pool.submit(llm_tag, client, a): a for a in todo}
        for i, fut in enumerate(as_completed(futs), start=1):
            row = fut.result()
            append_decision(args.decisions, row, lock)
            done[row["link"]] = row
            if row.get("method") == "llm":
                ok += 1
            else:
                err += 1
            if i % 20 == 0 or i == len(futs):
                print(f"  [{i}/{len(futs)}] ok={ok} err={err} {time.time()-t0:.0f}s")

    # собрать sidecar в порядке articles
    link_set = {a["link"] for a in articles}
    rows = [merge_row(done[a["link"]]) for a in articles if a["link"] in done]
    # если resume и в decisions лишнее — не пишем
    rows = [r for r in rows if r.get("link") in link_set]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    report = summarize(rows)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"sidecar -> {args.out}")
    print(f"report  -> {REPORT_PATH}")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.apply:
        stats = apply_tags_to_db(rows, merge_existing=True)
        print("apply:", json.dumps(stats, ensure_ascii=False))
    else:
        print("БД не трогали. Залить: python scripts/tag_flows_lab.py --resume --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
