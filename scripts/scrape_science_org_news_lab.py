"""Скрап всех сайтов Наука с Lab LLM — параллельно, компактный прогресс.

  python scripts/scrape_science_org_news_lab.py
  python scripts/scrape_science_org_news_lab.py --workers 6
  python scripts/scrape_science_org_news_lab.py --resume
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts._lab_credentials import lab_base_url, lab_api_key, lab_model, ensure_no_proxy
ensure_no_proxy()
# --- Lab LLM: явные креды ---
BASE_URL = lab_base_url()
API_KEY = lab_api_key()
MODEL_NAME = "qwen3-32b"
# -----------------------------


from gartner.config import Settings  # noqa: E402
from gartner.llm import LLMClient  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
import scrape_science_org_news as base  # noqa: E402


class CompactProgress:
    """Одна обновляемая строка + короткие события внизу."""

    def __init__(self, total: int) -> None:
        self.total = max(1, total)
        self.lock = threading.Lock()
        self.ok = 0
        self.empty = 0
        self.fail = 0
        self.skip = 0
        self.finished = 0
        self.running: dict[str, str] = {}  # sid -> short name
        self._last_len = 0
        self.t0 = time.time()

    def _bar(self, width: int = 22) -> str:
        done = self.finished
        filled = int(width * done / self.total)
        return "[" + "#" * filled + "-" * (width - filled) + "]"

    def _line(self) -> str:
        names = list(self.running.values())[:3]
        run = ", ".join(names) if names else "…"
        if len(self.running) > 3:
            run += f" +{len(self.running) - 3}"
        elapsed = int(time.time() - self.t0)
        return (
            f"{self._bar()} {self.finished}/{self.total} "
            f"ok:{self.ok} empty:{self.empty} fail:{self.fail} skip:{self.skip} "
            f"| {elapsed}s | {run}"
        )[:118]

    def paint(self) -> None:
        line = self._line()
        pad = max(0, self._last_len - len(line))
        sys.stdout.write("\r" + line + (" " * pad))
        sys.stdout.flush()
        self._last_len = len(line)

    def event(self, text: str) -> None:
        """Короткое событие новой строкой, затем снова прогресс."""
        sys.stdout.write("\r" + (" " * self._last_len) + "\r")
        print(text[:120], flush=True)
        self._last_len = 0
        self.paint()

    def start(self, sid: str, name: str) -> None:
        with self.lock:
            self.running[sid] = (name or sid)[:28]
            self.paint()

    def finish(
        self,
        sid: str,
        *,
        kind: str,
        name: str,
        detail: str = "",
    ) -> None:
        with self.lock:
            self.running.pop(sid, None)
            self.finished += 1
            if kind == "ok":
                self.ok += 1
            elif kind == "empty":
                self.empty += 1
            elif kind == "fail":
                self.fail += 1
            elif kind == "skip":
                self.skip += 1
            short = f"  {kind.upper():5} {(name or '')[:40]}"
            if detail:
                short += f" · {detail[:50]}"
            self.event(short)
            self.paint()

    def close(self) -> None:
        with self.lock:
            self.paint()
            sys.stdout.write("\n")
            sys.stdout.flush()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Параллельный скрап org-news с Lab LLM (компактный прогресс)"
    )
    p.add_argument("--sources", type=Path, default=base.DEFAULT_SOURCES)
    p.add_argument("--out-root", type=Path, default=base.DEFAULT_OUT_ROOT)
    p.add_argument("--date-from", default="2025-10-23")
    p.add_argument("--keep-undated", action="store_true")
    p.add_argument("--max-articles", type=int, default=120)
    p.add_argument("--max-hub-pages", type=int, default=12)
    p.add_argument("--workers", type=int, default=6, help="Параллельных сайтов (LLM+HTTP)")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--only", type=str, default="")
    p.add_argument(
        "--resume",
        action="store_true",
        help="Пропускать status=done с articles>0; empty/failed пересканируются",
    )
    p.add_argument(
        "--rediscover",
        action="store_true",
        help="Всегда заново discover профиля",
    )
    return p.parse_args()


def _should_skip(prev: dict[str, Any], *, resume: bool) -> bool:
    if not resume:
        return False
    if prev.get("status") != "done":
        return False
    return int(prev.get("articles") or 0) > 0


def main() -> int:
    args = parse_args()
    base.configure_paths(args.out_root.resolve())
    base.OUT_ROOT.mkdir(parents=True, exist_ok=True)
    base.SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    base.PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    if not args.sources.exists():
        print(f"Нет файла источников: {args.sources}", file=sys.stderr)
        return 1

    settings = Settings(API_KEY=API_KEY, BASE_URL=BASE_URL, LLM_MODEL=MODEL_NAME)
    # по клиенту на воркер — меньше блокировок на httpx
    def make_llm() -> LLMClient:
        return LLMClient(settings)

    probe = make_llm()
    if not probe.enabled:
        print("LLM не включён: проверьте API_KEY в скрипте", file=sys.stderr)
        return 1

    rows = base.load_source_rows(args.sources)
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

    total = len(rows)
    progress = base.load_json(base.PROGRESS_PATH, None)
    if not isinstance(progress, dict) or "sources" not in progress:
        progress = base.default_progress(args.date_from)
    progress["date_from"] = args.date_from
    progress.setdefault("sources", {})
    progress["llm"] = {"base_url": BASE_URL, "model": MODEL_NAME, "enabled": True}
    progress_lock = threading.Lock()
    ui = CompactProgress(total)
    workers = max(1, int(args.workers))

    print(
        f"Lab LLM · workers={workers} · sites={total} · out={base.OUT_ROOT}",
        flush=True,
    )
    print(f"model={MODEL_NAME}  base={BASE_URL}", flush=True)

    thread_local = threading.local()

    def llm_for_thread() -> LLMClient:
        client = getattr(thread_local, "llm", None)
        if client is None:
            client = make_llm()
            thread_local.llm = client
        return client

    def process(index: int, row: dict[str, Any]) -> None:
        sid = row["source_id"]
        name = row["name"]
        url = row["start_url"]
        with progress_lock:
            prev = progress["sources"].get(sid) or {}
        if _should_skip(prev, resume=args.resume):
            ui.finish(sid, kind="skip", name=name, detail=f"kept={prev.get('articles')}")
            return

        started = base.utc_now()
        with progress_lock:
            progress["sources"][sid] = {
                "name": name,
                "start_url": url,
                "status": "running",
                "started_at": started,
                "updated_at": started,
                "llm": True,
            }
            progress["updated_at"] = started
            base.atomic_write_json(base.PROGRESS_PATH, progress)

        ui.start(sid, name)
        try:
            result = base.scrape_one(
                row,
                max_articles=args.max_articles,
                max_hub_pages=args.max_hub_pages,
                date_from=args.date_from,
                keep_undated=args.keep_undated,
                use_llm=True,
                llm=llm_for_thread(),
                rediscover=args.rediscover,
            )
            kept = int(result["kept"])
            status = "done" if kept > 0 else "empty"
            with progress_lock:
                progress["sources"][sid] = {
                    "name": name,
                    "start_url": url,
                    "domain": result.get("domain"),
                    "list_url": result.get("list_url"),
                    "status": status,
                    "articles": kept,
                    "raw_fetched": result["raw_fetched"],
                    "date_stats": result["date_stats"],
                    "scrape_stats": result.get("scrape_stats"),
                    "started_at": started,
                    "updated_at": base.utc_now(),
                    "error": None if kept > 0 else "0 articles after scrape+browser retry",
                    "llm": True,
                }
                progress["updated_at"] = base.utc_now()
                base.atomic_write_json(base.PROGRESS_PATH, progress)
            ui.finish(
                sid,
                kind="ok" if kept > 0 else "empty",
                name=name,
                detail=f"raw={result['raw_fetched']} kept={kept}",
            )
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            with progress_lock:
                progress["sources"][sid] = {
                    "name": name,
                    "start_url": url,
                    "status": "failed",
                    "started_at": started,
                    "updated_at": base.utc_now(),
                    "error": err,
                    "llm": True,
                }
                progress["updated_at"] = base.utc_now()
                base.atomic_write_json(base.PROGRESS_PATH, progress)
            ui.finish(sid, kind="fail", name=name, detail=err[:60])

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {
                pool.submit(process, index, row): (index, row)
                for index, row in enumerate(rows, start=1)
            }
            pending = set(futs)
            while pending:
                done, pending = wait(pending, timeout=0.8, return_when=FIRST_COMPLETED)
                if not done:
                    ui.paint()
                    continue
                for fut in done:
                    try:
                        fut.result()
                    except Exception as exc:
                        _idx, row = futs[fut]
                        ui.finish(
                            row["source_id"],
                            kind="fail",
                            name=row["name"],
                            detail=str(exc)[:60],
                        )
    except KeyboardInterrupt:
        ui.close()
        print(
            f"Остановлено. Продолжить: python scripts/scrape_science_org_news_lab.py --resume",
            flush=True,
        )
        return 130

    ui.close()
    total_arts = base.rebuild_jsonl_from_sources()
    with progress_lock:
        base.atomic_write_json(
            base.MANIFEST_PATH,
            {
                "updated_at": base.utc_now(),
                "date_from": args.date_from,
                "sources_file": str(args.sources),
                "out_root": str(base.OUT_ROOT),
                "workers": workers,
                "llm": True,
                "lab": {"base_url": BASE_URL, "model": MODEL_NAME},
                "counts": {
                    "queued": total,
                    "ok": ui.ok,
                    "empty": ui.empty,
                    "failed": ui.fail,
                    "skipped": ui.skip,
                    "articles_jsonl": total_arts,
                },
            },
        )
    print(
        f"Готово · ok={ui.ok} empty={ui.empty} fail={ui.fail} skip={ui.skip} "
        f"· articles.jsonl={total_arts}",
        flush=True,
    )
    print(f"Прогресс: {base.PROGRESS_PATH}", flush=True)
    return 0 if ui.fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
