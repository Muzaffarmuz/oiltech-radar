"""Словарь меток потоков.

У одной статьи список меток, не одна. Пустой список значит «без потока»:
статью не удаляют, она попадает в отчёт неразмеченных.
Метка digital не заменяет поток и ставится вместе с другими.
"""

from __future__ import annotations

FLOW_TAGS: dict[str, str] = {
    "news": "Новости и события. Промышленное событие нефтегаза: добыча, бурение, переработка, поставки, конференции, пилоты.",
    "science": "Наука и патенты. Исследование, вуз, НИИ, патент, метод, эксперимент.",
    "investments": "Инвестиции и стартапы. Сделка, раунд, грант, покупка доли, проектное финансирование, новый игрок.",
    "policy": "Политика и рынок. Санкция, закон, регулятор, авария, рынок, цена, экспорт.",
}

DIGITAL_TAG = "digital"
DIGITAL_RULE = (
    "Конкретная ИТ- или цифровая технология: ИИ, цифровой двойник, промышленное ПО, "
    "робот, платформа данных. Общий лозунг «цифровизация» без предмета метку не получает."
)

ALLOWED_TAGS = frozenset([*FLOW_TAGS, DIGITAL_TAG])


def normalize_flow_tags(tags: list[str]) -> list[str]:
    """Оставляет только известные метки, без повторов, в порядке словаря."""
    found = set(tags)
    unknown = found - ALLOWED_TAGS
    if unknown:
        raise ValueError(f"Неизвестные метки потока: {', '.join(sorted(unknown))}")
    ordered = [code for code in FLOW_TAGS if code in found]
    if DIGITAL_TAG in found:
        ordered.append(DIGITAL_TAG)
    return ordered
