"""Перевод + кластеризация иностранных ИТ-новостей нефтегазовых компаний через Lab LLM.

1) Читает foreign_it_news/out_trade/it_focus.json (+ out_adapters при наличии)
2) Переводит title/text на русский (Lab, кэш)
3) TF-IDF+SVD → MiniBatchKMeans → русские имена кластеров/подкластеров (Lab)
4) Пишет отчёт и portal-совместимый JSON (как ИТ-поток)

  # связь
  python scripts/cluster_foreign_it_lab.py --ping

  # полный прогон (корпус: it_focus с реальными телами)
  python scripts/cluster_foreign_it_lab.py --force-translate

  # только отфильтрованный trade-press (без adapters)
  python scripts/cluster_foreign_it_lab.py --force-translate --input foreign_it_news/out_trade/it_focus.json

  # тест на срезе
  python scripts/cluster_foreign_it_lab.py --limit 40 --clusters 8

  # только перевод / только кластеризация по кэшу
  python scripts/cluster_foreign_it_lab.py --translate-only
  python scripts/cluster_foreign_it_lab.py --skip-translate --cached-embeddings

  # без LLM-имён кластеров (перевод всё равно нужен Lab, если нет кэша)
  python scripts/cluster_foreign_it_lab.py --skip-translate --heuristic-names

Корпус: foreign_it_news/out_trade/it_focus.json (после фильтра тел; backup: it_focus.pre_body_filter.json)

Выход:
  data/runs/foreign_it/articles_translated.jsonl
  data/runs/foreign_it/clusters_report.json
  data/runs/foreign_it/portal_data.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts._lab_credentials import lab_base_url, lab_api_key, lab_model, ensure_no_proxy
ensure_no_proxy()
# --- Lab LLM: явные креды ---
BASE_URL = lab_base_url()
API_KEY = lab_api_key()
MODEL_NAME = lab_model("gpt-oss-120b")
# -----------------------------


from gartner.config import Settings  # noqa: E402
from gartner.llm import LLMClient  # noqa: E402
from gartner.pipeline.foreign_it_cluster import (  # noqa: E402
    DEFAULT_INPUTS,
    DEFAULT_MAX_SUBCLUSTERS,
    DEFAULT_N_CLUSTERS,
    PORTAL_PATH,
    REPORT_PATH,
    TRANSLATED_JSONL,
    run_foreign_it_pipeline,
)


def make_settings(*, heuristic_names: bool) -> Settings:
    return Settings(
        API_KEY="" if heuristic_names else API_KEY,
        BASE_URL=BASE_URL,
        LLM_MODEL=MODEL_NAME,
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Lab: перевод + кластеры иностранных ИТ-новостей компаний"
    )
    p.add_argument(
        "--input",
        action="append",
        default=[],
        help="JSON с articles (можно несколько). По умолчанию it_focus + adapters",
    )
    p.add_argument("--limit", type=int, default=0, help="Срез статей (0 = все)")
    p.add_argument(
        "--clusters",
        type=int,
        default=DEFAULT_N_CLUSTERS,
        help=f"Число кластеров KMeans (по умолчанию {DEFAULT_N_CLUSTERS}; 0 = авто)",
    )
    p.add_argument(
        "--max-subclusters",
        type=int,
        default=DEFAULT_MAX_SUBCLUSTERS,
        help=f"Макс. подкластеров на кластер (по умолчанию {DEFAULT_MAX_SUBCLUSTERS})",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=5,
        help="Размер батча перевода (1 = по одной статье)",
    )
    p.add_argument("--force-translate", action="store_true", help="Игнор кэша перевода")
    p.add_argument(
        "--skip-translate",
        action="store_true",
        help="Взять уже готовый articles_translated.jsonl",
    )
    p.add_argument("--translate-only", action="store_true", help="Только перевод, без кластеров")
    p.add_argument("--cached-embeddings", action="store_true")
    p.add_argument("--api-embeddings", action="store_true")
    p.add_argument(
        "--heuristic-names",
        action="store_true",
        help="Имена кластеров без LLM (API_KEY пустой)",
    )
    p.add_argument("--ping", action="store_true", help="Проверка Lab и выход")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    lab_settings = make_settings(heuristic_names=False)
    lab = LLMClient(lab_settings)

    if args.ping:
        if not lab.enabled:
            print("Lab disabled: нет API_KEY", file=sys.stderr)
            return 1
        try:
            print("Lab OK:", lab.json_call('Верни {"ok": true}', {"x": 1}, max_retries=1))
            return 0
        except Exception as exc:
            print(f"Lab FAIL: {exc}", file=sys.stderr)
            return 1

    inputs = [Path(p) for p in args.input] if args.input else None
    if inputs:
        missing = [str(p) for p in inputs if not p.exists()]
        if missing:
            print(f"Нет файлов: {missing}", file=sys.stderr)
            return 1
    else:
        existing = [p for p in DEFAULT_INPUTS if p.exists()]
        if not existing:
            print(
                "Нет корпуса. Сначала scrape_trade_press / adapters.\n"
                f"Ожидалось: {DEFAULT_INPUTS[0]}",
                file=sys.stderr,
            )
            return 1

    name_settings = make_settings(heuristic_names=args.heuristic_names)
    name_llm = LLMClient(name_settings)
    n_clusters = int(args.clusters) if int(args.clusters) >= 2 else None
    print(
        json.dumps(
            {
                "mode": "translate_then_cluster",
                "inputs": [str(p) for p in (inputs or [p for p in DEFAULT_INPUTS if p.exists()])],
                "limit": args.limit or "all",
                "n_clusters": n_clusters or "auto",
                "batch_size": args.batch_size,
                "skip_translate": args.skip_translate,
                "translate_only": args.translate_only,
                "force_translate": args.force_translate,
                "heuristic_names": args.heuristic_names,
                "llm_model": MODEL_NAME,
                "base_url": BASE_URL,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    try:
        # heuristic-names: перевод через Lab, имена кластеров — эвристика
        if args.heuristic_names and not args.skip_translate and not args.translate_only:
            phase1 = run_foreign_it_pipeline(
                input_paths=inputs,
                force_translate=args.force_translate,
                skip_translate=False,
                translate_only=True,
                batch_size=args.batch_size,
                limit=args.limit,
                settings=lab_settings,
                llm=lab,
            )
            print(json.dumps({"phase": "translate", **phase1}, ensure_ascii=False), flush=True)
            result = run_foreign_it_pipeline(
                input_paths=inputs,
                skip_translate=True,
                force_embeddings=not args.cached_embeddings,
                local_embeddings=not args.api_embeddings,
                limit=args.limit,
                n_clusters=n_clusters,
                max_subclusters=args.max_subclusters,
                settings=name_settings,
                llm=name_llm,
            )
        else:
            # перевод всегда через Lab; heuristic-names влияет только на имена кластеров
            need_lab = (not args.skip_translate) or args.translate_only or not args.heuristic_names
            result = run_foreign_it_pipeline(
                input_paths=inputs,
                force_translate=args.force_translate,
                skip_translate=args.skip_translate,
                translate_only=args.translate_only,
                force_embeddings=not args.cached_embeddings,
                local_embeddings=not args.api_embeddings,
                batch_size=args.batch_size,
                limit=args.limit,
                n_clusters=n_clusters,
                max_subclusters=args.max_subclusters,
                settings=lab_settings if need_lab else name_settings,
                llm=lab if need_lab else name_llm,
            )
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "result": result,
                "translated": str(TRANSLATED_JSONL),
                "report": str(REPORT_PATH),
                "portal": str(PORTAL_PATH),
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
