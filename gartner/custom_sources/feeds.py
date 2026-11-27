"""Поиск обновляемых лент новостей на домене."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from gartner.custom_sources.fetch import _is_js_cookie_challenge, fetch_html_safe
from gartner.custom_sources.rules import domain_from_url, normalize_start_url

FEED_PATHS = (
    "/news/",
    "/novosti/",
    "/press/",
    "/press-center/",
    "/media/",
    "/rss.xml",
    "/feed/",
)

NEWS_HINTS = (
    "news",
    "novosti",
    "press",
    "media",
    "лента",
    "новост",
    "пресс",
    "аналит",
    "smi",
    "rss",
    "feed",
    "блог",
)


def _origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _same_site(candidate: str, base: str) -> bool:
    a = (urlparse(candidate).hostname or "").lower().lstrip("www.")
    b = (urlparse(base).hostname or "").lower().lstrip("www.")
    return bool(a) and (a == b or a.endswith("." + b) or b.endswith("." + a))


def extract_feed_candidates(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    found: list[str] = []
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        label = (a.get_text(" ", strip=True) or "").lower()
        abs_url = urljoin(base_url, href)
        if not _same_site(abs_url, base_url):
            continue
        blob = f"{href} {label}".lower()
        if any(k in blob for k in NEWS_HINTS):
            found.append(abs_url.split("#")[0])
    for link in soup.find_all("link", href=True):
        rel = " ".join(link.get("rel") or []).lower()
        typ = str(link.get("type") or "").lower()
        if "rss" in rel or "atom" in rel or "rss" in typ or "atom" in typ:
            found.append(urljoin(base_url, str(link.get("href"))))
    origin = _origin(base_url)
    # сначала ссылки с главной, потом типовые пути
    extras = [urljoin(origin + "/", path.lstrip("/")) for path in FEED_PATHS]
    out: list[str] = []
    seen: set[str] = set()
    for u in found + extras:
        key = u.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out[:20]


def looks_like_rss(html: str) -> bool:
    head = (html or "")[:400].lower()
    return "<rss" in head or "<feed" in head or "<rdf:rdf" in head


def _score_feed_html(html: str, url: str) -> int:
    if not html or _is_js_cookie_challenge(html):
        return 0
    if looks_like_rss(html):
        items = len(re.findall(r"<item[\s>]", html, re.I)) + len(re.findall(r"<entry[\s>]", html, re.I))
        return 50 + min(items, 40)
    soup = BeautifulSoup(html, "html.parser")
    links = soup.find_all("a", href=True)
    articleish = 0
    for a in links:
        href = str(a.get("href") or "")
        path = urlparse(urljoin(url, href)).path
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2 and any(k in path.lower() for k in ("news", "novosti", "press", "media", "article")):
            articleish += 1
    return min(articleish, 40)


def discover_feeds(start_url: str, *, max_probe: int = 5) -> dict[str, Any]:
    """Главная + типовые пути → список живых лент, отсортированных по числу ссылок."""
    url = normalize_start_url(start_url)
    home, err = fetch_html_safe(url)
    candidates = extract_feed_candidates(home or "", url)
    if url not in candidates:
        candidates.insert(0, url)

    probed: list[dict[str, Any]] = []
    seen: set[str] = set()
    # если главная не открылась — не долбим типовые /news (часто тот же timeout)
    probe_budget = max_probe if (home and not err) else min(2, max_probe)
    for cand in candidates[:probe_budget]:
        key = cand.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        html, ferr = fetch_html_safe(cand)
        score = _score_feed_html(html or "", cand) if html and not ferr else 0
        probed.append(
            {
                "url": cand,
                "ok": bool(html) and not ferr and not _is_js_cookie_challenge(html or ""),
                "score": score,
                "rss": looks_like_rss(html or "") if html else False,
                "error": ferr,
                "challenge": _is_js_cookie_challenge(html or "") if html else False,
                "bytes": len(html or ""),
            }
        )
    probed.sort(key=lambda x: (x["ok"], x["score"]), reverse=True)
    live = [p for p in probed if p["ok"] and p["score"] >= 2]
    return {
        "start_url": url,
        "domain": domain_from_url(url),
        "home_ok": bool(home) and not err,
        "home_error": err,
        "home_challenge": _is_js_cookie_challenge(home or "") if home else False,
        "candidates": probed,
        "feeds": live,
    }
