"""Реестр патентов Роспатента: нормализация, МПК→направления, агрегаты."""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from gartner.science_directions import (
    COARSE_DIRECTIONS,
    FINE_DIRECTIONS,
    build_direction_payload,
    heuristic_fine,
    normalize_fine,
)

# Префикс МПК → детальное направление (длинные префиксы проверяем раньше)
_IPC_FINE_RULES: list[tuple[str, str]] = [
    ("E21B33", "Строительство скважин"),
    ("E21B43/22", "EOR"),
    ("E21B43/16", "EOR"),
    ("E21B43/26", "ГРП"),
    ("E21B43/27", "ГРП"),
    ("E21B43", "Добыча нефти"),
    ("E21B7", "Бурение"),
    ("E21B10", "Бурение"),
    ("E21B17", "Бурение"),
    ("E21B21", "Бурение"),
    ("E21B4", "Бурение"),
    ("E21B", "Бурение"),
    ("G01V", "Геофизика"),
    ("C10G", "Переработка нефти"),
    ("C10L", "Переработка нефти"),
    ("C10M", "Нефтехимия"),
    ("C07C", "Нефтехимия"),
    ("C08F", "Нефтехимия"),
    ("B01J", "Нефтехимия"),
    ("F17C", "СПГ"),
    ("F17D", "Трубопроводы"),
    ("C09K8", "ГРП"),
    ("C09K", "Новые материалы"),
    ("C01B3", "Водород"),
    ("B01D53", "CCUS"),
    ("G06", "ИТ и автоматизация"),
    ("G05", "ИТ и автоматизация"),
    ("H04", "ИТ и автоматизация"),
]

_PATENT_ID_RE = re.compile(
    r"\b(?:RU|РФ)[\s\-№]*(\d{6,8})\b",
    re.IGNORECASE,
)
_IDENTITY_NUM_RE = re.compile(r"(\d{6,8})")


def normalize_patent_id(identity: str | None) -> str:
    """RU 2815817 C1 → RU2815817"""
    text = str(identity or "").strip().upper().replace("РФ", "RU")
    if not text:
        return ""
    match = _IDENTITY_NUM_RE.search(text)
    if not match:
        return re.sub(r"[^A-Z0-9]", "", text)[:32]
    return f"RU{match.group(1)}"


def parse_ipc_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[;,\n|]+", str(raw))
    out: list[str] = []
    for part in parts:
        code = part.strip().upper().replace(" ", "")
        if code:
            out.append(code)
    return out


def ipc_to_fine(ipc_codes: list[str], title: str = "", abstract: str = "") -> list[str]:
    hits: list[str] = []
    for code in ipc_codes:
        normalized = code.upper().replace(" ", "")
        for prefix, label in _IPC_FINE_RULES:
            if normalized.startswith(prefix.replace(" ", "").upper()):
                if label not in hits:
                    hits.append(label)
                break
        if len(hits) >= 2:
            break
    if not hits:
        hits = heuristic_fine(title, abstract)
    return normalize_fine(hits)


def fips_db_code(identity_or_kind: str | None) -> str:
    """БД ФИПС: RUPAT — изобретения (C1/C2), RUPM — полезные модели (U1)."""
    blob = (identity_or_kind or "").upper()
    if re.search(r"\bU\d?\b", blob) or blob.strip() in {"U", "U1", "U2"}:
        return "RUPM"
    return "RUPAT"


def fips_url(patent_id: str, identity: str | None = None) -> str:
    """Ссылка на карточку ФИПС. Для U1 нужен DB=RUPM, иначе короткий номер попадает в старые изобретения."""
    num = re.sub(r"\D", "", patent_id or "")
    if not num:
        num = re.sub(r"\D", "", identity or "")
    if not num:
        return ""
    db = fips_db_code(identity or patent_id)
    return (
        "https://www1.fips.ru/registers-doc-view/fips_servlet"
        f"?DB={db}&DocNumber={num}&TypeFile=html"
    )


def extract_patent_ids_from_text(*chunks: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    blob = "\n".join(str(c or "") for c in chunks)
    for match in _PATENT_ID_RE.finditer(blob):
        pid = f"RU{match.group(1)}"
        if pid not in seen:
            seen.add(pid)
            out.append(pid)
    return out


def merge_direction_bars(
    article_rows: list[dict[str, Any]],
    patent_rows: list[dict[str, Any]],
    *,
    scale: str,
) -> list[dict[str, Any]]:
    """Склеивает [{name,count}] статей и патентов → [{name, articles, patents}]."""
    order = COARSE_DIRECTIONS if scale == "coarse" else FINE_DIRECTIONS
    art = {row["name"]: int(row.get("count") or 0) for row in article_rows}
    pat = {row["name"]: int(row.get("count") or 0) for row in patent_rows}
    names = list(order)
    for name in list(art) + list(pat):
        if name not in names:
            names.append(name)
    merged = []
    for name in names:
        a = art.get(name, 0)
        p = pat.get(name, 0)
        if a or p:
            merged.append({"name": name, "articles": a, "patents": p, "count": a + p})
    return merged


def directions_from_patent_row(row: dict[str, Any]) -> dict[str, Any]:
    ipc = parse_ipc_list(row.get("ipc"))
    fine = ipc_to_fine(ipc, str(row.get("title") or ""), str(row.get("abstract") or ""))
    return build_direction_payload(fine, reason="ipc" if ipc else "heuristic")


def normalize_pub_date(raw: str | None) -> str:
    """2025.09.18 / 2025-09-18 → 2025-09-18; иначе ''."""
    text = str(raw or "").strip().replace(".", "-")
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    if len(text) >= 7 and text[4] == "-":
        return text[:7] + "-01"
    return ""


def patent_chart_since(conn: Any, months: int = 6) -> tuple[str, str]:
    """(since_date, max_date) для окна графика; dates YYYY-MM-DD."""
    from datetime import date, timedelta

    row = conn.execute(
        "SELECT publication_date FROM patents WHERE publication_date IS NOT NULL AND publication_date != ''"
    ).fetchall()
    dates = [normalize_pub_date(r["publication_date"] if hasattr(r, "keys") else r[0]) for r in row]
    dates = [d for d in dates if d]
    if not dates:
        return "", ""
    max_d = max(dates)
    try:
        y, m, day = (int(x) for x in max_d.split("-"))
        end = date(y, m, min(day, 28))
    except ValueError:
        return "", max_d
    # приблизительно months назад
    year = end.year
    month = end.month - (months - 1)
    while month <= 0:
        month += 12
        year -= 1
    since = date(year, month, 1).isoformat()
    return since, max_d


def aggregate_patent_counts(conn_rows: list[Any], scale: str) -> list[dict[str, Any]]:
    key = "coarse" if scale == "coarse" else "fine"
    order = COARSE_DIRECTIONS if key == "coarse" else FINE_DIRECTIONS
    counter: Counter[str] = Counter()
    for row in conn_rows:
        try:
            payload = json.loads(row["directions_json"] or "{}")
        except (json.JSONDecodeError, TypeError, KeyError):
            continue
        labels = payload.get(key) or []
        if not isinstance(labels, list):
            continue
        for label in labels:
            if label:
                counter[str(label)] += 1
    rows = [{"name": name, "count": int(counter.get(name, 0))} for name in order]
    for name, count in counter.most_common():
        if name not in order:
            rows.append({"name": name, "count": int(count)})
    return [row for row in rows if row["count"] > 0]
