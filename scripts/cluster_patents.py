"""Кластеризация патентов: embed → HDBSCAN/KMeans → имена → подкластеры.

  # как раньше (LLM из .env)
  python scripts/cluster_patents.py --local-embeddings

  # Lab LLM (qwen3-32b) для имён кластеров и подкластеров
  python scripts/cluster_patents.py --lab --local-embeddings --force-relabel

  # только переименовать уже готовые кластеры через Lab (без пересчёта групп)
  python scripts/cluster_patents.py --lab --names-only --force-relabel
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
# --- Lab LLM: явные креды (включаются флагом --lab) ---
LAB_BASE_URL = lab_base_url()
LAB_API_KEY = lab_api_key()
LAB_MODEL_NAME = "qwen3-32b"
# -----------------------------------------------------


def _setup_lab_no_proxy() -> None:
    _no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    parts = {p.strip() for p in _no_proxy.split(",") if p.strip()}
    parts.update({"d.dgx", "localhost", "127.0.0.1"})
    os.environ["NO_PROXY"] = ",".join(sorted(parts))
    os.environ["no_proxy"] = os.environ["NO_PROXY"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Кластеризация патентов (UMAP+HDBSCAN)")
    parser.add_argument("--force-embeddings", action="store_true", help="Пересчитать все эмбеддинги")
    parser.add_argument(
        "--local-embeddings",
        action="store_true",
        help="TF-IDF+SVD без API-эмбеддингов",
    )
    parser.add_argument("--skip-enrich", action="store_true", help="Без LLM-имён кластеров")
    parser.add_argument(
        "--lab",
        action="store_true",
        help="Имена кластеров/подкластеров через Lab LLM (qwen3-32b на d.dgx)",
    )
    parser.add_argument(
        "--force-relabel",
        action="store_true",
        help="Перезаписать уже существующие названия кластеров",
    )
    parser.add_argument(
        "--names-only",
        action="store_true",
        help="Не пересчитывать группировку: только enrich + подкластеры",
    )
    args = parser.parse_args()

    from gartner.config import Settings, get_settings
    from gartner.llm import LLMClient
    from gartner.pipeline.patent_cluster import run_patent_cluster_pipeline

    settings = get_settings()
    llm: LLMClient | None = None
    if args.lab:
        _setup_lab_no_proxy()
        settings = Settings(
            API_KEY=LAB_API_KEY,
            BASE_URL=LAB_BASE_URL,
            LLM_MODEL=LAB_MODEL_NAME,
            EMBEDDING_MODEL=settings.embedding_model,
        )
        llm = LLMClient(settings)
        print(
            json.dumps(
                {
                    "llm": "lab",
                    "enabled": llm.enabled,
                    "base_url": LAB_BASE_URL,
                    "model": LAB_MODEL_NAME,
                    "force_relabel": bool(args.force_relabel),
                    "names_only": bool(args.names_only),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if not llm.enabled:
            print("Lab LLM не включён — проверьте креды в скрипте", file=sys.stderr)
            return 1

    result = run_patent_cluster_pipeline(
        force_embeddings=args.force_embeddings,
        skip_enrich=args.skip_enrich,
        local_embeddings=args.local_embeddings or args.lab,
        llm=llm,
        settings=settings if args.lab else None,
        force_relabel=bool(args.force_relabel),
        skip_cluster=bool(args.names_only),
    )
    summary = {
        "embeddings": result.get("embeddings"),
        "cluster": result.get("cluster"),
        "enrich": result.get("enrich"),
        "subcluster": result.get("subcluster"),
        "report_n_clusters": (result.get("report") or {}).get("n_clusters"),
        "report_n_subclusters": (result.get("report") or {}).get("n_subclusters"),
        "report_noise": (result.get("report") or {}).get("noise"),
        "lab": bool(args.lab),
        "top_clusters": [
            {
                "id": c["cluster_id"],
                "title": c["title"],
                "n": c["member_count"],
                "subs": len(c.get("subclusters") or []),
            }
            for c in ((result.get("report") or {}).get("clusters") or [])[:12]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
