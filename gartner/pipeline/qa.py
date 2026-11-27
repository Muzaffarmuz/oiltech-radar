"""Автоматический QA-отчёт по кластерам."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from gartner.config import RUNS_DIR, ensure_dirs
from gartner.db import connect, init_db, utc_now


def build_qa_report() -> dict[str, Any]:
    init_db()
    ensure_dirs()
    with connect() as conn:
        total_events = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
        noise = conn.execute("SELECT COUNT(*) AS n FROM cluster_members WHERE is_noise=1").fetchone()["n"]
        clusters = [dict(r) for r in conn.execute("SELECT * FROM clusters").fetchall()]
        broken_links = conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE link IS NULL OR link='' OR link LIKE '%example.com/%'"
        ).fetchone()["n"]

    cluster_rows = []
    for c in clusters:
        with connect() as conn:
            members = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT e.event_id, e.topic_label, e.company_normalized, e.category, e.link
                    FROM cluster_members m JOIN events e ON e.event_id=m.event_id
                    WHERE m.cluster_id=? AND m.is_noise=0
                    """,
                    (c["cluster_id"],),
                ).fetchall()
            ]
        sample = random.sample(members, k=min(5, len(members))) if members else []
        categories = {m.get("category") for m in members if m.get("category")}
        cluster_rows.append(
            {
                "cluster_id": c["cluster_id"],
                "title": c["title"],
                "size": len(members),
                "stage": c.get("stage"),
                "mixed_segments": len(categories) > 2,
                "sample": sample,
            }
        )

    report = {
        "generated_at": utc_now(),
        "total_events": total_events,
        "noise": noise,
        "noise_ratio": round(noise / total_events, 4) if total_events else 0.0,
        "n_clusters": len(clusters),
        "suspicious_links": broken_links,
        "clusters": cluster_rows,
        "notes": [],
    }
    if report["noise_ratio"] > 0.3:
        report["notes"].append("Высокая доля unassigned/noise — рассмотрите полный recluster.")
    if broken_links:
        report["notes"].append(f"Подозрительные/пустые ссылки: {broken_links}.")

    out = RUNS_DIR / "qa_latest.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = RUNS_DIR / "qa_latest.md"
    lines = [
        f"# QA {report['generated_at']}",
        "",
        f"- Событий: {total_events}",
        f"- Кластеров: {len(clusters)}",
        f"- Noise: {noise} ({report['noise_ratio']})",
        f"- Подозрительные ссылки: {broken_links}",
        "",
    ]
    for note in report["notes"]:
        lines.append(f"- ⚠ {note}")
    lines.append("")
    for row in cluster_rows:
        lines.append(f"## {row['title']} (`{row['cluster_id']}`)")
        lines.append(f"size={row['size']} stage={row['stage']} mixed_segments={row['mixed_segments']}")
        for s in row["sample"]:
            lines.append(f"- {s.get('topic_label')} | {s.get('company_normalized') or '—'} | {s.get('link')}")
        lines.append("")
    md.write_text("\n".join(lines), encoding="utf-8")
    return report
