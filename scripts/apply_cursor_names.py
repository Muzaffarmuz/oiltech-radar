"""Применить имена кластеров из Cursor LLM (_cluster_names_cursor.json)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gartner.db import connect, init_db, utc_now
from gartner.pipeline.patent_cluster import build_patent_cluster_report

NAMES = ROOT / "data" / "runs" / "patents" / "_cluster_names_cursor.json"


def main() -> int:
    names = json.loads(NAMES.read_text(encoding="utf-8"))
    by_id = {x["cluster_id"]: x for x in names if isinstance(x, dict) and x.get("cluster_id")}
    init_db()
    now = utc_now()
    updated = 0
    with connect() as conn:
        for cid, meta in by_id.items():
            title = (meta.get("title") or "").strip()
            desc = (meta.get("description") or "").strip()
            if not title:
                continue
            cur = conn.execute(
                "UPDATE patent_clusters SET title=?, description=?, updated_at=? WHERE cluster_id=?",
                (title, desc, now, cid),
            )
            updated += cur.rowcount
    report = build_patent_cluster_report()
    print(
        json.dumps(
            {
                "named_file": len(by_id),
                "updated": updated,
                "n_clusters": report["n_clusters"],
                "n_subclusters": report["n_subclusters"],
                "noise": report["noise"],
                "top": [
                    {"id": c["cluster_id"], "title": c["title"], "n": c["member_count"]}
                    for c in report["clusters"][:15]
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
