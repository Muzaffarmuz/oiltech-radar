"""Тесты нормализации ответа LLM и discover fallback."""

from __future__ import annotations

from gartner.custom_sources.discover import _normalize_llm_rules, heuristic_rules
from gartner.custom_sources.rules import validate_rules_dict
from tests.fixtures_custom_sources import HOME_HTML, LIST_HTML, VALID_RULES


def test_normalize_llm_null_fields() -> None:
    raw = {
        "list_url": None,
        "list": {
            "article_link_selector": None,
            "link_attr": None,
            "pagination": {"next_selector": None, "max_pages": None},
        },
        "article": {
            "title_selector": None,
            "date_selector": None,
            "date_attr": None,
            "text_selector": None,
            "remove_selectors": None,
        },
        "source_name": None,
        "version": 1,
    }
    normalized = _normalize_llm_rules(
        raw,
        start_url="https://oilcapital.ru/",
        candidates=["https://oilcapital.ru/news/"],
    )
    rules = validate_rules_dict(normalized)
    assert rules.list_url.startswith("https://")
    assert rules.list.article_link_selector
    assert rules.article.title_selector
    assert rules.article.text_selector
    assert rules.source_name == "oilcapital.ru"


def test_heuristic_finds_links(monkeypatch) -> None:
    import gartner.custom_sources.discover as discover
    import gartner.custom_sources.engine as engine
    from tests.fixtures_custom_sources import ARTICLE_HTML, LIST_HTML_PAGE2

    pages = {
        "https://example-news.test/": HOME_HTML,
        "https://example-news.test/news/": LIST_HTML,
        "https://example-news.test/news?page=2": LIST_HTML_PAGE2,
        "https://example-news.test/news/one": ARTICLE_HTML,
        "https://example-news.test/news/two": ARTICLE_HTML,
        "https://example-news.test/news/three": ARTICLE_HTML,
        "https://example-news.test/analytics": LIST_HTML,
        "https://example-news.test/novosti/": LIST_HTML,
        "https://example-news.test/press/": "<html></html>",
        "https://example-news.test/media/": "<html></html>",
    }

    def fake_fetch(url: str, **kwargs):
        # normalize trailing
        u = url if url in pages else (url.rstrip("/") + "/")
        html = pages.get(url) or pages.get(u)
        if html is None:
            return "<html></html>", None
        return html, None

    monkeypatch.setattr(discover, "fetch_html_safe", fake_fetch)
    monkeypatch.setattr(engine, "fetch_html_safe", fake_fetch)

    rules = heuristic_rules("https://example-news.test/", HOME_HTML, ["https://example-news.test/news/"])
    assert rules is not None
    assert "news" in rules.list_url or rules.list.article_link_selector

def test_discover_rejects_non_oilgas(monkeypatch) -> None:
    import gartner.custom_sources.discover as discover

    monkeypatch.setattr(
        discover,
        "inspect_domain",
        lambda url, llm=None: {
            "start_url": url,
            "domain": "shop.example",
            "theme": {"theme": "other", "accepted": False, "reason": "нет нефтегаза"},
            "protection": "none",
            "feeds": [],
            "candidates": [],
            "home_ok": True,
            "home_error": None,
        },
    )
    from gartner.custom_sources.discover import discover_and_validate

    class Dummy:
        enabled = True

    try:
        discover_and_validate("https://shop.example/", Dummy())  # type: ignore[arg-type]
        raise AssertionError("должен быть RuntimeError")
    except RuntimeError as exc:
        assert "тематик" in str(exc).lower() or "нефтегаз" in str(exc).lower()


def test_discover_heuristic_without_llm(monkeypatch) -> None:
    import gartner.custom_sources.discover as discover
    import gartner.custom_sources.engine as engine
    from gartner.custom_sources.discover import discover_and_validate
    from tests.fixtures_custom_sources import ARTICLE_HTML, HOME_HTML, LIST_HTML, LIST_HTML_PAGE2

    pages = {
        "https://example-news.test/": HOME_HTML,
        "https://example-news.test/news/": LIST_HTML,
        "https://example-news.test/news?page=2": LIST_HTML_PAGE2,
        "https://example-news.test/news/one": ARTICLE_HTML,
        "https://example-news.test/news/two": ARTICLE_HTML,
        "https://example-news.test/news/three": ARTICLE_HTML,
    }

    def fake_fetch(url: str, **kwargs):
        html = pages.get(url) or pages.get(url.rstrip("/") + "/")
        if html is None:
            return "<html></html>", None
        return html, None

    monkeypatch.setattr(discover, "fetch_html_safe", fake_fetch)
    monkeypatch.setattr(engine, "fetch_html_safe", fake_fetch)
    monkeypatch.setattr(
        discover,
        "inspect_domain",
        lambda url, llm=None, probe_feeds=True: {
            "start_url": url,
            "domain": "example-news.test",
            "theme": {"theme": "oilgas", "accepted": True, "reason": "fixture"},
            "protection": "none",
            "feeds": [{"url": "https://example-news.test/news/", "score": 8, "ok": True}],
            "candidates": [],
            "home_ok": True,
            "home_error": None,
        },
    )

    class Off:
        enabled = False

    rules, probe = discover_and_validate("https://example-news.test/", Off())  # type: ignore[arg-type]
    assert probe["method"] == "heuristic_no_llm"
    assert probe["articles"] >= 1
    assert "news" in rules.list_url
