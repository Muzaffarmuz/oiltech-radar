"""Выгрузка сэмплов кластеров/подкластеров для нейминга внешней LLM (Cursor)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gartner.db import connect, init_db

OUT = ROOT / "data" / "runs" / "patents" / "_cluster_samples_for_naming.json"
OUT_SUB = ROOT / "data" / "runs" / "patents" / "_subcluster_samples_for_naming.json"


def main() -> int:
    init_db()
    clusters: list[dict] = []
    subs: list[dict] = []
    with connect() as conn:
        for crow in conn.execute(
            "SELECT cluster_id, title, member_count FROM patent_clusters ORDER BY member_count DESC"
        ):
            cid = crow["cluster_id"]
            rows = conn.execute(
                """
                SELECT p.title, p.abstract, p.ipc
                FROM patent_cluster_members m
                JOIN patents p ON p.patent_id=m.patent_id
                WHERE m.cluster_id=? AND m.is_noise=0
                ORDER BY m.probability DESC
                LIMIT 14
                """,
                (cid,),
            ).fetchall()
            clusters.append(
                {
                    "cluster_id": cid,
                    "n": int(crow["member_count"] or 0),
                    "current_title": crow["title"],
                    "titles": [r["title"] or "" for r in rows],
                    "abstracts": [(r["abstract"] or "")[:220] for r in rows[:8]],
                    "ipc": [r["ipc"] or "" for r in rows[:8]],
                }
            )
        try:
            for srow in conn.execute(
                """
                SELECT subcluster_id, parent_cluster_id, title, member_count
                FROM patent_subclusters
                ORDER BY member_count DESC
                """
            ):
                sid = srow["subcluster_id"]
                rows = conn.execute(
                    """
                    SELECT p.title, p.abstract
                    FROM patent_subcluster_members m
                    JOIN patents p ON p.patent_id=m.patent_id
                    WHERE m.subcluster_id=?
                    LIMIT 10
                    """,
                    (sid,),
                ).fetchall()
                subs.append(
                    {
                        "subcluster_id": sid,
                        "parent_cluster_id": srow["parent_cluster_id"],
                        "n": int(srow["member_count"] or 0),
                        "current_title": srow["title"],
                        "titles": [r["title"] or "" for r in rows],
                    }
                )
        except Exception:
            pass

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(clusters, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_SUB.write_text(json.dumps(subs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"clusters={len(clusters)} -> {OUT}")
    print(f"subclusters={len(subs)} -> {OUT_SUB}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
