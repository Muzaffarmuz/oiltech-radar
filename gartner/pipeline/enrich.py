"""LLM-имена кластеров, описания, стадии (новизна × внедрённость)."""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime
from typing import Any

from gartner.company import normalize_text
from gartner.config import get_settings
from gartner.db import cache_get, cache_set, connect, init_db, utc_now
from gartner.llm import LLMClient

CLUSTER_PROMPT = """Ты — старший аналитик технологических трендов нефтегаза (Gartner-style).
Сформулируй ОДНУ высокоуровневую категорию бизнес-технологий (3–6 слов): домен + область + функция.
Без названий компаний, продуктов, слишком узких устройств.
Верни ТОЛЬКО JSON: {"name":"...","description":"1-2 предложения для CIO","confidence":0.0}
"""


def _parse_month(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(value)[:7]
    except Exception:
        return None


def _stage_from_scores(innovation: float, execution: float) -> str:
    if innovation >= 55 and execution >= 55:
        return "breakthrough"  # прорывные
    if innovation >= 55 and execution < 55:
        return "emerging"  # зарождающиеся
    if innovation < 55 and execution >= 55:
        return "mature"  # зрелые
    return "fading"  # угасающие


def _heuristic_name(topics: list[str]) -> tuple[str, str]:
    if not topics:
        return "Технологическое направление", "Кластер сформирован по близким технологическим упоминаниям."
    # самый частый topic_label, укороченный
    top = Counter(topics).most_common(1)[0][0]
    name = top if len(top) <= 48 else top[:45] + "…"
    name = name[:1].upper() + name[1:] if name else name
    return name, f"Направление объединяет упоминания вроде «{top}» и близкие технологические контуры."


def enrich_clusters(llm: LLMClient | None = None) -> dict[str, int]:
    init_db()
    settings = get_settings()
    client = llm or LLMClient(settings)
    now = utc_now()
    updated = 0

    with connect() as conn:
        clusters = [dict(r) for r in conn.execute("SELECT * FROM clusters").fetchall()]

    for cluster in clusters:
        cid = cluster["cluster_id"]
        with connect() as conn:
            events = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT e.topic_label, e.ai_summary, e.company_normalized, e.category, e.datatime
                    FROM cluster_members m
                    JOIN events e ON e.event_id = m.event_id
                    WHERE m.cluster_id=? AND m.is_noise=0
                    """,
                    (cid,),
                ).fetchall()
            ]
        if not events:
            continue

        topics = [e["topic_label"] for e in events if e["topic_label"]]
        companies = [e["company_normalized"] for e in events if e.get("company_normalized")]
        categories = [e["category"] for e in events if e.get("category")]
        months = sorted({m for m in (_parse_month(e.get("datatime")) for e in events) if m})

        # novelty ~ свежесть + разнообразие тем; execution ~ число компаний + объём
        n = len(events)
        unique_topics = len(set(topics))
        unique_companies = len(set(companies))
        latest = months[-1] if months else None
        earliest = months[0] if months else None
        freshness = 50.0
        if latest:
            try:
                ly, lm = map(int, latest.split("-"))
                age_months = max(0, (datetime.utcnow().year - ly) * 12 + (datetime.utcnow().month - lm))
                freshness = max(10.0, 90.0 - age_months * 4)
            except Exception:
                pass
        innovation = min(95.0, 0.45 * freshness + 0.35 * min(100, unique_topics * 12) + 0.20 * min(100, n * 5))
        execution = min(95.0, 0.40 * min(100, n * 6) + 0.40 * min(100, unique_companies * 15) + 0.20 * (70 if earliest and latest and earliest != latest else 40))
        stage = _stage_from_scores(innovation, execution)
        segment_focus = Counter(categories).most_common(1)[0][0] if categories else "Upstream"

        # стабильность имени: не переименовывать без нужды
        current_title = cluster.get("title") or ""
        looks_placeholder = current_title.startswith("Тема c") or current_title.startswith("Тема ")
        cache_key = f"cluster_name:{cid}:{hash(tuple(sorted(set(topics))[:12]))}"
        named = cache_get(cache_key)
        if named is None:
            if client.enabled:
                try:
                    named = client.json_call(
                        CLUSTER_PROMPT,
                        {
                            "topics": topics[:20],
                            "summaries": [e.get("ai_summary") or "" for e in events[:12]],
                            "companies": list(set(companies))[:10],
                        },
                    )
                except Exception:
                    name, desc = _heuristic_name(topics)
                    named = {"name": name, "description": desc, "confidence": 0.4}
            else:
                name, desc = _heuristic_name(topics)
                named = {"name": name, "description": desc, "confidence": 0.4}
            cache_set(cache_key, "cluster_name", named)

        new_title = normalize_text(named.get("name")) or _heuristic_name(topics)[0]
        new_desc = normalize_text(named.get("description")) or ""

        if looks_placeholder or not current_title:
            title = new_title
            description = new_desc
        else:
            # сохраняем старое имя (стабильность), описание можно обновить
            title = current_title
            description = new_desc or (cluster.get("description") or "")

        with connect() as conn:
            conn.execute(
                """
                UPDATE clusters SET title=?, description=?, stage=?, segment_focus=?,
                    innovation_score=?, execution_score=?, updated_at=?
                WHERE cluster_id=?
                """,
                (title, description, stage, segment_focus, float(innovation), float(execution), now, cid),
            )
        updated += 1

    return {"clusters_updated": updated}
