import json, os, sys
from pathlib import Path
ROOT = Path(r"C:\Users\Муз\Desktop\ГАРТНЕР\Oil radar 4")
sys.path.insert(0, str(ROOT))
os.environ["FORCE_HEURISTIC"] = "1"
from gartner.config import get_settings
get_settings.cache_clear()
from gartner.db import connect, init_db
from gartner.pipeline.patent_cluster import run_patent_subclusters, build_patent_cluster_report

init_db()
print("llm_enabled", get_settings().llm_enabled, flush=True)
# dump samples for naming
rows = []
with connect() as conn:
    clusters = [dict(r) for r in conn.execute(
        "SELECT cluster_id, title, member_count FROM patent_clusters ORDER BY member_count DESC"
    ).fetchall()]
    for c in clusters:
        titles = [r[0] for r in conn.execute(
            """
            SELECT p.title FROM patent_cluster_members m
            JOIN patents p ON p.patent_id=m.patent_id
            WHERE m.cluster_id=? AND m.is_noise=0
            LIMIT 12
            """,
            (c["cluster_id"],),
        ).fetchall()]
        rows.append({"cluster_id": c["cluster_id"], "n": c["member_count"], "titles": titles})
Path("data/runs/patents/_cluster_samples_for_naming.json").write_text(
    json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("samples", len(rows), flush=True)
print("sub...", flush=True)
print(json.dumps(run_patent_subclusters(), ensure_ascii=False), flush=True)
r = build_patent_cluster_report()
print("report", r["n_clusters"], r["n_subclusters"], r["noise"], flush=True)
