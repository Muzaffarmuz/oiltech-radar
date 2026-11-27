import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["FORCE_HEURISTIC"] = "1"
from gartner.config import get_settings
get_settings.cache_clear()
from gartner.pipeline.patent_cluster import enrich_patent_clusters, run_patent_subclusters, build_patent_cluster_report
print("settings llm_enabled", get_settings().llm_enabled, flush=True)
print("enrich", enrich_patent_clusters(), flush=True)
print("sub", json.dumps(run_patent_subclusters(), ensure_ascii=False), flush=True)
r = build_patent_cluster_report()
print(json.dumps({
    "n_clusters": r["n_clusters"],
    "n_subclusters": r["n_subclusters"],
    "noise": r["noise"],
    "top": [{"id": c["cluster_id"], "title": c["title"], "n": c["member_count"], "subs": len(c["subclusters"])} for c in r["clusters"][:15]],
}, ensure_ascii=False, indent=2), flush=True)
