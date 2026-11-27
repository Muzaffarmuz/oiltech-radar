"""Оркестратор пайплайна OilTech Radar 3.0."""

from __future__ import annotations

import argparse
import json
import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from gartner.config import RUNS_DIR, ensure_dirs, get_settings
from gartner.db import get_state, init_db, set_state, utc_now
from gartner.llm import LLMClient
from gartner.pipeline.build_portal import build_portal_payload
from gartner.pipeline.cluster import assign_new_events, run_full_cluster
from gartner.pipeline.embeddings import ensure_embeddings
from gartner.pipeline.enrich import enrich_clusters
from gartner.pipeline.extract import extract_new_articles
from gartner.pipeline.forecast import forecast_clusters
from gartner.pipeline.merge import merge_and_upsert
from gartner.pipeline.qa import build_qa_report
from gartner.pipeline.scrape import run_scrapers
from gartner.pipeline.snapshot import create_snapshot
from gartner.pipeline.subcluster import run_subclusters
from gartner.pipeline.tag_flows import run_tag_flows_stage

_lock = threading.Lock()
_status: dict[str, Any] = {
    "state": "idle",
    "stage": "",
    "started_at": None,
    "finished_at": None,
    "error": None,
    "manifest": None,
}


def get_pipeline_status() -> dict[str, Any]:
    return dict(_status)


@dataclass
class PipelineOptions:
    scrape: bool = True
    backfill: bool = False
    include_seed: bool = False
    seed_only: bool = False
    full_recluster: bool = False
    limit_extract: int | None = None


def _stage(name: str) -> None:
    _status["stage"] = name
    set_state("pipeline_stage", name)


def run_pipeline(options: PipelineOptions | None = None) -> dict[str, Any]:
    """Полный/инкрементальный прогон. Потокобезопасен (одна задача за раз)."""
    opts = options or PipelineOptions()
    if not _lock.acquire(blocking=False):
        return {"ok": False, "error": "Пайплайн уже выполняется", "status": get_pipeline_status()}

    ensure_dirs()
    init_db()
    # портал может жить долго: подхватываем свежий .env перед каждым прогоном
    get_settings.cache_clear()
    settings = get_settings()
    started = utc_now()
    _status.update(
        {
            "state": "running",
            "stage": "init",
            "started_at": started,
            "finished_at": None,
            "error": None,
            "manifest": None,
        }
    )
    set_state("pipeline_state", "running")
    manifest: dict[str, Any] = {
        "started_at": started,
        "options": opts.__dict__,
        "llm_enabled": settings.llm_enabled,
        "steps": {},
    }

    try:
        llm = LLMClient(settings)

        if opts.seed_only:
            _stage("merge_seed")
            manifest["steps"]["merge"] = merge_and_upsert(include_seed=True)
        else:
            if opts.scrape:
                _stage("scrape")
                scrape_report = run_scrapers(settings=settings, backfill=opts.backfill)
                manifest["steps"]["scrape"] = {
                    "ok_sources": scrape_report.ok_sources,
                    "failed": [r.__dict__ for r in scrape_report.failed],
                    "results": [r.__dict__ for r in scrape_report.results],
                }
            _stage("merge")
            manifest["steps"]["merge"] = merge_and_upsert(include_seed=opts.include_seed)

        _stage("tag_flows")
        # Экспериментальные метки → articles; LLM-разметку новых даёт scripts/tag_flow_articles.py
        manifest["steps"]["tag_flows"] = run_tag_flows_stage(import_sidecars=True)

        _stage("extract")
        manifest["steps"]["extract"] = extract_new_articles(llm=llm, limit=opts.limit_extract)

        _stage("embeddings")
        emb_step = ensure_embeddings(llm=llm, settings=settings)
        manifest["steps"]["embeddings"] = emb_step

        _stage("cluster")
        force_recluster = bool(opts.full_recluster or get_state("has_clusters") != "1")
        # полный recluster если эмбеддинги только что пересобраны (смена dim/модели)
        if emb_step.get("rebuilt") or (emb_step.get("new", 0) and emb_step.get("dim", 0) >= 256 and emb_step.get("new") == emb_step.get("total")):
            force_recluster = True
        if force_recluster:
            manifest["steps"]["cluster"] = run_full_cluster(settings)
        else:
            manifest["steps"]["cluster"] = assign_new_events(settings)
        set_state("has_clusters", "1")

        _stage("enrich")
        manifest["steps"]["enrich"] = enrich_clusters(llm=llm)

        _stage("subcluster")
        # полный split после recluster; после инкрементального assign — тоже пересобираем,
        # чтобы новые точки попали в пересчёт (дёшево на нашем объёме)
        manifest["steps"]["subcluster"] = run_subclusters(llm=llm, settings=settings)

        _stage("forecast")
        manifest["steps"]["forecast"] = forecast_clusters(llm=llm)

        _stage("snapshot")
        manifest["steps"]["snapshot"] = create_snapshot(manifest=manifest)

        _stage("qa")
        qa = build_qa_report()
        manifest["steps"]["qa"] = {
            "noise_ratio": qa.get("noise_ratio"),
            "n_clusters": qa.get("n_clusters"),
            "notes": qa.get("notes"),
        }

        _stage("portal")
        portal = build_portal_payload()
        manifest["steps"]["portal"] = {"topics": portal["kpis"]["topics"], "events": portal["kpis"]["events"]}

        finished = utc_now()
        manifest["finished_at"] = finished
        manifest["ok"] = True
        _write_manifest(manifest)
        _status.update({"state": "idle", "stage": "done", "finished_at": finished, "manifest": manifest, "error": None})
        set_state("pipeline_state", "idle")
        set_state("last_success_at", finished)
        return manifest
    except Exception as exc:  # noqa: BLE001
        finished = utc_now()
        manifest["finished_at"] = finished
        manifest["ok"] = False
        manifest["error"] = str(exc)
        manifest["traceback"] = traceback.format_exc()
        _write_manifest(manifest)
        _status.update(
            {
                "state": "error",
                "stage": _status.get("stage") or "error",
                "finished_at": finished,
                "manifest": manifest,
                "error": str(exc),
            }
        )
        set_state("pipeline_state", "error")
        return manifest
    finally:
        _lock.release()


def _write_manifest(manifest: dict[str, Any]) -> None:
    ensure_dirs()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RUNS_DIR / f"run_{stamp}.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUNS_DIR / "last_run.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OilTech Radar 3.0 pipeline")
    parser.add_argument("--seed-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--include-seed", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-scrape", action="store_true", help="Не запускать парсеры (только уже скачанный raw)")
    parser.add_argument("--backfill", action="store_true", help="Полный backfill (месяцы из BACKFILL_MONTHS)")
    parser.add_argument("--recluster", action="store_true", help="Принудительный полный recluster")
    parser.add_argument("--limit-extract", type=int, default=None)
    parser.add_argument("--reset", action="store_true", help="Очистить БД перед прогоном")
    args = parser.parse_args(argv)

    if args.seed_only or args.include_seed:
        print(
            "Отказ: seed/демо-тексты отключены. Используйте scrape реальных сайтов "
            "(python -m gartner.pipeline.run --backfill --recluster).",
            flush=True,
        )
        return 2

    if args.reset:
        from gartner.pipeline.reset import reset_all

        reset_all(keep_raw=args.no_scrape)

    result = run_pipeline(
        PipelineOptions(
            scrape=not args.no_scrape,
            backfill=args.backfill,
            include_seed=False,
            seed_only=False,
            full_recluster=args.recluster,
            limit_extract=args.limit_extract,
        )
    )
    print(json.dumps({k: result.get(k) for k in ("ok", "started_at", "finished_at", "steps", "error")}, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
