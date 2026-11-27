"""Пакетный сбор новостей патентообладателей/НИИ через custom_sources (crawl+trafilatura).

Данные только для потока «Наука» — пишутся в data/science_org_news/,
НЕ в data/raw (ИТ-контур их не подхватит).

Прогресс сохраняется после каждого источника: при обрыве сети перезапуск
продолжит с незавершённых.

Пример:
  python scripts/scrape_science_org_news.py
  python scripts/scrape_science_org_news.py --limit 3
  python scripts/scrape_science_org_news.py --retry-failed
  python scripts/scrape_science_org_news.py --force
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gartner.custom_sources.engine import ArticleRecord, write_articles_raw
from gartner.custom_sources.llm_gates import LlmBudget
from gartner.custom_sources.pipeline import discover_source, scrape_discovered
from gartner.custom_sources.rules import domain_from_url, normalize_start_url

DEFAULT_SOURCES = ROOT / "data" / "exports" / "org_sites_prompt" / "org_news_sources.json"
# рядом с data/runs/patents — только для потока «Наука»
DEFAULT_OUT_ROOT = ROOT / "data" / "runs" / "science_org_news"

OUT_ROOT = DEFAULT_OUT_ROOT
SOURCES_DIR = OUT_ROOT / "sources"
PROFILES_DIR = OUT_ROOT / "profiles"
PROGRESS_PATH = OUT_ROOT / "progress.json"
MANIFEST_PATH = OUT_ROOT / "manifest.json"
ALL_JSONL = OUT_ROOT / "articles.jsonl"


def configure_paths(out_root: Path) -> None:
    global OUT_ROOT, SOURCES_DIR, PROFILES_DIR, PROGRESS_PATH, MANIFEST_PATH, ALL_JSONL
    OUT_ROOT = out_root
    SOURCES_DIR = OUT_ROOT / "sources"
    PROFILES_DIR = OUT_ROOT / "profiles"
    PROGRESS_PATH = OUT_ROOT / "progress.json"
    MANIFEST_PATH = OUT_ROOT / "manifest.json"
    ALL_JSONL = OUT_ROOT / "articles.jsonl"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def source_id_from_url(url: str) -> str:
    domain = domain_from_url(url)
    digest = hashlib.sha1(domain.encode("utf-8")).hexdigest()[:10]
    safe = "".join(ch if ch.isalnum() else "_" for ch in domain)[:40]
    return f"sci_{safe}_{digest}"


def pick_start_url(row: dict[str, Any]) -> str | None:
    for key in ("news_url", "official_url"):
        value = (row.get(key) or "").strip()
        if value.startswith("http://") or value.startswith("https://"):
            return value
    return None


def load_source_rows(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit(f"Ожидался JSON-массив в {path}")
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        url = pick_start_url(item)
        if not url:
            continue
        try:
            url = normalize_start_url(url)
        except Exception:
            continue
        sid = source_id_from_url(url)
        if sid in seen_ids:
            continue
        seen_ids.add(sid)
        rows.append(
            {
                "source_id": sid,
                "name": (item.get("name") or domain_from_url(url)).strip(),
                "start_url": url,
                "official_url": item.get("official_url"),
                "news_url": item.get("news_url"),
                "confidence": item.get("confidence"),
                "lang": item.get("lang"),
            }
        )
    return rows


def article_day(value: str) -> str:
    text = (value or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return ""


def filter_by_date(
    articles: list[ArticleRecord],
    *,
    date_from: str,
    keep_undated: bool,
) -> tuple[list[ArticleRecord], dict[str, int]]:
    kept: list[ArticleRecord] = []
    stats = {"in_range": 0, "too_old": 0, "undated_kept": 0, "undated_dropped": 0}
    for art in articles:
        day = article_day(art.datatime)
        if not day:
            if keep_undated:
                kept.append(art)
                stats["undated_kept"] += 1
            else:
                stats["undated_dropped"] += 1
            continue
        if day >= date_from:
            kept.append(art)
            stats["in_range"] += 1
        else:
            stats["too_old"] += 1
    return kept, stats


def enrich_records(
    articles: list[ArticleRecord],
    *,
    org_name: str,
    source_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for art in articles:
        row = art.as_dict()
        row["org_name"] = org_name
        row["source_id"] = source_id
        row["scraped_at"] = utc_now()
        rows.append(row)
    return rows


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def rebuild_jsonl_from_sources() -> int:
    """Пересобрать articles.jsonl из per-source файлов (после resume)."""
    rows: list[dict[str, Any]] = []
    for path in sorted(SOURCES_DIR.glob("*.json")):
        payload = load_json(path, {})
        arts = payload.get("articles") if isinstance(payload, dict) else None
        if isinstance(arts, list):
            rows.extend(arts)
    tmp = ALL_JSONL.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(ALL_JSONL)
    return len(rows)


def default_progress(date_from: str) -> dict[str, Any]:
    return {
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "date_from": date_from,
        "out_root": str(OUT_ROOT),
        "sources": {},
    }


def scrape_one(
    row: dict[str, Any],
    *,
    max_articles: int,
    max_hub_pages: int,
    date_from: str,
    keep_undated: bool,
    use_llm: bool,
    llm: Any | None = None,
    rediscover: bool = False,
    force_browser: bool = False,
) -> dict[str, Any]:
    sid = row["source_id"]
    url = row["start_url"]
    client = None
    if use_llm:
        from gartner.llm import LLMClient

        client = llm if llm is not None else LLMClient()

    budget = LlmBudget()
    profile_path = PROFILES_DIR / f"{sid}.json"
    discovered = None if rediscover else load_json(profile_path, None)
    # битый/пустой профиль или 404 стартовой — переdiscover
    theme_reason = str(((discovered or {}).get("theme") or {}).get("reason") or "")
    hubs = (discovered or {}).get("hubs") if isinstance(discovered, dict) else None
    bad_profile = (
        not isinstance(discovered, dict)
        or not discovered.get("start_url")
        or "404" in theme_reason
        or "fetch_fail" in theme_reason
        or not hubs
    )
    if rediscover or bad_profile:
        discovered = discover_source(url, llm=client, budget=budget)
        atomic_write_json(profile_path, discovered)

    articles, scrape_stats = scrape_discovered(
        discovered,
        max_articles=max_articles,
        llm=client,
        budget=budget,
        max_hub_pages=max_hub_pages,
        force_browser=force_browser,
    )
    # пусто → ещё раз: rediscover + browser
    if not articles and not force_browser:
        discovered = discover_source(url, llm=client, budget=LlmBudget())
        atomic_write_json(profile_path, discovered)
        articles, scrape_stats = scrape_discovered(
            discovered,
            max_articles=max_articles,
            llm=client,
            budget=LlmBudget(),
            max_hub_pages=max_hub_pages,
            force_browser=True,
        )
        scrape_stats = dict(scrape_stats)
        scrape_stats["retried_browser"] = True
    filtered, date_stats = filter_by_date(
        articles, date_from=date_from, keep_undated=keep_undated
    )
    # источник в записи — домен; org_name отдельно
    for art in filtered:
        if not art.source:
            art.source = domain_from_url(url)

    enriched = enrich_records(filtered, org_name=row["name"], source_id=sid)
    payload = {
        "source_id": sid,
        "name": row["name"],
        "start_url": url,
        "official_url": row.get("official_url"),
        "news_url": row.get("news_url"),
        "scraped_at": utc_now(),
        "date_from": date_from,
        "raw_fetched": len(articles),
        "kept": len(enriched),
        "date_stats": date_stats,
        "scrape_stats": scrape_stats,
        "articles": enriched,
    }
    # полный payload (для resume/rebuild); CSV — плоский список статей
    atomic_write_json(SOURCES_DIR / f"{sid}.json", payload)
    if filtered:
        write_articles_raw(filtered, SOURCES_DIR / f"{sid}_flat")
    return {
        "articles": enriched,
        "raw_fetched": len(articles),
        "kept": len(enriched),
        "date_stats": date_stats,
        "scrape_stats": scrape_stats,
        "list_url": (discovered.get("hubs") or [{}])[0].get("url") or url,
        "domain": discovered.get("domain") or domain_from_url(url),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Скрапинг новостей через universal custom_sources → data/runs/science_org_news"
    )
    parser.add_argument(
        "--sources",
        type=Path,
        default=DEFAULT_SOURCES,
        help="JSON со списком организаций (news_url/official_url)",
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=DEFAULT_OUT_ROOT,
        help="Каталог вывода (по умолчанию рядом с patents: data/runs/science_org_news)",
    )
    parser.add_argument(
        "--date-from",
        default="2025-10-23",
        help="Оставлять статьи с datatime >= этой даты (YYYY-MM-DD); 12 мес. от 2026-10-23",
    )
    parser.add_argument(
        "--keep-undated",
        action="store_true",
        help="Не отбрасывать статьи без распознанной даты",
    )
    parser.add_argument("--max-articles", type=int, default=120, help="Макс. статей с сайта до фильтра даты")
    parser.add_argument("--max-hub-pages", type=int, default=12, help="Страниц пагинации хаба новостей")
    parser.add_argument("--delay", type=float, default=0.3, help="Пауза между источниками в одном воркере (сек)")
    parser.add_argument("--workers", type=int, default=4, help="Параллельных воркеров (потоки)")
    parser.add_argument("--limit", type=int, default=0, help="Обработать только N источников (0 = все)")
    parser.add_argument("--offset", type=int, default=0, help="Пропустить первые N источников списка")
    parser.add_argument("--only", type=str, default="", help="Подстрока имени/домена/URL (фильтр)")
    parser.add_argument("--force", action="store_true", help="Пересканировать уже успешные")
    parser.add_argument("--retry-failed", action="store_true", help="Только failed/error")
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Включить LLM-гейты (нужен API_KEY/BASE_URL/LLM_MODEL в env)",
    )
    parser.add_argument(
        "--rebuild-jsonl",
        action="store_true",
        help="Только пересобрать articles.jsonl из sources/*.json и выйти",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_paths(args.out_root.resolve())
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    if args.rebuild_jsonl:
        n = rebuild_jsonl_from_sources()
        print(f"Пересобран {ALL_JSONL} · {n} статей")
        return 0

    if not args.sources.exists():
        print(f"Нет файла источников: {args.sources}", file=sys.stderr)
        return 1

    rows = load_source_rows(args.sources)
    if args.only:
        q = args.only.lower()
        rows = [
            r
            for r in rows
            if q in r["name"].lower()
            or q in r["start_url"].lower()
            or q in r["source_id"].lower()
        ]
    rows = rows[args.offset :]
    if args.limit > 0:
        rows = rows[: args.limit]

    progress = load_json(PROGRESS_PATH, None)
    if not isinstance(progress, dict) or "sources" not in progress:
        progress = default_progress(args.date_from)
    progress["date_from"] = args.date_from
    progress.setdefault("sources", {})
    progress_lock = threading.Lock()

    print(f"Источников в очереди: {len(rows)}")
    print(f"Выход: {OUT_ROOT}")
    print(f"Дата с: {args.date_from} · undated={'keep' if args.keep_undated else 'drop'}")
    print(f"LLM: {'on' if args.llm else 'off'} · workers={max(1, args.workers)}")

    counters = {"done": 0, "failed": 0, "skipped": 0}
    counters_lock = threading.Lock()

    def process_row(index: int, row: dict[str, Any]) -> None:
        sid = row["source_id"]
        with progress_lock:
            prev = progress["sources"].get(sid) or {}
            status = prev.get("status")
            if args.retry_failed and status not in {"failed", "error"}:
                with counters_lock:
                    counters["skipped"] += 1
                return
            if not args.force and not args.retry_failed and status == "done":
                print(f"[{index}/{len(rows)}] SKIP done · {row['name']}", flush=True)
                with counters_lock:
                    counters["skipped"] += 1
                return
            started = utc_now()
            progress["sources"][sid] = {
                "name": row["name"],
                "start_url": row["start_url"],
                "status": "running",
                "started_at": started,
                "updated_at": started,
            }
            atomic_write_json(PROGRESS_PATH, progress)

        print(f"[{index}/{len(rows)}] {row['name']}", flush=True)
        print(f"         {row['start_url']}", flush=True)
        try:
            result = scrape_one(
                row,
                max_articles=args.max_articles,
                max_hub_pages=args.max_hub_pages,
                date_from=args.date_from,
                keep_undated=args.keep_undated,
                use_llm=args.llm,
            )
            with progress_lock:
                if not args.force:
                    append_jsonl(ALL_JSONL, result["articles"])
                progress["sources"][sid] = {
                    "name": row["name"],
                    "start_url": row["start_url"],
                    "domain": result.get("domain"),
                    "list_url": result.get("list_url"),
                    "status": "done",
                    "articles": result["kept"],
                    "raw_fetched": result["raw_fetched"],
                    "date_stats": result["date_stats"],
                    "started_at": started,
                    "updated_at": utc_now(),
                    "error": None,
                }
                progress["updated_at"] = utc_now()
                atomic_write_json(PROGRESS_PATH, progress)
            with counters_lock:
                counters["done"] += 1
            print(
                f"         OK · raw={result['raw_fetched']} kept={result['kept']} "
                f"({result['date_stats']})",
                flush=True,
            )
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            with progress_lock:
                progress["sources"][sid] = {
                    "name": row["name"],
                    "start_url": row["start_url"],
                    "status": "failed",
                    "started_at": started,
                    "updated_at": utc_now(),
                    "error": err,
                }
                progress["updated_at"] = utc_now()
                atomic_write_json(PROGRESS_PATH, progress)
            with counters_lock:
                counters["failed"] += 1
            print(f"         FAIL · {err}", flush=True)
            traceback.print_exc(limit=2)
        if args.delay > 0:
            time.sleep(args.delay)

    workers = max(1, int(args.workers))
    try:
        if workers == 1:
            for index, row in enumerate(rows, start=1):
                process_row(index, row)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = {
                    pool.submit(process_row, index, row): row
                    for index, row in enumerate(rows, start=1)
                }
                for fut in as_completed(futs):
                    # surface unexpected thread errors
                    fut.result()
    except KeyboardInterrupt:
        print("\nОстановлено пользователем. Прогресс сохранён — можно продолжить тем же запуском.")
        return 130

    with progress_lock:
        atomic_write_json(
            MANIFEST_PATH,
            {
                "updated_at": utc_now(),
                "date_from": args.date_from,
                "sources_file": str(args.sources),
                "out_root": str(OUT_ROOT),
                "workers": workers,
                "llm": bool(args.llm),
                "note": "Только для потока Наука; не смешивается с data/raw ИТ-контура.",
                "counts": {
                    "listed": len(load_source_rows(args.sources)),
                    "progress_done": sum(
                        1 for s in progress["sources"].values() if s.get("status") == "done"
                    ),
                    "progress_failed": sum(
                        1 for s in progress["sources"].values() if s.get("status") == "failed"
                    ),
                },
            },
        )

    total_arts = rebuild_jsonl_from_sources()
    print(
        f"\nГотово. done={counters['done']} failed={counters['failed']} "
        f"skipped={counters['skipped']} · статей в {ALL_JSONL.name}: {total_arts}"
    )
    print(f"Прогресс: {PROGRESS_PATH}")
    return 0 if counters["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
