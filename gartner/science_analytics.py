"""Аналитика науки без РИНЦ: центры по корпусу + «наука → рынок»."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from gartner.science_directions import (
    COARSE_DIRECTIONS,
    fine_to_coarse,
    heuristic_fine,
    normalize_fine,
)

# Справочник центров (макет + частые нефтегаз-организации в патентах/новостях)
SCIENCE_CENTERS: list[dict[str, Any]] = [
    {
        "id": "gubkin",
        "name": "РГУ нефти и газа им. Губкина",
        "city": "Москва",
        "aliases": ("губкин", "ргу нефти", "gubkin"),
    },
    {
        "id": "spmi",
        "name": "Санкт-Петербургский горный университет",
        "city": "Санкт-Петербург",
        "aliases": ("горный университет", "спггу", "spmi", "петербургский горный"),
    },
    {
        "id": "kfu",
        "name": "Казанский федеральный университет",
        "city": "Казань",
        "aliases": ("казанский федеральн", "кфу", "kfu"),
    },
    {
        "id": "tiu",
        "name": "Тюменский индустриальный университет",
        "city": "Тюмень",
        "aliases": ("тюменский индустриальн", "тиу", "тюменский нефтяной"),
    },
    {
        "id": "ugntu",
        "name": "УГНТУ",
        "city": "Уфа",
        "aliases": ("угнту", "уфимский государственный нефтяной", "уфимский нефтяной"),
    },
    {
        "id": "ipgg",
        "name": "ИНГГ СО РАН",
        "city": "Новосибирск",
        "aliases": ("ингг", "институт нефтегазовой геологии", "тропова"),
    },
    {
        "id": "tpu",
        "name": "Томский политехнический университет",
        "city": "Томск",
        "aliases": ("томский политехническ", "тпу", "tpu"),
    },
    {
        "id": "vniigaz",
        "name": "ВНИИГАЗ",
        "city": "Москва",
        "aliases": ("вниигаз", "gazprom vniigaz", "газпром вниигаз"),
    },
    {
        "id": "skoltech",
        "name": "Сколтех",
        "city": "Москва",
        "aliases": ("сколтех", "сколковск", "skoltech"),
    },
    {
        "id": "misis",
        "name": "НИТУ МИСИС",
        "city": "Москва",
        "aliases": ("мисис", "misis"),
    },
    {
        "id": "mfti",
        "name": "МФТИ",
        "city": "Долгопрудный",
        "aliases": ("мфти", "физтех", "mipt"),
    },
    {
        "id": "ran_catalysis",
        "name": "Институт катализа СО РАН",
        "city": "Новосибирск",
        "aliases": ("институт катализа", "боросков", "катализа со ран"),
    },
    {
        "id": "iki_ran",
        "name": "ИКИ РАН",
        "city": "Москва",
        "aliases": ("ики ран", "институт космических исследований"),
    },
    {
        "id": "spmii",
        "name": "СПбПУ Петра Великого",
        "city": "Санкт-Петербург",
        "aliases": ("политех петра", "спбпу", "политехнический университет петра"),
    },
]

_CENTER_BY_ID = {c["id"]: c for c in SCIENCE_CENTERS}


def match_centers(text: str) -> list[str]:
    """Возвращает id центров, упомянутых в тексте (по алиасам)."""
    blob = (text or "").lower().replace("ё", "е")
    if not blob.strip():
        return []
    hits: list[str] = []
    for center in SCIENCE_CENTERS:
        for alias in center["aliases"]:
            if alias.lower() in blob:
                hits.append(center["id"])
                break
    return hits


def _parse_tags(raw: str | None) -> list[str]:
    try:
        tags = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [str(t) for t in tags] if isinstance(tags, list) else []


def _parse_directions(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _coarse_from_directions(dirs: dict[str, Any] | None, title: str, text: str) -> list[str]:
    if dirs:
        coarse = dirs.get("coarse") if isinstance(dirs.get("coarse"), list) else []
        if coarse:
            return [str(x) for x in coarse if str(x) in COARSE_DIRECTIONS]
        fine = normalize_fine(dirs.get("fine") if isinstance(dirs.get("fine"), list) else [])
        return fine_to_coarse(fine)
    return fine_to_coarse(heuristic_fine(title, text))


def build_science_centers(
    *,
    science_rows: list[Any],
    patent_rows: list[Any],
) -> list[dict[str, Any]]:
    """Центры по упоминаниям в science-статьях и patentees (без РИНЦ)."""
    stats: dict[str, dict[str, Any]] = {
        cid: {
            "id": cid,
            "name": meta["name"],
            "city": meta["city"],
            "articles": 0,
            "patents": 0,
            "focus_counter": Counter(),
        }
        for cid, meta in _CENTER_BY_ID.items()
    }

    for row in science_rows:
        title = str(row["title"] or "")
        text = str(row["text"] or "")
        dirs = _parse_directions(row["science_directions_json"] if "science_directions_json" in row.keys() else None)
        coarse = _coarse_from_directions(dirs, title, text)
        for cid in match_centers(f"{title}\n{text}"):
            stats[cid]["articles"] += 1
            for label in coarse:
                stats[cid]["focus_counter"][label] += 1

    for row in patent_rows:
        blob = " ".join(
            str(row[k] or "")
            for k in ("patentee", "applicant", "inventor", "title")
            if k in row.keys()
        )
        dirs = _parse_directions(row["directions_json"] if "directions_json" in row.keys() else None)
        coarse = []
        if dirs and isinstance(dirs.get("coarse"), list):
            coarse = [str(x) for x in dirs["coarse"] if str(x) in COARSE_DIRECTIONS]
        for cid in match_centers(blob):
            stats[cid]["patents"] += 1
            for label in coarse:
                stats[cid]["focus_counter"][label] += 1

    out: list[dict[str, Any]] = []
    for cid, item in stats.items():
        articles = int(item["articles"])
        patents = int(item["patents"])
        if articles == 0 and patents == 0:
            continue
        focus = [name for name, _ in item["focus_counter"].most_common(3)]
        # простой индекс 0–100 по корпусу (не цитируемость РИНЦ)
        score = min(100, int(round(articles * 12 + patents * 2.5)))
        out.append(
            {
                "id": cid,
                "name": item["name"],
                "city": item["city"],
                "articles": articles,
                "patents": patents,
                "focus": ", ".join(focus) if focus else "—",
                "score": score,
            }
        )
    out.sort(key=lambda row: (-row["score"], -row["articles"], -row["patents"], row["name"]))
    return out


def build_science_to_market(
    *,
    science_by_coarse: list[dict[str, Any]],
    patents_by_coarse: list[dict[str, Any]],
    news_by_coarse: list[dict[str, Any]],
    patent_weight: float = 0.25,
) -> list[dict[str, Any]]:
    """
    Отношение научной активности к медиапотоку по 8 направлениям.
    score = (science_articles + patent_weight * patents) / max(news, 1)
    """
    sci = {row["name"]: int(row.get("count") or row.get("articles") or 0) for row in science_by_coarse}
    # patents_by_coarse from merge may be {name, patents} or {name, count}
    pat: dict[str, int] = {}
    for row in patents_by_coarse:
        name = row["name"]
        if "patents" in row and "articles" in row:
            # merged bar — берём только патентную часть если передали merge; иначе count
            pat[name] = int(row.get("patents") or 0)
        else:
            pat[name] = int(row.get("count") or row.get("patents") or 0)
    news = {row["name"]: int(row.get("count") or 0) for row in news_by_coarse}

    rows: list[dict[str, Any]] = []
    for name in COARSE_DIRECTIONS:
        s = sci.get(name, 0)
        p = pat.get(name, 0)
        n = news.get(name, 0)
        activity = s + patent_weight * p
        ratio = round(activity / max(n, 1), 2)
        rows.append(
            {
                "name": name,
                "ratio": ratio,
                "science": s,
                "patents": p,
                "news": n,
                "signal": ratio >= 1.5,
            }
        )
    rows.sort(key=lambda row: (-row["ratio"], row["name"]))
    return rows


def count_news_by_coarse(news_rows: list[Any]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for row in news_rows:
        title = str(row["title"] or "")
        text = str(row["text"] or "")[:3000]
        for label in fine_to_coarse(heuristic_fine(title, text)):
            counter[label] += 1
    return [{"name": name, "count": int(counter.get(name, 0))} for name in COARSE_DIRECTIONS if counter.get(name)]
