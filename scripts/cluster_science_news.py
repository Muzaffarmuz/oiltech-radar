"""Полная перекластеризация новостей science_org_news через Lab LLM.

С нуля (эмбеддинги + KMeans + LLM-имена), только нефтегаз/бурение:

  python scripts/cluster_science_news.py
  python scripts/cluster_science_news.py --oilgas-min-hits 2
  python scripts/cluster_science_news.py --clusters 20
  python scripts/cluster_science_news.py --heuristic-names
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
MODEL_NAME = "qwen3-32b"
# -----------------------------


from gartner.config import Settings  # noqa: E402
from gartner.llm import LLMClient  # noqa: E402
from gartner.pipeline.science_news_cluster import (  # noqa: E402
    ARTICLES_JSONL,
    run_science_news_cluster_pipeline,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Перекластеризация science_org_news с фильтром нефтегаза"
    )
    parser.add_argument(
        "--cached-embeddings",
        action="store_true",
        help="Не пересчитывать эмбеддинги (взять кэш)",
    )
    parser.add_argument(
        "--api-embeddings",
        action="store_true",
        help="Эмбеддинги через API вместо локального TF-IDF+SVD",
    )
    parser.add_argument(
        "--heuristic-names",
        action="store_true",
        help="Без LLM: только эвристические имена",
    )
    parser.add_argument(
        "--oilgas-min-hits",
        type=int,
        default=1,
        help="Мин. число нефтегаз-ключей в title+text (0 = без фильтра темы)",
    )
    parser.add_argument(
        "--clusters",
        type=int,
        default=0,
        help="Число кластеров KMeans (0 = авто: ~1 на 35 статей, max 28)",
    )
    args = parser.parse_args()

    if not ARTICLES_JSONL.exists():
        print(f"Нет корпуса: {ARTICLES_JSONL}", file=sys.stderr)
        return 1

    settings = Settings(
        API_KEY = lab_api_key() if args.heuristic_names else API_KEY,
        BASE_URL=BASE_URL,
        LLM_MODEL=MODEL_NAME,
    )
    llm = LLMClient(settings)
    force_embeddings = not args.cached_embeddings
    n_clusters = int(args.clusters) if int(args.clusters) >= 2 else None
    print(
        json.dumps(
            {
                "mode": "full_recluster",
                "corpus": str(ARTICLES_JSONL),
                "force_embeddings": force_embeddings,
                "oilgas_min_hits": int(args.oilgas_min_hits),
                "n_clusters": n_clusters or "auto(min(28, n//35))",
                "llm_enabled": llm.enabled,
                "base_url": settings.base_url,
                "model": settings.llm_model,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    result = run_science_news_cluster_pipeline(
        force_embeddings=force_embeddings,
        local_embeddings=not args.api_embeddings,
        settings=settings,
        llm=llm,
        oilgas_min_hits=int(args.oilgas_min_hits),
        n_clusters=n_clusters,
    )
    cluster = result.get("cluster") or {}
    summary = {
        "embeddings": result.get("embeddings"),
        "status": cluster.get("status"),
        "method": cluster.get("method"),
        "n_articles": cluster.get("n_articles"),
        "n_clusters": cluster.get("n_clusters"),
        "n_subclusters": cluster.get("n_subclusters"),
        "noise": cluster.get("noise"),
        "report": cluster.get("report"),
        "llm": {
            "enabled": llm.enabled,
            "base_url": settings.base_url,
            "model": settings.llm_model,
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if cluster.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
