"""Firecrawl как запасной загрузчик универсального парсера."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from gartner.custom_sources import fetch as fetch_mod
from gartner.custom_sources import firecrawl
from gartner.custom_sources import pipeline
from gartner.custom_sources.engine import ArticleRecord

ARTICLE_TEXT = "Добыча нефти на месторождении выросла. " * 12


def _cfg(url: str = "http://fc.local:3002", key: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        firecrawl_api_url=url,
        firecrawl_api_key=key,
        firecrawl_timeout_ms=45000,
        firecrawl_max_pages=3,
    )


@pytest.fixture
def fc_on(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(firecrawl, "_config", lambda: _cfg())

    def fake_post(url: str) -> dict[str, Any]:
        calls.append(url)
        return {
            "rawHtml": f"<html><body><h1>FC</h1><p>{url}</p></body></html>",
            "markdown": f"# Заголовок новости\n\n![img](x.png) [ссылка](/a) {ARTICLE_TEXT}",
            "metadata": {"title": "Рост добычи нефти", "publishedTime": "2026-11-01T10:00:00Z"},
        }

    monkeypatch.setattr(firecrawl, "_post_scrape", fake_post)
    return calls


def _rec(link: str = "https://site.ru/news/1") -> ArticleRecord:
    return ArticleRecord(title="T", text=ARTICLE_TEXT, datatime="2026-11-01", source="site.ru", link=link)


def test_disabled_without_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(firecrawl, "_config", lambda: _cfg(url="", key=""))
    assert not firecrawl.firecrawl_enabled()


def test_cloud_url_from_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(firecrawl, "_config", lambda: _cfg(url="", key="fc-123"))
    assert firecrawl._base_url() == firecrawl.CLOUD_API_URL


def test_fetch_uses_firecrawl_only_inside_fallback(
    monkeypatch: pytest.MonkeyPatch, fc_on: list[str]
) -> None:
    monkeypatch.setattr(fetch_mod, "fetch_html", lambda url, **_: "<html>local</html>")

    html, _ = fetch_mod.fetch_html_safe("https://site.ru/news/")
    assert html == "<html>local</html>"
    assert fc_on == []

    with firecrawl.firecrawl_fallback():
        html, _ = fetch_mod.fetch_html_safe("https://site.ru/news/")
        robots, _ = fetch_mod.fetch_html_safe("https://site.ru/robots.txt")
    assert "FC" in (html or "")
    assert robots == "<html>local</html>"
    assert fc_on == ["https://site.ru/news/"]


def test_page_budget_and_cache(monkeypatch: pytest.MonkeyPatch, fc_on: list[str]) -> None:
    monkeypatch.setattr(fetch_mod, "fetch_html", lambda url, **_: "<html>local</html>")
    with firecrawl.firecrawl_fallback():
        for i in range(5):
            fetch_mod.fetch_html_safe(f"https://site.ru/news/{i}")
        fetch_mod.fetch_html_safe("https://site.ru/news/0")
    assert len(fc_on) == 3


def test_no_fallback_when_local_found_articles(
    monkeypatch: pytest.MonkeyPatch, fc_on: list[str]
) -> None:
    def once(discovered: dict[str, Any], **_: Any):
        return [_rec()], {"articles": 1}

    monkeypatch.setattr(pipeline, "_scrape_discovered_once", once)
    articles, _ = pipeline.scrape_discovered({"start_url": "https://site.ru"})
    assert len(articles) == 1
    assert fc_on == []


def test_fallback_when_local_empty(monkeypatch: pytest.MonkeyPatch, fc_on: list[str]) -> None:
    modes: list[bool] = []

    def once(discovered: dict[str, Any], **_: Any):
        active = firecrawl.firecrawl_active()
        modes.append(active)
        return ([_rec()] if active else []), {"articles": int(active)}

    monkeypatch.setattr(pipeline, "_scrape_discovered_once", once)
    articles, stats = pipeline.scrape_discovered({"start_url": "https://site.ru"})
    assert modes == [False, True]
    assert len(articles) == 1
    assert set(articles[0].as_dict()) == {"title", "text", "datatime", "source", "link"}
    assert stats == {"articles": 1}
    assert not firecrawl.firecrawl_active()


def test_discover_retries_when_site_not_loaded(
    monkeypatch: pytest.MonkeyPatch, fc_on: list[str]
) -> None:
    def crawl(url: str, **_: Any) -> dict[str, Any]:
        if firecrawl.firecrawl_active():
            return {
                "start_url": url,
                "home_ok": True,
                "theme": {"accepted": True},
                "hubs": [{"url": url}],
                "article_candidates": [],
                "rss_items": [],
                "protection": "none",
            }
        return {"start_url": url, "home_ok": False, "theme": {"theme": "unknown", "accepted": False}}

    monkeypatch.setattr(pipeline, "crawl_domain", crawl)
    discovered = pipeline.discover_source("https://site.ru")
    assert discovered["home_ok"] is True
    assert "firecrawl" not in str(discovered).lower()


def test_discover_keeps_real_theme_reject(monkeypatch: pytest.MonkeyPatch, fc_on: list[str]) -> None:
    calls: list[bool] = []

    def crawl(url: str, **_: Any) -> dict[str, Any]:
        calls.append(firecrawl.firecrawl_active())
        return {
            "start_url": url,
            "home_ok": True,
            "theme": {"theme": "other", "accepted": False},
            "hubs": [{"url": url}],
            "protection": "none",
            "needs_browser": False,
        }

    monkeypatch.setattr(pipeline, "crawl_domain", crawl)
    pipeline.discover_source("https://shop.ru")
    assert calls == [False]


def test_article_from_markdown(fc_on: list[str]) -> None:
    with firecrawl.firecrawl_fallback():
        rec = firecrawl.article_from_markdown("https://site.ru/news/2026/11/01/x", source_name="site.ru")
    assert rec is not None
    assert rec.title
    assert "![" not in rec.text and "](" not in rec.text
    assert rec.datatime.startswith("2026-11-01")
    assert rec.source == "site.ru"
