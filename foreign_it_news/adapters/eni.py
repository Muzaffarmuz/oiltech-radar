"""Eni — press releases 2026 из sitemap (+ media.html как запас)."""

from __future__ import annotations

import re

from .base import ListItem, extract_hrefs, fetch_html, sitemap_locs

SITEMAP = "https://www.eni.com/en-IT/sitemap.xml"
MEDIA = "https://www.eni.com/en-IT/media.html"
ARTICLE_RE = r"https://www\.eni\.com/en-IT/media/press-release/2026/\d{2}/[a-z0-9\-/]+\.html"


def _is_buyback_noise(url: str) -> bool:
    u = url.lower()
    return "buyback" in u or "treasury-shares" in u or "purchase-treasury" in u


def list_articles() -> list[ListItem]:
    items: list[ListItem] = []
    xml, _ = fetch_html(SITEMAP, timeout=45.0)
    if xml:
        for loc in sitemap_locs(xml):
            if re.search(r"/media/press-release/2026/\d{2}/", loc, re.I) and loc.endswith(".html"):
                if _is_buyback_noise(loc):
                    continue
                items.append(ListItem(url=loc))

    html, _ = fetch_html(MEDIA)
    if html:
        for url in extract_hrefs(html, MEDIA, ARTICLE_RE):
            if _is_buyback_noise(url):
                continue
            items.append(ListItem(url=url))

    seen: set[str] = set()
    out: list[ListItem] = []
    for it in items:
        key = it.url.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out
