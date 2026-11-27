"""Настоящая кластеризация потоков policy / investments через Lab LLM.

Эмбеддинги (локальный TF-IDF+SVD) → MiniBatchKMeans → имена кластеров/подкластеров Lab.

По умолчанию: 20 кластеров, до 5 подкластеров на каждый.

  # связь
  python scripts/cluster_flow_news_lab.py --ping

  # политика / инвестиции (дефолт k=20, max-sub=5)
  python scripts/cluster_flow_news_lab.py --flow policy
  python scripts/cluster_flow_news_lab.py --flow investments
  python scripts/cluster_flow_news_lab.py --flow both

  # свои параметры первичной кластеризации
  python scripts/cluster_flow_news_lab.py --flow policy --clusters 20 --max-subclusters 5
  python scripts/cluster_flow_news_lab.py --flow policy --clusters 30 --max-subclusters 3

  # авто-k по размеру корпуса (старое поведение)
  python scripts/cluster_flow_news_lab.py --flow policy --auto-clusters

  # тест на срезе
  python scripts/cluster_flow_news_lab.py --flow policy --limit 400 --clusters 12 --max-subclusters 3

  # со стрижкой малоинформативных (рекомендуется для policy)
  python scripts/cluster_flow_news_lab.py --flow policy --relevant-only --interfax-per-day 2

  # после Lab oilgas-стрижки (keep-ids из filter_flow_oilgas_lab.py)
  python scripts/cluster_flow_news_lab.py --flow policy --relevant-only --interfax-per-day 2 --keep-ids data/runs/flow_tags/policy_oilgas_lab_keep.json

  # кэш эмбеддингов
  python scripts/cluster_flow_news_lab.py --flow policy --cached-embeddings

Отчёты:
  data/runs/flow_tags/policy_clusters_report.json
  data/runs/flow_tags/investments_clusters_report.json
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
BASE_URL = lab_base_url()
API_KEY = lab_api_key()
MODEL_NAME = "qwen3-32b"


from gartner.config import Settings  # noqa: E402
from gartner.llm import LLMClient  # noqa: E402
from gartner.pipeline.flow_news_cluster import (  # noqa: E402
    ALLOWED_FLOWS,
    DEFAULT_MAX_SUBCLUSTERS,
    DEFAULT_N_CLUSTERS,
    MIN_YEAR_DEFAULT,
    load_keep_ids,
    oilgas_lab_keep_path,
    run_flow_news_cluster_pipeline,
)


def make_settings(*, heuristic_names: bool) -> Settings:
    return Settings(
        API_KEY = lab_api_key() if heuristic_names else API_KEY,
        BASE_URL=BASE_URL,
        LLM_MODEL=MODEL_NAME,
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Lab LLM: кластеры policy/investments")
    p.add_argument("--flow", choices=[*ALLOWED_FLOWS, "both"], default="both")
    p.add_argument("--year-from", type=int, default=MIN_YEAR_DEFAULT)
    p.add_argument("--limit", type=int, default=0, help="Срез статей (0 = все с year-from)")
    p.add_argument(
        "--clusters",
        type=int,
        default=DEFAULT_N_CLUSTERS,
        help=f"Число кластеров KMeans (по умолчанию {DEFAULT_N_CLUSTERS})",
    )
    p.add_argument(
        "--max-subclusters",
        type=int,
        default=DEFAULT_MAX_SUBCLUSTERS,
        help=f"Макс. подкластеров на кластер (по умолчанию {DEFAULT_MAX_SUBCLUSTERS})",
    )
    p.add_argument(
        "--auto-clusters",
        action="store_true",
        help="Игнорировать --clusters: k ≈ n/40 в диапазоне 6…24",
    )
    p.add_argument(
        "--relevant-only",
        action="store_true",
        help="Policy: только ТЭК/рынок/регулятор (без дронов/аэропортов и слабого Interfax)",
    )
    p.add_argument(
        "--interfax-per-day",
        type=int,
        default=0,
        help="Лимит Interfax новостей в день (0 = без лимита; для policy обычно 1–2)",
    )
    p.add_argument(
        "--no-dedupe-titles",
        action="store_true",
        help="Не удалять дубликаты заголовков",
    )
    p.add_argument("--cached-embeddings", action="store_true")
    p.add_argument("--api-embeddings", action="store_true", help="Эмбеддинги через API Lab")
    p.add_argument("--heuristic-names", action="store_true", help="Без LLM имён")
    p.add_argument(
        "--keep-ids",
        type=Path,
        default=None,
        help="JSON со списком article_id после filter_flow_oilgas_lab.py "
        "(по умолчанию data/runs/flow_tags/{flow}_oilgas_lab_keep.json если файл есть — не авто)",
    )
    p.add_argument(
        "--use-oilgas-lab-keep",
        action="store_true",
        help="Взять keep-ids из data/runs/flow_tags/{flow}_oilgas_lab_keep.json",
    )
    p.add_argument("--ping", action="store_true")
    p.add_argument(
        "--workers-note",
        action="store_true",
        help="Показать подсказку: именование кластеров последовательное (не ThreadPool)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    settings = make_settings(heuristic_names=args.heuristic_names)
    client = LLMClient(settings)

    if args.workers_note:
        print(
            "Имена кластеров Lab зовутся последовательно (1 запрос на кластер/подкластер). "
            "Параллельных --workers нет: узкое место — LLM, не CPU. "
            "Ускорение: --limit / меньше --clusters / --heuristic-names для теста."
        )
        return 0

    if args.ping:
        if not client.enabled:
            print("LLM disabled", file=sys.stderr)
            return 2
        try:
            print("Lab OK:", client.json_call('Верни {"ok": true}', {"x": 1}, max_retries=1))
            return 0
        except Exception as exc:
            print("Lab FAIL:", type(exc).__name__, exc, file=sys.stderr)
            return 1

    flows = list(ALLOWED_FLOWS) if args.flow == "both" else [args.flow]
    n_clusters = int(args.clusters) if int(args.clusters) >= 2 else DEFAULT_N_CLUSTERS
    max_sub = int(args.max_subclusters) if int(args.max_subclusters) >= 2 else DEFAULT_MAX_SUBCLUSTERS
    results = []
    for flow in flows:
        keep_path = args.keep_ids
        if keep_path is None and args.use_oilgas_lab_keep:
            keep_path = oilgas_lab_keep_path(flow)
        keep_ids = load_keep_ids(keep_path) if keep_path else None
        print(
            json.dumps(
                {
                    "flow": flow,
                    "year_from": args.year_from,
                    "limit": args.limit or "all",
                    "n_clusters": "auto" if args.auto_clusters else n_clusters,
                    "max_subclusters": max_sub,
                    "relevant_only": bool(args.relevant_only),
                    "interfax_per_day": int(args.interfax_per_day),
                    "dedupe_titles": not args.no_dedupe_titles,
                    "keep_ids": str(keep_path) if keep_path else None,
                    "keep_ids_n": len(keep_ids) if keep_ids is not None else None,
                    "force_embeddings": not args.cached_embeddings,
                    "llm_enabled": client.enabled,
                    "model": settings.llm_model,
                    "base_url": settings.base_url,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        result = run_flow_news_cluster_pipeline(
            flow,
            force_embeddings=not args.cached_embeddings,
            local_embeddings=not args.api_embeddings,
            settings=settings,
            llm=client,
            year_from=int(args.year_from),
            limit=int(args.limit or 0),
            n_clusters=None if args.auto_clusters else n_clusters,
            max_subclusters=max_sub,
            auto_clusters=bool(args.auto_clusters),
            relevant_only=bool(args.relevant_only),
            interfax_per_day=int(args.interfax_per_day),
            dedupe_titles=not args.no_dedupe_titles,
            keep_ids=keep_ids,
        )
        cluster = result.get("cluster") or {}
        summary = {
            "flow": flow,
            "embeddings": result.get("embeddings"),
            "status": cluster.get("status"),
            "method": cluster.get("method"),
            "n_articles": cluster.get("n_articles"),
            "n_clusters": cluster.get("n_clusters"),
            "n_subclusters": cluster.get("n_subclusters"),
            "report": cluster.get("report"),
        }
        results.append(summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)

    ok = all((r.get("status") == "ok") for r in results)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
