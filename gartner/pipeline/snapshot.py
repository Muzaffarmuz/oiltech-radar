"""Снимки и diff «что изменилось за неделю»."""

from __future__ import annotations

import json
from typing import Any

from gartner.db import connect, init_db, utc_now


def _current_payload() -> dict[str, Any]:
    with connect() as conn:
        clusters = [dict(r) for r in conn.execute("SELECT cluster_id, title, stage FROM clusters").fetchall()]
        events = [
            dict(r)
            for r in conn.execute(
                "SELECT event_id, topic_label, company_normalized, cluster_id FROM events e "
                "LEFT JOIN cluster_members m USING(event_id)"
            ).fetchall()
        ]
        counts = {
            c["cluster_id"]: conn.execute(
                "SELECT COUNT(*) AS n FROM cluster_members WHERE cluster_id=? AND is_noise=0",
                (c["cluster_id"],),
            ).fetchone()["n"]
            for c in clusters
        }
    return {
        "clusters": {c["cluster_id"]: {"title": c["title"], "stage": c["stage"], "count": counts.get(c["cluster_id"], 0)} for c in clusters},
        "event_ids": sorted(e["event_id"] for e in events),
        "events_by_cluster": {
            cid: [e["event_id"] for e in events if e.get("cluster_id") == cid]
            for cid in {c["cluster_id"] for c in clusters}
        },
    }


def _diff(prev: dict[str, Any] | None, curr: dict[str, Any]) -> dict[str, Any]:
    if not prev:
        return {
            "new_events": len(curr.get("event_ids", [])),
            "new_clusters": list(curr.get("clusters", {}).keys()),
            "growing": [],
            "lines": ["Первый снимок: история ещё не накоплена."],
        }
    prev_events = set(prev.get("event_ids", []))
    curr_events = set(curr.get("event_ids", []))
    new_events = sorted(curr_events - prev_events)
    prev_clusters = prev.get("clusters", {})
    curr_clusters = curr.get("clusters", {})
    new_cluster_ids = [cid for cid in curr_clusters if cid not in prev_clusters]
    growing = []
    for cid, meta in curr_clusters.items():
        old = prev_clusters.get(cid, {}).get("count", 0)
        delta = meta.get("count", 0) - old
        if delta > 0:
            growing.append({"cluster_id": cid, "title": meta.get("title"), "delta": delta})
    growing.sort(key=lambda x: x["delta"], reverse=True)

    lines: list[str] = []
    if new_events:
        lines.append(f"Появилось {len(new_events)} новых технологических упоминаний.")
    for g in growing[:5]:
        lines.append(f"+{g['delta']} к теме «{g['title']}».")
    for cid in new_cluster_ids[:3]:
        lines.append(f"Новая тема на карте: «{curr_clusters[cid].get('title')}».")
    if not lines:
        lines.append("Существенных изменений с прошлого снимка нет.")
    return {
        "new_events": len(new_events),
        "new_clusters": new_cluster_ids,
        "growing": growing[:10],
        "lines": lines,
    }


def create_snapshot(manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    init_db()
    curr = _current_payload()
    with connect() as conn:
        prev_row = conn.execute(
            "SELECT payload_json FROM snapshots ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    prev = json.loads(prev_row["payload_json"]) if prev_row else None
    diff = _diff(prev, curr)
    now = utc_now()
    snapshot_id = now.replace(":", "").replace("-", "")[:15]
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots(snapshot_id, created_at, payload_json, diff_json, manifest_json)
            VALUES(?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                now,
                json.dumps(curr, ensure_ascii=False),
                json.dumps(diff, ensure_ascii=False),
                json.dumps(manifest or {}, ensure_ascii=False),
            ),
        )
    return {"snapshot_id": snapshot_id, "diff": diff}
