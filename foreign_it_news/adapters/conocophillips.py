"""ConocoPhillips — story listing + archive."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import ListItem, fetch_html

STORY = "https://www.conocophillips.com/news-media/story/"
ARCHIVE = "https://www.conocophillips.com/news-media/archive/"
ARTICLE_RE = re.compile(r"/news-media/story/[a-z0-9\-]+/?$", re.I)


def _collect(url: str) -> list[ListItem]:
    html, _ = fetch_html(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: list[ListItem] = []
    for a in soup.find_all("a", href=True):
        full = urljoin(url, a["href"]).split("#")[0]
        if not ARTICLE_RE.search(full.rstrip("/")):
            continue
        # skip index itself
        if full.rstrip("/").endswith("/story"):
            continue
        title = a.get_text(" ", strip=True)
        out.append(ListItem(url=full if full.endswith("/") else full + "/", title=title))
    return out


def list_articles() -> list[ListItem]:
    items = _collect(STORY) + _collect(ARCHIVE)
    seen: set[str] = set()
    out: list[ListItem] = []
    for it in items:
        key = it.url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out
