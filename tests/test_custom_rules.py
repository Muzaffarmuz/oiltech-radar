"""Тесты валидации URL и схемы правил."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gartner.custom_sources.rules import (
    domain_from_url,
    normalize_start_url,
    validate_rules_dict,
)
from tests.fixtures_custom_sources import VALID_RULES


def test_normalize_adds_https() -> None:
    assert normalize_start_url("itek.ru").startswith("https://itek.ru")


def test_normalize_rejects_empty() -> None:
    with pytest.raises(ValueError, match="пустой"):
        normalize_start_url("  ")


def test_normalize_rejects_localhost() -> None:
    with pytest.raises(ValueError, match="Локальные"):
        normalize_start_url("http://localhost:8080/news")


def test_normalize_rejects_file_scheme() -> None:
    with pytest.raises(ValueError):
        normalize_start_url("file:///tmp/x")


def test_domain_from_url_strips_www() -> None:
    assert domain_from_url("https://www.ComNews.ru/path") == "comnews.ru"


def test_validate_rules_ok() -> None:
    rules = validate_rules_dict(VALID_RULES)
    assert rules.list.article_link_selector == "a.news-item"
    assert rules.article.title_selector == "h1.title"


def test_validate_rules_requires_selectors() -> None:
    bad = dict(VALID_RULES)
    bad["list"] = {"article_link_selector": "", "link_attr": "href"}
    with pytest.raises(ValidationError):
        validate_rules_dict(bad)


def test_validate_rules_max_pages_bounds() -> None:
    bad = dict(VALID_RULES)
    bad = {
        **VALID_RULES,
        "list": {
            **VALID_RULES["list"],
            "pagination": {"next_selector": None, "max_pages": 0},
        },
    }
    with pytest.raises(ValidationError):
        validate_rules_dict(bad)
