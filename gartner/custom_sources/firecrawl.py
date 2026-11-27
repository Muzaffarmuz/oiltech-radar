"""Firecrawl — запасной загрузчик универсального парсера.

Активен только внутри `firecrawl_fallback()`: пайплайн входит в этот режим,
когда обычный прогон по сайту ничего не дал. Данные статей не помечаются.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import requests

from gartner.config import get_settings
from gartner.custom_sources.article_extract import polish_title
from gartner.custom_sources.engine import ArticleRecord, infer_date_from_url, parse_date_any
from gartner.custom_sources.scoring import news_score

log = logging.getLogger(__name__)

CLOUD_API_URL = "https://api.firecrawl.dev"
MIN_TEXT_CHARS = 200

# robots / sitemap / RSS отдаём обычному fetch: Firecrawl там ничего не добавит
_MACHINE_SUFFIXES = (".xml", ".rss", ".atom", "robots.txt")
_MACHINE_SEGMENTS = {"rss", "feed", "atom"}


@dataclass
class _Session:
    max_pages: int
    used: int = 0
    cache: dict[str, dict[str, Any] | None] = field(default_factory=dict)


_ACTIVE: ContextVar[_Session | None] = ContextVar("firecrawl_session", default=None)


def _config() -> Any:
    return get_settings()


def _base_url() -> str:
    cfg = _config()
    url = (cfg.firecrawl_api_url or "").strip().rstrip("/")
    if url:
        return url
    return CLOUD_API_URL if (cfg.firecrawl_api_key or "").strip() else ""


def firecrawl_enabled() -> bool:
    return bool(_base_url())


def firecrawl_active() -> bool:
    return _ACTIVE.get() is not None


@contextmanager
def firecrawl_fallback() -> Iterator[None]:
    """Режим «загружать через Firecrawl» на время запасного прогона."""
    token = _ACTIVE.set(_Session(max_pages=max(1, int(_config().firecrawl_max_pages))))
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def is_machine_url(url: str) -> bool:
    path = (urlparse(url).path or "").lower().rstrip("/")
    if path.endswith(_MACHINE_SUFFIXES):
        return True
    return any(seg in _MACHINE_SEGMENTS for seg in path.split("/"))


def _post_scrape(url: str) -> dict[str, Any] | None:
    cfg = _config()
    timeout_ms = max(1000, int(cfg.firecrawl_timeout_ms))
    headers = {"Content-Type": "application/json"}
    key = (cfg.firecrawl_api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    response = requests.post(
        f"{_base_url()}/v2/scrape",
        json={
            "url": url,
            "formats": ["rawHtml", "markdown"],
            "onlyMainContent": True,
            "timeout": timeout_ms,
        },
        headers=headers,
        timeout=timeout_ms / 1000 + 15,
    )
    response.raise_for_status()
    body = response.json()
    if not body.get("success"):
        raise RuntimeError(str(body.get("error") or "firecrawl: success=false"))
    data = body.get("data")
    return data if isinstance(data, dict) else None


def scrape_page(url: str) -> dict[str, Any] | None:
    """Документ Firecrawl для URL (кэш + лимит страниц в рамках запасного прогона)."""
    session = _ACTIVE.get()
    if session is None or not firecrawl_enabled():
        return None
    if url in session.cache:
        return session.cache[url]
    if session.used >= session.max_pages:
        return None
    session.used += 1
    try:
        doc = _post_scrape(url)
    except Exception as exc:  # noqa: BLE001
        log.info("firecrawl scrape failed %s: %s", url, exc)
        doc = None
    session.cache[url] = doc
    return doc


def fetch_html(url: str) -> tuple[str | None, str | None]:
    doc = scrape_page(url)
    if not doc:
        return None, "firecrawl: нет ответа"
    html = doc.get("rawHtml") or doc.get("html")
    if not html:
        return None, "firecrawl: пустой HTML"
    return str(html), None


_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_MARKUP = re.compile(r"(^|\s)#{1,6}\s|[*_`>|]+")


def markdown_to_text(markdown: str) -> str:
    text = _MD_IMAGE.sub(" ", markdown or "")
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_MARKUP.sub(" ", text)
    return " ".join(text.split())


def article_from_markdown(url: str, *, source_name: str) -> ArticleRecord | None:
    """Карточка из markdown Firecrawl, когда наш экстрактор не справился с его HTML."""
    if news_score(url) < -2:
        return None
    doc = scrape_page(url)
    if not doc:
        return None
    text = markdown_to_text(str(doc.get("markdown") or ""))
    if len(text) < MIN_TEXT_CHARS:
        return None
    meta = doc.get("metadata") or {}
    title = polish_title(str(meta.get("title") or meta.get("ogTitle") or ""), text)
    if not title:
        return None
    datatime = parse_date_any(str(meta.get("publishedTime") or "")) or infer_date_from_url(url)
    return ArticleRecord(
        title=title[:500],
        text=text[:50000],
        datatime=datatime or "",
        source=source_name,
        link=url,
    )
