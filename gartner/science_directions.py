"""Таксономия направлений науки: 23 детальных → 8 укрупнённых.

Детальный список = отраслевые лейблы с главной (concept.js) без ИТ-потока.
ИТ вынесен отдельным детальным лейблом «ИТ и автоматизация» (совпадает с coarse).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

# 8 корзин макета «Наука»
COARSE_DIRECTIONS: list[str] = [
    "ИТ и автоматизация",
    "Геологоразведка",
    "Бурение и скважины",
    "Добыча и нефтесервис",
    "Транспорт и СПГ",
    "Переработка и нефтехимия",
    "Безопасность и экология",
    "Энергопереход",
]

# 23 отраслевых + ИТ как детальный ярлык для digital-науки
FINE_DIRECTIONS: list[str] = [
    "Геология",
    "Геофизика",
    "Разведка",
    "Бурение",
    "Строительство скважин",
    "ГРП",
    "Нефтесервис",
    "Добыча нефти",
    "Добыча газа",
    "EOR",
    "Промысловое оборудование",
    "Транспортировка",
    "Трубопроводы",
    "Переработка нефти",
    "Переработка газа",
    "Нефтехимия",
    "СПГ",
    "Энергетика",
    "Водород",
    "Промышленная безопасность",
    "Экология",
    "CCUS",
    "Новые материалы",
    "ИТ и автоматизация",
]

FINE_TO_COARSE: dict[str, str] = {
    "Геология": "Геологоразведка",
    "Геофизика": "Геологоразведка",
    "Разведка": "Геологоразведка",
    "Бурение": "Бурение и скважины",
    "Строительство скважин": "Бурение и скважины",
    "ГРП": "Бурение и скважины",
    "Нефтесервис": "Добыча и нефтесервис",
    "Добыча нефти": "Добыча и нефтесервис",
    "Добыча газа": "Добыча и нефтесервис",
    "EOR": "Добыча и нефтесервис",
    "Промысловое оборудование": "Добыча и нефтесервис",
    "Транспортировка": "Транспорт и СПГ",
    "Трубопроводы": "Транспорт и СПГ",
    "СПГ": "Транспорт и СПГ",
    "Переработка нефти": "Переработка и нефтехимия",
    "Переработка газа": "Переработка и нефтехимия",
    "Нефтехимия": "Переработка и нефтехимия",
    "Промышленная безопасность": "Безопасность и экология",
    "Экология": "Безопасность и экология",
    "Водород": "Энергопереход",
    "CCUS": "Энергопереход",
    "Энергетика": "Энергопереход",
    "Новые материалы": "Энергопереход",
    "ИТ и автоматизация": "ИТ и автоматизация",
}

# Ключевые слова для эвристики, если LLM недоступен
_FINE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("ИТ и автоматизация", ("цифров", "ии ", "ии-", "машинн", "нейросет", "робот", "iot", "кибер", "twin", "двойник", "беспилот", "автоматизац", "алгоритм")),
    ("Геофизика", ("геофиз", "сейсм", "электроразвед")),
    ("Геология", ("геолог", "коллектор", "свит", "пласт", "керн")),
    ("Разведка", ("разведк", "геологоразвед", "поисков")),
    ("ГРП", ("грп", "гидроразрыв", "пропант")),
    ("Бурение", ("бурен", "скважин", "долот", "rss", "роторн")),
    ("Строительство скважин", ("строительств скважин", "обсад", "цементир")),
    ("EOR", ("eor", "нефтеотдач", "мун", "полимер-пав", "заводнен")),
    ("Добыча нефти", ("добыч нефти", "нефтедобыч")),
    ("Добыча газа", ("добыч газа", "газодобыч")),
    ("Нефтесервис", ("нефтесервис", "сервисн компан")),
    ("Промысловое оборудование", ("промыслов", "устьево", "шгн", "эсн")),
    ("СПГ", ("спг", "lng", "сжиженн")),
    ("Трубопроводы", ("трубопровод", "нефтепровод", "газопровод")),
    ("Транспортировка", ("транспорт", "логистик", "танкер")),
    ("Нефтехимия", ("нефтехим", "полимер", "мономер")),
    ("Переработка нефти", ("нефтеперераб", "нпз", "гидрокрекинг", "гидроочист")),
    ("Переработка газа", ("газоперераб", "гпз", "аминов")),
    ("Водород", ("водород", "h2")),
    ("CCUS", ("ccus", "улавливан", "со2", "co₂", "со₂")),
    ("Экология", ("эколог", "метан", "выброс", "углерод")),
    ("Промышленная безопасность", ("промбезопас", "охрана труда", "аварии")),
    ("Новые материалы", ("материал", "катализатор", "цеолит", "композит")),
    ("Энергетика", ("энергет", "электростанц", "генерац")),
]


def normalize_fine(labels: list[str] | None) -> list[str]:
    allowed = set(FINE_DIRECTIONS)
    seen: set[str] = set()
    out: list[str] = []
    for raw in labels or []:
        name = str(raw or "").strip()
        if name in allowed and name not in seen:
            seen.add(name)
            out.append(name)
    return out[:3]


def fine_to_coarse(fine: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for label in fine:
        coarse = FINE_TO_COARSE.get(label)
        if coarse and coarse not in seen:
            seen.add(coarse)
            out.append(coarse)
    return out


def heuristic_fine(title: str, text: str) -> list[str]:
    blob = f"{title}\n{text}".lower()
    hits: list[str] = []
    for label, keys in _FINE_KEYWORDS:
        if any(key in blob for key in keys):
            hits.append(label)
        if len(hits) >= 2:
            break
    return normalize_fine(hits) or ["ИТ и автоматизация"] if any(
        k in blob for k in ("цифр", "ии", "автомат", "данн")
    ) else normalize_fine(hits)


def build_direction_payload(fine: list[str], reason: str = "") -> dict[str, Any]:
    cleaned = normalize_fine(fine)
    return {
        "fine": cleaned,
        "coarse": fine_to_coarse(cleaned),
        "reason": str(reason or "").strip()[:280],
    }


def aggregate_counts(items: list[dict[str, Any]], scale: str = "coarse") -> list[dict[str, Any]]:
    """scale: coarse | fine → [{name, count}, ...] отсортировано по count desc."""
    key = "coarse" if scale == "coarse" else "fine"
    order = COARSE_DIRECTIONS if key == "coarse" else FINE_DIRECTIONS
    counter: Counter[str] = Counter()
    for item in items:
        dirs = item.get("directions") or {}
        labels = dirs.get(key) or []
        if not isinstance(labels, list):
            continue
        # статья считается один раз на каждое направление
        for label in labels:
            if isinstance(label, str) and label:
                counter[label] += 1
    rows = [{"name": name, "count": int(counter.get(name, 0))} for name in order]
    # в конец — неожиданные лейблы, если есть
    for name, count in counter.most_common():
        if name not in order:
            rows.append({"name": name, "count": int(count)})
    return [row for row in rows if row["count"] > 0] or [
        {"name": name, "count": 0} for name in (order if scale == "coarse" else order[:8])
    ]


def taxonomy_meta() -> dict[str, Any]:
    return {
        "coarse": list(COARSE_DIRECTIONS),
        "fine": list(FINE_DIRECTIONS),
        "fine_to_coarse": dict(FINE_TO_COARSE),
        "fine_industrial_count": 23,
        "note": "23 отраслевых лейбла с главной + «ИТ и автоматизация»; 8 = макет науки",
    }
