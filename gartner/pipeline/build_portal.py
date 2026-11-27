"""Сборка JSON для CIO-портала и audit."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from gartner.config import PORTAL_DIR, ensure_dirs
from gartner.db import connect, init_db, utc_now
from gartner.geo_companies import aggregate_geo_from_events

STAGE_LABELS = {
    "emerging": "Зарождающиеся",
    "breakthrough": "Прорывные",
    "mature": "Зрелые",
    "fading": "Угасающие",
}


def _month(value: str | None) -> str | None:
    if not value or len(str(value)) < 7:
        return None
    return str(value)[:7]


def build_portal_payload() -> dict[str, Any]:
    init_db()
    ensure_dirs()
    with connect() as conn:
        clusters = [dict(r) for r in conn.execute("SELECT * FROM clusters").fetchall()]
        forecasts = {
            r["cluster_id"]: dict(r)
            for r in conn.execute("SELECT * FROM cluster_forecasts").fetchall()
        }
        articles_n = conn.execute("SELECT COUNT(*) AS n FROM articles").fetchone()["n"]
        events_n = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
        sources = [r["source"] for r in conn.execute("SELECT DISTINCT source FROM articles WHERE source IS NOT NULL AND source!=''").fetchall()]
        custom_domains = [
            r["domain"]
            for r in conn.execute(
                "SELECT domain FROM custom_sources WHERE enabled=1 AND domain IS NOT NULL AND domain!=''"
            ).fetchall()
        ]
        for domain in custom_domains:
            if domain not in sources:
                sources.append(domain)
        snap = conn.execute("SELECT * FROM snapshots ORDER BY created_at DESC LIMIT 1").fetchone()
        legacy_n = conn.execute(
            "SELECT COUNT(*) AS n FROM clusters WHERE cluster_id LIKE 'legacy_%'"
        ).fetchone()["n"]
        live_links = conn.execute(
            """
            SELECT COUNT(*) AS n FROM events
            WHERE link LIKE 'http%'
              AND link NOT LIKE '%/seed/%'
              AND link NOT LIKE '%/legacy/%'
              AND link NOT LIKE 'legacy://%'
              AND link NOT LIKE '%example.com%'
            """
        ).fetchone()["n"]
        seed_n = conn.execute(
            "SELECT COUNT(*) AS n FROM articles WHERE link LIKE '%/seed/%'"
        ).fetchone()["n"]
        legacy_articles = conn.execute(
            "SELECT COUNT(*) AS n FROM articles WHERE link LIKE '%/legacy/%' OR link LIKE 'legacy://%'"
        ).fetchone()["n"]
        members_audit = [
            dict(r)
            for r in conn.execute(
                """
                SELECT m.*, e.topic_label, e.ai_summary, e.company_normalized, e.category, e.link, e.datatime, e.source,
                       s.title AS sub_cluster_title, s.local_id AS sub_local_id
                FROM cluster_members m
                JOIN events e ON e.event_id = m.event_id
                LEFT JOIN subclusters s ON s.subcluster_id = m.sub_cluster_id
                """
            ).fetchall()
        ]
        all_subs = [dict(r) for r in conn.execute("SELECT * FROM subclusters ORDER BY parent_cluster_id, local_id").fetchall()]

    subs_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in all_subs:
        subs_by_parent[s["parent_cluster_id"]].append(
            {
                "id": s["subcluster_id"],
                "local_id": s["local_id"],
                "title": s.get("title") or s["subcluster_id"],
                "mentions": s.get("member_count") or 0,
            }
        )

    cluster_cards = []
    for c in clusters:
        cid = c["cluster_id"]
        with connect() as conn:
            events = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT e.event_id, e.topic_label, e.ai_summary, e.company_normalized, e.category,
                           e.link, e.datatime, e.source, m.probability, m.sub_cluster_id,
                           s.title AS sub_cluster_title, s.local_id AS sub_local_id
                    FROM cluster_members m
                    JOIN events e ON e.event_id = m.event_id
                    LEFT JOIN subclusters s ON s.subcluster_id = m.sub_cluster_id
                    WHERE m.cluster_id=? AND m.is_noise=0
                    ORDER BY e.datatime DESC
                    """,
                    (cid,),
                ).fetchall()
            ]
        if not events:
            continue
        months = defaultdict(int)
        companies = Counter()
        for e in events:
            m = _month(e.get("datatime"))
            if m:
                months[m] += 1
            if e.get("company_normalized"):
                companies[e["company_normalized"]] += 1
        trend = [{"month": k, "count": months[k]} for k in sorted(months)]
        # slope
        vals = [p["count"] for p in trend]
        slope = 0.0
        if len(vals) >= 2:
            n = len(vals)
            xs = list(range(n))
            mx = sum(xs) / n
            my = sum(vals) / n
            denom = sum((x - mx) ** 2 for x in xs) or 1
            slope = sum((x - mx) * (y - my) for x, y in zip(xs, vals)) / denom

        fc = forecasts.get(cid, {})
        mults = []
        if fc.get("monthly_multipliers_json"):
            try:
                mults = json.loads(fc["monthly_multipliers_json"])
            except Exception:
                mults = []

        cluster_cards.append(
            {
                "id": cid,
                "title": c.get("title") or cid,
                "description": c.get("description") or "",
                "stage": c.get("stage") or "emerging",
                "stage_label": STAGE_LABELS.get(c.get("stage") or "", c.get("stage") or ""),
                "segment_focus": c.get("segment_focus") or "",
                "innovation_score": c.get("innovation_score") or 50,
                "execution_score": c.get("execution_score") or 50,
                "mentions": len(events),
                "companies": [{"name": n, "count": int(cnt)} for n, cnt in companies.most_common(8)],
                "trend": trend,
                "slope": round(float(slope), 4),
                "events": [
                    {
                        "id": e["event_id"],
                        "date": (e.get("datatime") or "")[:10],
                        "topic": e.get("topic_label"),
                        "summary": e.get("ai_summary"),
                        "company": e.get("company_normalized") or "",
                        "category": e.get("category"),
                        "source": e.get("source"),
                        "link": e.get("link"),
                        "sub_cluster_id": e.get("sub_cluster_id"),
                        "sub_cluster_title": e.get("sub_cluster_title"),
                        "sub_local_id": e.get("sub_local_id"),
                    }
                    for e in events[:40]
                ],
                "subclusters": subs_by_parent.get(cid, []),
                "forecast": {
                    "direction": fc.get("direction") or "stable",
                    "confidence": fc.get("confidence") or 0,
                    "narrative": fc.get("narrative") or "",
                    "action": fc.get("action") or "",
                    "provider": fc.get("provider") or "",
                    # multipliers только для audit
                    "monthly_multipliers": mults,
                },
            }
        )

    cluster_cards.sort(key=lambda x: x["mentions"], reverse=True)
    growing = [c for c in cluster_cards if c["slope"] > 0.05][:5]
    fading = [c for c in cluster_cards if c["slope"] < -0.05][:5]

    diff_lines = []
    if snap:
        try:
            diff_lines = json.loads(snap["diff_json"]).get("lines", [])
        except Exception:
            diff_lines = []

    # company leaderboard (secondary)
    company_counter: Counter[str] = Counter()
    for card in cluster_cards:
        for co in card["companies"]:
            company_counter[co["name"]] += co["count"]

    payload = {
        "generated_at": utc_now(),
        "product": "OilTech Radar 3.0",
        "provenance": {
            "legacy_topics": legacy_n,
            "legacy_articles": legacy_articles,
            "seed_articles": seed_n,
            "live_article_links": live_links,
            "is_live_scrape": live_links > 0,
            "banner": (
                "На портале только статьи, скачанные с отраслевых сайтов. "
                f"Живых ссылок в событиях: {live_links}."
                if live_links > 0
                else "Пока нет live-статей. Запустите: python -m gartner.pipeline.run --backfill --recluster"
            ),
        },
        "kpis": {
            "topics": len(cluster_cards),
            "events": events_n,
            "articles": articles_n,
            "sources": len(sources),
            "growing": len(growing),
        },
        "sources": sources,
        "geography": aggregate_geo_from_events(),
        "diff_lines": diff_lines,
        "clusters": cluster_cards,
        "growing": [{"id": c["id"], "title": c["title"], "slope": c["slope"], "mentions": c["mentions"]} for c in growing],
        "fading": [{"id": c["id"], "title": c["title"], "slope": c["slope"], "mentions": c["mentions"]} for c in fading],
        "companies": [{"name": n, "count": int(c)} for n, c in company_counter.most_common(12)],
        "quadrant": [
            {
                "id": c["id"],
                "title": c["title"],
                "x": c["execution_score"],
                "y": c["innovation_score"],
                "stage": c["stage"],
                "mentions": c["mentions"],
            }
            for c in cluster_cards
        ],
        "audit": {
            "members": [
                {
                    "event_id": m["event_id"],
                    "cluster_id": m.get("cluster_id"),
                    "is_noise": m.get("is_noise"),
                    "probability": m.get("probability"),
                    "umap_x": m.get("umap_x"),
                    "umap_y": m.get("umap_y"),
                    "topic_label": m.get("topic_label"),
                    "company": m.get("company_normalized"),
                    "category": m.get("category"),
                    "link": m.get("link"),
                    "datatime": m.get("datatime"),
                    "source": m.get("source"),
                    "ai_summary": m.get("ai_summary"),
                    "sub_cluster_id": m.get("sub_cluster_id"),
                    "sub_cluster_title": m.get("sub_cluster_title"),
                    "sub_local_id": m.get("sub_local_id"),
                    "sub_probability": m.get("sub_probability"),
                }
                for m in members_audit
            ],
            "params_file": "data/cache/cluster_params.json",
        },
    }

    out = PORTAL_DIR / "portal_data.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
