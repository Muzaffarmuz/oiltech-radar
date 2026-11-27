"""Chevron — лента из sitemap + newsroom HTML."""

from __future__ import annotations

import re

from .base import ListItem, extract_hrefs, fetch_html, sitemap_locs

SITEMAP = "https://www.chevron.com/sitemap.xml"
NEWSROOM = "https://www.chevron.com/newsroom"
ARTICLE_RE = r"https://www\.chevron\.com/newsroom/2026/q[1-4]/[a-z0-9\-/]+"


def list_articles() -> list[ListItem]:
    items: list[ListItem] = []

    xml, _ = fetch_html(SITEMAP)
    if xml:
        for loc in sitemap_locs(xml):
            if re.search(r"/newsroom/2026/q[1-4]/", loc, re.I):
                low = loc.lower()
                if any(x in low for x in (".jpg", ".png", ".mp4", "thumbnail", "-nr", "video-thumbnail")):
                    continue
                items.append(ListItem(url=loc.rstrip("/")))

    html, _ = fetch_html(NEWSROOM)
    if html:
        for url in extract_hrefs(html, NEWSROOM, ARTICLE_RE):
            items.append(ListItem(url=url.rstrip("/")))

    seen: set[str] = set()
    out: list[ListItem] = []
    for it in items:
        key = it.url.rstrip("/").lower()
        if key in seen:
            continue
        if not re.search(r"/newsroom/2026/q[1-4]/[a-z0-9\-]+", key):
            continue
        seen.add(key)
        out.append(ListItem(url=it.url.rstrip("/")))
    return out
