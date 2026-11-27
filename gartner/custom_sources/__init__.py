"""Пользовательские источники: краул + trafilatura (3.2)."""

from gartner.custom_sources.service import (
    add_custom_source,
    delete_custom_source,
    list_custom_sources,
    scrape_all_custom_sources,
)

__all__ = [
    "add_custom_source",
    "delete_custom_source",
    "list_custom_sources",
    "scrape_all_custom_sources",
]
