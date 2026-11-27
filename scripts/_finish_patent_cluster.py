"""Добить enrich + subclusters + report по уже готовым patent clusters."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gartner.config import get_settings
from gartner.pipeline.patent_cluster import (
    build_patent_cluster_report,
    enrich_patent_clusters,
    run_patent_subclusters,
)

get_settings.cache_clear()


def main() -> int:
    print("enrich...", flush=True)
    print(json.dumps(enrich_patent_clusters(), ensure_ascii=False), flush=True)
    print("subclusters...", flush=True)
    print(json.dumps(run_patent_subclusters(), ensure_ascii=False), flush=True)
    print("report...", flush=True)
    report = build_patent_cluster_report()
    summary = {
        "n_clusters": report["n_clusters"],
        "n_subclusters": report["n_subclusters"],
        "noise": report["noise"],
        "patents_assigned": report["patents_assigned"],
        "top": [
            {
                "id": c["cluster_id"],
                "title": c["title"],
                "n": c["member_count"],
                "subs": [
                    {"title": s["title"], "n": s["member_count"]}
                    for s in (c.get("subclusters") or [])[:5]
                ],
            }
            for c in report["clusters"][:12]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
