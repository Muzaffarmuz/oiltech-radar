"""География событий по справочнику компания → город (без LLM).

Правило: география берётся от компании. Если в тексте есть и город, и компания —
главнее компания (в т.ч. при несовпадении).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from gartner.config import DATA_DIR
from gartner.db import connect, init_db

COMPANY_GEO_PATH = DATA_DIR / "company_geo.json"


def _norm(text: str) -> str:
    text = (text or "").lower().replace("ё", "е")
    text = text.replace("«", "").replace("»", "").replace('"', "")
    text = re.sub(r"\b(пао|ао|ооо|зао|пк|нк)\b\.?", " ", text)
    text = re.sub(r"[-–—_/.,;:()]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


@lru_cache(maxsize=1)
def load_company_geo(path: str | None = None) -> list[dict[str, Any]]:
    file_path = Path(path) if path else COMPANY_GEO_PATH
    if not file_path.exists():
        return []
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else []


def build_alias_index(entries: list[dict[str, Any]] | None = None) -> list[tuple[str, dict[str, Any]]]:
    """Список (нормализованный алиас, запись), длинные алиасы первыми."""
    entries = entries if entries is not None else load_company_geo()
    pairs: list[tuple[str, dict[str, Any]]] = []
    for row in entries:
        names = [row.get("canonical_name") or "", *(row.get("aliases") or [])]
        for name in names:
            key = _norm(str(name))
            if len(key) < 3:
                continue
            pairs.append((key, row))
    pairs.sort(key=lambda item: len(item[0]), reverse=True)
    return pairs


def match_company(text: str, alias_index: list[tuple[str, dict[str, Any]]] | None = None) -> dict[str, Any] | None:
    """Первое совпадение по самому длинному алиасу. Составные «A, B» бьём по частям — берём первую."""
    alias_index = alias_index if alias_index is not None else build_alias_index()
    raw = (text or "").strip()
    if not raw:
        return None
    parts = [p.strip() for p in re.split(r"[,;/|]", raw) if p.strip()] or [raw]
    for part in parts:
        key = _norm(part)
        if not key:
            continue
        for alias, row in alias_index:
            if key == alias or alias in key:
                return row
    return None


def aggregate_geo_from_events() -> dict[str, Any]:
    """Считает города по событиям с меткой компании.

    Слои карты:
    - inv — все события, привязанные через компанию
    - sci — среди них статьи с flow-тегом science
    - news — среди них статьи с flow-тегом news (или без science, если тегов нет — 0)
    """
    init_db()
    alias_index = build_alias_index()
    if not alias_index:
        return {"mode": "company_hq", "cities": [], "matched_events": 0, "unmatched_events": 0}

    cities: dict[str, dict[str, Any]] = {}
    matched = 0
    unmatched = 0

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT e.event_id, e.company, e.company_normalized, e.article_id,
                   a.flow_tags_json
            FROM events e
            LEFT JOIN articles a ON a.article_id = e.article_id
            WHERE (e.company IS NOT NULL AND trim(e.company) != '')
               OR (e.company_normalized IS NOT NULL AND trim(e.company_normalized) != '')
            """
        ).fetchall()

    for row in rows:
        blob = " | ".join(
            part
            for part in (row["company_normalized"] or "", row["company"] or "")
            if part
        )
        hit = match_company(blob, alias_index)
        if not hit or not hit.get("city"):
            unmatched += 1
            continue
        matched += 1
        city = str(hit["city"])
        bucket = cities.setdefault(
            city,
            {
                "name": city,
                "news": 0,
                "sci": 0,
                "inv": 0,
                "companies": CounterLike(),
                "lat": hit.get("lat"),
                "lon": hit.get("lon"),
            },
        )
        bucket["inv"] += 1
        bucket["companies"].add(str(hit.get("canonical_name") or blob))

        tags: list[str] = []
        try:
            tags = json.loads(row["flow_tags_json"] or "[]")
        except json.JSONDecodeError:
            tags = []
        if isinstance(tags, list):
            if "science" in tags:
                bucket["sci"] += 1
            if "news" in tags:
                bucket["news"] += 1

    city_list = []
    for city, bucket in cities.items():
        orgs = bucket["companies"].top(6)
        city_list.append(
            {
                "name": city,
                "news": int(bucket["news"]),
                "sci": int(bucket["sci"]),
                "inv": int(bucket["inv"]),
                "org": ", ".join(orgs) if orgs else "компании из корпуса",
                "lat": bucket.get("lat"),
                "lon": bucket.get("lon"),
            }
        )
    city_list.sort(key=lambda item: item["inv"], reverse=True)
    return {
        "mode": "company_hq",
        "rule": "company_over_city",
        "matched_events": matched,
        "unmatched_events": unmatched,
        "cities": city_list,
    }


class CounterLike:
    def __init__(self) -> None:
        self._counts: dict[str, int] = defaultdict(int)

    def add(self, name: str) -> None:
        self._counts[name] += 1

    def top(self, n: int) -> list[str]:
        return [name for name, _ in sorted(self._counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]
