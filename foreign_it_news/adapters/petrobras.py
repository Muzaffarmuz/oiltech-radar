"""Petrobras Agência — ленты mais-recentes / inovacao / home."""

from __future__ import annotations

import re
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from .base import ListItem, fetch_html

LIST_URLS = [
    "https://agencia.petrobras.com.br/en",
    "https://agencia.petrobras.com.br/en/mais-recentes",
    "https://agencia.petrobras.com.br/en/inovacao",
    "https://agencia.petrobras.com.br/en/negocio",
]
ARTICLE_RE = re.compile(r"agencia\.petrobras\.com\.br/w/[a-z0-9\-%]+/.+", re.I)


def _collect(url: str) -> list[ListItem]:
    html, _ = fetch_html(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: list[ListItem] = []
    for a in soup.find_all("a", href=True):
        full = urljoin(url, a["href"]).split("#")[0]
        if not ARTICLE_RE.search(full):
            continue
        # skip video_e_fotos style assets if obvious
        path = unquote(full).lower()
        if "video_e_fotos" in path or path.endswith((".jpg", ".png", ".pdf", ".mp4")):
            continue
        title = a.get_text(" ", strip=True)
        out.append(ListItem(url=full, title=title))
    return out


def list_articles() -> list[ListItem]:
    items: list[ListItem] = []
    for u in LIST_URLS:
        items.extend(_collect(u))
    seen: set[str] = set()
    out: list[ListItem] = []
    for it in items:
        key = unquote(it.url).rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out
