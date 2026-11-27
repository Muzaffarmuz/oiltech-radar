"""Прогнозы по кластерам: LLM + статистический fallback."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from gartner.config import get_settings
from gartner.db import connect, init_db, utc_now
from gartner.llm import LLMClient

FORECAST_PROMPT = """Ты — старший аналитик технологического рынка нефтегазовой отрасли России.
Составь прогноз на 6 месяцев. Верни ТОЛЬКО JSON:
{
  "direction": "growing",
  "confidence": 0.0,
  "narrative": "...",
  "action": "...",
  "monthly_multipliers": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
}
direction: growing | stable | declining
narrative: 2–3 предложения для топ-менеджмента, БЕЗ конкретных процентов и ложных цифр.
action: строго "[глагол] + [конкретная технология] + [срок/условие]".
monthly_multipliers: ровно 6 чисел относительно последнего месяца.
"""


def _monthly_counts(cluster_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT substr(e.datatime, 1, 7) AS month, COUNT(*) AS cnt
            FROM cluster_members m
            JOIN events e ON e.event_id = m.event_id
            WHERE m.cluster_id=? AND m.is_noise=0 AND e.datatime IS NOT NULL AND length(e.datatime) >= 7
            GROUP BY substr(e.datatime, 1, 7)
            ORDER BY month
            """,
            (cluster_id,),
        ).fetchall()
    return [{"month": r["month"], "count": int(r["cnt"])} for r in rows]


def _stat_forecast(series: list[dict[str, Any]]) -> dict[str, Any]:
    if len(series) < 2:
        return {
            "direction": "stable",
            "confidence": 0.3,
            "narrative": "Недостаточно истории упоминаний для уверенного сценария; направление выглядит стабильным.",
            "action": "Мониторить упоминания направления ежемесячно до накопления ряда",
            "monthly_multipliers": [1.0] * 6,
            "provider": "stat-fallback",
        }
    values = [p["count"] for p in series]
    # простой slope
    n = len(values)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    denom = sum((x - mean_x) ** 2 for x in xs) or 1.0
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values)) / denom
    last = values[-1] or 1.0
    if slope > 0.15:
        direction = "growing"
        mults = [1.0 + 0.05 * (i + 1) for i in range(6)]
        narrative = "Упоминания направления растут. Вероятен переход от пилотов к расширению практик у лидеров рынка."
        action = "Запустить пилот ключевой технологии направления в течение квартала"
    elif slope < -0.15:
        direction = "declining"
        mults = [max(0.5, 1.0 - 0.05 * (i + 1)) for i in range(6)]
        narrative = "Интенсивность упоминаний снижается. Тема может уходить в зрелость или терять информационный интерес."
        action = "Пересмотреть приоритет направления и зафиксировать критерии продолжения инвестиций"
    else:
        direction = "stable"
        mults = [1.0] * 6
        narrative = "Поток упоминаний относительно ровный. Тема присутствует на рынке без резкого ускорения."
        action = "Удерживать точечный мониторинг лидеров внедрения по теме"
    return {
        "direction": direction,
        "confidence": min(0.75, 0.35 + n * 0.05),
        "narrative": narrative,
        "action": action,
        "monthly_multipliers": [round(m, 3) for m in mults],
        "provider": "stat-fallback",
    }


def forecast_clusters(llm: LLMClient | None = None) -> dict[str, int]:
    init_db()
    settings = get_settings()
    client = llm or LLMClient(settings)
    now = utc_now()
    updated = 0
    fallback = 0

    with connect() as conn:
        clusters = [dict(r) for r in conn.execute("SELECT * FROM clusters").fetchall()]

    for cluster in clusters:
        cid = cluster["cluster_id"]
        series = _monthly_counts(cid)
        with connect() as conn:
            n_members = conn.execute(
                "SELECT COUNT(*) AS n FROM cluster_members WHERE cluster_id=? AND is_noise=0",
                (cid,),
            ).fetchone()["n"]
        if n_members == 0:
            continue

        result: dict[str, Any] | None = None
        provider = "heuristic"
        if client.enabled:
            try:
                payload = {
                    "cluster": cluster.get("title"),
                    "stage": cluster.get("stage"),
                    "total_mentions": n_members,
                    "monthly_data": series[-12:],
                }
                result = client.json_call(FORECAST_PROMPT, payload)
                provider = f"llm:{settings.llm_model}"
            except Exception:
                result = None

        if not result:
            result = _stat_forecast(series)
            provider = result.pop("provider", "stat-fallback")
            fallback += 1

        direction = str(result.get("direction", "stable"))
        if direction not in {"growing", "stable", "declining"}:
            direction = "stable"
        mults = result.get("monthly_multipliers") or [1.0] * 6
        if not isinstance(mults, list) or len(mults) != 6:
            mults = [1.0] * 6

        with connect() as conn:
            conn.execute(
                """
                INSERT INTO cluster_forecasts(cluster_id, direction, confidence, narrative, action,
                    monthly_multipliers_json, provider, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cluster_id) DO UPDATE SET
                    direction=excluded.direction,
                    confidence=excluded.confidence,
                    narrative=excluded.narrative,
                    action=excluded.action,
                    monthly_multipliers_json=excluded.monthly_multipliers_json,
                    provider=excluded.provider,
                    updated_at=excluded.updated_at
                """,
                (
                    cid,
                    direction,
                    float(result.get("confidence") or 0.0),
                    str(result.get("narrative") or ""),
                    str(result.get("action") or ""),
                    json.dumps([float(x) for x in mults]),
                    provider,
                    now,
                ),
            )
        updated += 1

    return {"forecasts": updated, "fallback": fallback}
