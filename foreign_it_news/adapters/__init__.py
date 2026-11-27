"""Реестр ручных адаптеров foreign IT news."""

from __future__ import annotations

from typing import Callable

from . import chevron, conocophillips, eni, petrobras
from .base import ListItem

ListFn = Callable[[], list[ListItem]]

ADAPTERS: dict[str, dict] = {
    "chevron": {
        "name": "Chevron",
        "list_articles": chevron.list_articles,
    },
    "eni": {
        "name": "Eni",
        "list_articles": eni.list_articles,
    },
    "conocophillips": {
        "name": "ConocoPhillips",
        "list_articles": conocophillips.list_articles,
    },
    "petrobras": {
        "name": "Petrobras",
        "list_articles": petrobras.list_articles,
    },
}


def get_adapter(company_id: str) -> dict | None:
    return ADAPTERS.get((company_id or "").lower())
