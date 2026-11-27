"""Тесты сервиса custom sources (БД + discover mock)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gartner.custom_sources import service
from gartner.custom_sources.engine import ArticleRecord
from gartner.custom_sources.rules import validate_rules_dict
from gartner.db import connect, init_db
from tests.fixtures_custom_sources import ARTICLE_HTML, LIST_HTML, VALID_RULES


def _fake_discovered(url: str = "https://example-news.test/") -> dict:
    return {
        "engine": "crawl_trafilatura",
        "version": 2,
        "start_url": url,
        "domain": "example-news.test",
        "theme": {"theme": "oilgas", "accepted": True, "reason": "fixture"},
        "protection": "none",
        "home_ok": True,
        "hubs": [{"url": "https://example-news.test/news/", "score": 8, "kind": "hub", "ok": True}],
        "article_candidates": [
            {"url": "https://example-news.test/news/one", "score": 6, "kind": "article", "ok": True}
        ],
        "rss_items": [],
        "pages_fetched": 2,
        "needs_browser": False,
    }


def _fake_articles() -> list[ArticleRecord]:
    return [
        ArticleRecord(
            title="Цифровой двойник месторождения",
            text="Компания внедрила цифровой двойник для оптимизации добычи на промысле и снизила простои.",
            datatime="2026-03-15",
            source="example-news.test",
            link="https://example-news.test/news/one",
        )
    ]


class FakeLLM:
    enabled = True

    def __init__(self, rules: dict | None = None) -> None:
        self.rules = rules or VALID_RULES
        self.calls = 0

    def json_call(self, prompt: str, payload: dict) -> dict:
        self.calls += 1
        return dict(self.rules)


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("gartner.db.DB_PATH", db_path)
    monkeypatch.setattr("gartner.config.DB_PATH", db_path)
    # service uses connect() which uses DB_PATH from gartner.db
    init_db(db_path)
    return db_path


def test_add_list_delete_custom_source(isolated_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("gartner.custom_sources.service.RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr("gartner.custom_sources.service.discover_source", lambda url, **kw: _fake_discovered(url))
    monkeypatch.setattr(
        "gartner.custom_sources.service.scrape_discovered",
        lambda discovered, max_articles=8, use_browser=None, **kw: (
            _fake_articles(),
            {"links_found": 2, "pages_fetched": 1, "browser": False},
        ),
    )
    llm = FakeLLM(VALID_RULES)
    item = service.add_custom_source("https://example-news.test/", llm=llm)
    assert item["domain"] == "example-news.test"
    assert item["status"] == "ready"
    assert item["probe"]["articles"] >= 1
    assert item["probe"]["method"] == "crawl_trafilatura"

    items = service.list_custom_sources()
    assert len(items) == 1
    assert items[0]["source_id"] == item["source_id"]

    with pytest.raises(ValueError, match="уже добавлен"):
        service.add_custom_source("https://www.example-news.test/other", llm=llm)

    assert service.set_custom_source_enabled(item["source_id"], False) is True
    assert service.list_custom_sources()[0]["enabled"] is False
    assert service.set_custom_source_enabled(item["source_id"], True) is True

    assert service.delete_custom_source(item["source_id"]) is True
    assert service.list_custom_sources() == []


def test_scrape_all_writes_raw(isolated_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw_dir = tmp_path / "raw"
    monkeypatch.setattr("gartner.custom_sources.service.RAW_DIR", raw_dir)
    monkeypatch.setattr(
        "gartner.custom_sources.engine.fetch_html_safe",
        lambda url, **kw: (
            LIST_HTML if url.rstrip("/").endswith("/news") or url.endswith("/news/") else ARTICLE_HTML,
            None,
        ),
    )

    rules = validate_rules_dict(VALID_RULES)
    init_db(isolated_db)
    with connect(isolated_db) as conn:
        conn.execute(
            """
            INSERT INTO custom_sources(
              source_id, domain, start_url, list_url, rules_json, status,
              last_error, last_probe_json, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'ready', NULL, '{}', 1, 't', 't')
            """,
            (
                "custom_example_1",
                "example-news.test",
                "https://example-news.test/",
                rules.list_url,
                json.dumps(rules.model_dump(), ensure_ascii=False),
            ),
        )

    class DisabledLLM:
        enabled = False

    report = service.scrape_all_custom_sources(llm=DisabledLLM())  # type: ignore[arg-type]
    assert report["ok_sources"] == 1
    assert (raw_dir / "custom_example_1.json").exists()
    data = json.loads((raw_dir / "custom_example_1.json").read_text(encoding="utf-8"))
    assert data[0]["title"]
    assert data[0]["link"]
    assert data[0]["source"] == "example-news.test"


def test_add_works_without_llm(isolated_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Off:
        enabled = False

    monkeypatch.setattr("gartner.custom_sources.service.RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr("gartner.custom_sources.service.discover_source", lambda url, **kw: _fake_discovered(url))
    monkeypatch.setattr(
        "gartner.custom_sources.service.scrape_discovered",
        lambda discovered, max_articles=8, use_browser=None, **kw: (
            _fake_articles(),
            {"links_found": 1, "pages_fetched": 1, "browser": False},
        ),
    )
    item = service.add_custom_source("https://example-news.test/", llm=Off())  # type: ignore[arg-type]
    assert item["status"] == "ready"
    assert item["engine"] == "crawl_trafilatura"
