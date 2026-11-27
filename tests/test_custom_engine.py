"""Тесты фиксированного движка извлечения."""

from __future__ import annotations

import pytest

from gartner.custom_sources.engine import (
    extract_article,
    extract_list_links,
    find_next_page,
    parse_date_any,
    run_rules_engine,
)
from gartner.custom_sources.rules import validate_rules_dict
from tests.fixtures_custom_sources import (
    ARTICLE_HTML,
    ARTICLE_HTML_THIN,
    LIST_HTML,
    LIST_HTML_PAGE2,
    VALID_RULES,
)


def test_parse_date_iso_and_ru() -> None:
    assert parse_date_any("2026-03-15T10:00:00Z") == "2026-03-15"
    assert parse_date_any("15.03.2026") == "2026-03-15"
    assert parse_date_any("15 марта 2026") == "2026-03-15"
    assert parse_date_any("") == ""


def test_extract_list_links() -> None:
    rules = validate_rules_dict(VALID_RULES)
    links = extract_list_links(LIST_HTML, rules, "https://example-news.test/news/")
    assert links == [
        "https://example-news.test/news/one",
        "https://example-news.test/news/two",
    ]


def test_extract_article_fields() -> None:
    rules = validate_rules_dict(VALID_RULES)
    rec = extract_article(ARTICLE_HTML, rules, "https://example-news.test/news/one")
    assert rec is not None
    assert rec.title.startswith("Цифровой двойник")
    assert "АСУ ТП" in rec.text
    assert rec.datatime == "2026-03-15"
    assert rec.source == "example-news.test"
    assert "evil" not in rec.text


def test_extract_article_rejects_thin_text() -> None:
    rules = validate_rules_dict(VALID_RULES)
    assert extract_article(ARTICLE_HTML_THIN, rules, "https://example-news.test/x") is None


def test_run_rules_engine_with_mocked_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    import gartner.custom_sources.engine as engine

    pages = {
        "https://example-news.test/news/": LIST_HTML,
        "https://example-news.test/news?page=2": LIST_HTML_PAGE2,
        "https://example-news.test/news/one": ARTICLE_HTML,
        "https://example-news.test/news/two": ARTICLE_HTML,
        "https://example-news.test/news/three": ARTICLE_HTML,
    }

    def fake_fetch(url: str, **kwargs):
        html = pages.get(url)
        if html is None:
            return None, f"missing {url}"
        return html, None

    monkeypatch.setattr(engine, "fetch_html_safe", fake_fetch)
    result = run_rules_engine(VALID_RULES, max_articles=10)
    assert result.ok
    assert result.links_found == 3
    assert result.pages_fetched >= 2
    assert len(result.articles) == 3


def test_page_query_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    import gartner.custom_sources.engine as engine

    pages = {
        "https://example-news.test/news/": LIST_HTML,
        "https://example-news.test/news/?page=2": LIST_HTML_PAGE2,
        "https://example-news.test/news/one": ARTICLE_HTML,
        "https://example-news.test/news/two": ARTICLE_HTML,
        "https://example-news.test/news/three": ARTICLE_HTML,
    }

    def fake_fetch(url: str, **kwargs):
        html = pages.get(url)
        if html is None:
            return None, f"missing {url}"
        return html, None

    monkeypatch.setattr(engine, "fetch_html_safe", fake_fetch)
    rules = {
        **VALID_RULES,
        "list": {
            "article_link_selector": "a.news-item",
            "link_attr": "href",
            "pagination": {"strategy": "page_query", "page_param": "page", "page_start": 1, "max_pages": 2},
        },
    }
    result = run_rules_engine(rules, max_articles=10)
    assert result.ok
    assert result.links_found == 3
    nxt = find_next_page(LIST_HTML, validate_rules_dict(rules), "https://example-news.test/news/")
    assert nxt and "page=2" in nxt


def test_run_rules_engine_fails_without_links(monkeypatch: pytest.MonkeyPatch) -> None:
    import gartner.custom_sources.engine as engine

    monkeypatch.setattr(engine, "fetch_html_safe", lambda url, **kw: ("<html></html>", None))
    result = run_rules_engine(VALID_RULES)
    assert not result.ok
    assert "ссылк" in (result.error or "").lower()
