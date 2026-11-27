import json
from pathlib import Path
from gartner.db import connect, init_db, utc_now
from gartner.pipeline.patent_cluster import build_patent_cluster_report

names_path = Path("data/runs/patents/_cluster_names_gemini.json")
samples_path = Path("data/runs/patents/_cluster_samples_for_naming.json")
names = json.loads(names_path.read_text(encoding="utf-8"))
samples = json.loads(samples_path.read_text(encoding="utf-8"))
by_id = {x["cluster_id"]: x for x in names if isinstance(x, dict) and x.get("cluster_id")}
print("named", len(by_id), "samples", len(samples))
missing = [s["cluster_id"] for s in samples if s["cluster_id"] not in by_id]
print("missing", missing)

init_db()
now = utc_now()
updated = 0
with connect() as conn:
    for cid, meta in by_id.items():
        title = (meta.get("title") or "").strip()
        desc = (meta.get("description") or "").strip()
        if not title:
            continue
        conn.execute(
            "UPDATE patent_clusters SET title=?, description=?, updated_at=? WHERE cluster_id=?",
            (title, desc, now, cid),
        )
        updated += 1
print("updated", updated)
r = build_patent_cluster_report()
print(json.dumps({
    "n_clusters": r["n_clusters"],
    "n_subclusters": r["n_subclusters"],
    "noise": r["noise"],
    "patents_assigned": r["patents_assigned"],
    "top": [
        {"id": c["cluster_id"], "title": c["title"], "n": c["member_count"], "subs": len(c["subclusters"])}
        for c in r["clusters"][:12]
    ],
}, ensure_ascii=False, indent=2))
print("report -> data/runs/patents/patent_clusters_report.json")
