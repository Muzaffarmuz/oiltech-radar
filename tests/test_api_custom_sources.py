"""API-тесты custom sources."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gartner.db import init_db
from portal.app import app
from tests.fixtures_custom_sources import ARTICLE_HTML, HOME_HTML, LIST_HTML, VALID_RULES


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db_path = tmp_path / "api.db"
    monkeypatch.setattr("gartner.db.DB_PATH", db_path)
    monkeypatch.setattr("gartner.config.DB_PATH", db_path)
    init_db(db_path)
    monkeypatch.setattr("gartner.custom_sources.service.RAW_DIR", tmp_path / "raw")

    class FakeLLM:
        enabled = True

        def json_call(self, prompt: str, payload: dict) -> dict:
            return dict(VALID_RULES)

    monkeypatch.setattr("gartner.llm.LLMClient", lambda settings=None: FakeLLM())
    monkeypatch.setattr(
        "gartner.custom_sources.service.discover_source",
        lambda url, **kw: {
            "engine": "crawl_trafilatura",
            "version": 2,
            "start_url": "https://example-news.test/",
            "domain": "example-news.test",
            "theme": {"theme": "oilgas", "accepted": True, "reason": "fixture"},
            "protection": "none",
            "hubs": [{"url": "https://example-news.test/news/", "score": 8, "kind": "hub", "ok": True}],
            "article_candidates": [{"url": "https://example-news.test/news/one", "score": 6, "kind": "article", "ok": True}],
            "rss_items": [],
            "home_ok": True,
            "pages_fetched": 2,
            "needs_browser": False,
        },
    )
    from gartner.custom_sources.engine import ArticleRecord

    monkeypatch.setattr(
        "gartner.custom_sources.service.scrape_discovered",
        lambda discovered, max_articles=8, use_browser=None, **kw: (
            [
                ArticleRecord(
                    title="Цифровой двойник месторождения",
                    text="Компания внедрила цифровой двойник для оптимизации добычи на промысле и снизила простои оборудования.",
                    datatime="2026-03-15",
                    source="example-news.test",
                    link="https://example-news.test/news/one",
                )
            ],
            {"links_found": 2, "pages_fetched": 1, "browser": False},
        ),
    )
    return TestClient(app)


def test_api_list_empty(client: TestClient) -> None:
    res = client.get("/api/custom-sources")
    assert res.status_code == 200
    assert res.json()["items"] == []


def test_api_add_toggle_delete(client: TestClient) -> None:
    res = client.post("/api/custom-sources", json={"url": "https://example-news.test"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    source_id = body["item"]["source_id"]

    listed = client.get("/api/custom-sources").json()["items"]
    assert len(listed) == 1

    bad = client.post("/api/custom-sources", json={"url": "https://example-news.test/news"})
    assert bad.status_code == 400

    tog = client.post(f"/api/custom-sources/{source_id}/enabled", json={"enabled": False})
    assert tog.status_code == 200
    assert client.get("/api/custom-sources").json()["items"][0]["enabled"] is False

    deleted = client.delete(f"/api/custom-sources/{source_id}")
    assert deleted.status_code == 200
    assert client.get("/api/custom-sources").json()["items"] == []


def test_api_add_rejects_localhost(client: TestClient) -> None:
    res = client.post("/api/custom-sources", json={"url": "http://127.0.0.1/news"})
    assert res.status_code in {400, 422, 500}
