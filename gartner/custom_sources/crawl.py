"""Локальный краул домена: sitemap, RSS, BFS, хабы и статьи."""

from __future__ import annotations

import re
from collections import deque
from typing import Any
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from gartner.custom_sources.fetch import _is_js_cookie_challenge, fetch_html_safe
from gartner.custom_sources.feeds import FEED_PATHS, looks_like_rss
from gartner.custom_sources.rules import domain_from_url, normalize_start_url
from gartner.custom_sources.llm_gates import LlmBudget, classify_kind_llm, has_article_query, is_ambiguous_kind, refine_theme_once
from gartner.custom_sources.scoring import looks_like_article_url, looks_like_hub_url, news_score, same_site
from gartner.custom_sources.theme import classify_theme

MAX_URLS = 45
MAX_DEPTH = 3

PAGER_HINTS = ("далее", "следующ", "показать ещё", "показать еще", "ещё", "еще", "load more", "show more")


def origin_of(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _abs(base: str, href: str) -> str | None:
    href = (href or "").strip()
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return None
    abs_url = urljoin(base, href).split("#")[0]
    parsed = urlparse(abs_url)
    if parsed.scheme not in {"http", "https"}:
        return None
    if not same_site(abs_url, base):
        return None
    return abs_url


def parse_sitemap_locs(xml_text: str) -> list[str]:
    if not xml_text:
        return []
    locs: list[str] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return re.findall(r"<loc>\s*([^<]+)\s*</loc>", xml_text, flags=re.I)
    for node in root.iter():
        tag = node.tag.split("}")[-1].lower()
        if tag == "loc" and node.text:
            locs.append(node.text.strip())
    return locs


def parse_rss_items(xml_text: str) -> list[dict[str, str]]:
    if not xml_text:
        return []
    items: list[dict[str, str]] = []
    soup = BeautifulSoup(xml_text, "html.parser")
    nodes = soup.find_all(["item", "entry"])
    # html.parser глотает <link>url</link> как пустой HTML-link — сразу regex
    blocks = re.findall(r"<(?:item|entry)\b[\s\S]*?</(?:item|entry)>", xml_text, flags=re.I)
    if blocks:
        for block in blocks:
            title_m = re.search(r"<title[^>]*>([\s\S]*?)</title>", block, flags=re.I)
            link_m = re.search(r"<link[^>]*>([\s\S]*?)</link>", block, flags=re.I)
            if not link_m:
                link_m = re.search(r'href="([^"]+)"', block)
            desc_m = re.search(r"<description[^>]*>([\s\S]*?)</description>", block, flags=re.I)
            items.append(
                {
                    "title": re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else "",
                    "link": re.sub(r"<[^>]+>", "", (link_m.group(1) if link_m else "")).strip(),
                    "date": "",
                    "text": re.sub(r"<[^>]+>", "", desc_m.group(1)).strip() if desc_m else "",
                }
            )
        return [x for x in items if x.get("link")]
    for item in nodes:
        title = ""
        link = ""
        date = ""
        text = ""
        if item.find("title"):
            title = item.find("title").get_text(" ", strip=True)
        link_el = item.find("link")
        if link_el:
            link = (link_el.get("href") or link_el.get_text(" ", strip=True) or "").strip()
        guid = item.find("guid")
        if not link and guid:
            link = guid.get_text(" ", strip=True)
        for dtag in ("pubDate", "published", "updated", "date"):
            node = item.find(dtag)
            if node:
                date = node.get_text(" ", strip=True)
                break
        body = item.find("content") or item.find("description") or item.find("summary")
        if body:
            text = body.get_text(" ", strip=True)
        if link:
            items.append({"title": title, "link": link, "date": date, "text": text})
    return items


def _sanitize_html(html: str) -> str:
    """Убрать NULs/бинарщину и битые &#… charref, из‑за которых html.parser падает."""
    if not html:
        return ""
    cleaned = "".join(ch if (ord(ch) >= 32 or ch in "\n\r\t") else " " for ch in html)

    def _fix_charref(match: re.Match[str]) -> str:
        body = match.group(1) or ""
        if body.isdigit() or (body.startswith("x") and all(c in "0123456789abcdefABCDEF" for c in body[1:])):
            return match.group(0)
        return " "

    return re.sub(r"&#([^\s;]{0,64});?", _fix_charref, cleaned)


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(_sanitize_html(html or ""), "html.parser")
    except (ValueError, TypeError):
        return BeautifulSoup("", "html.parser")


def extract_hrefs(html: str, base_url: str) -> list[tuple[str, str]]:
    soup = _soup(html)
    out: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        abs_url = _abs(base_url, str(a.get("href")))
        if not abs_url:
            continue
        label = a.get_text(" ", strip=True)
        out.append((abs_url, label))
    for link in soup.find_all("link", href=True):
        rel = " ".join(link.get("rel") or []).lower()
        typ = str(link.get("type") or "").lower()
        if "rss" in rel or "atom" in rel or "rss" in typ or "sitemap" in rel:
            abs_url = _abs(base_url, str(link.get("href")))
            if abs_url:
                out.append((abs_url, rel or typ))
    return out


def find_next_href(html: str, base_url: str) -> str | None:
    soup = _soup(html)
    node = soup.select_one("a[rel='next']")
    if node and node.get("href"):
        return _abs(base_url, str(node.get("href")))
    for a in soup.find_all("a", href=True):
        label = (a.get_text(" ", strip=True) or "").lower()
        if label in {"далее", "следующая", ">", "»", "next"}:
            return _abs(base_url, str(a.get("href")))
    return None


def html_looks_js_heavy(html: str) -> bool:
    if not html:
        return True
    if _is_js_cookie_challenge(html):
        return True
    soup = _soup(html)
    text = soup.get_text(" ", strip=True)
    scripts = html.lower().count("<script")
    return len(text) < 120 and scripts >= 8


def html_has_load_more(html: str) -> bool:
    blob = (html or "").lower()
    return any(h in blob for h in ("load-more", "show-more", "loadmore")) or any(
        h in blob for h in PAGER_HINTS[2:6]
    )


def articleish_count(html: str, url: str) -> int:
    hrefs = extract_hrefs(html or "", url)
    return sum(1 for u, lab in hrefs if news_score(u, lab) > 0 and looks_like_article_url(u))


def classify_page(url: str, html: str) -> str:
    if looks_like_rss(html or ""):
        return "rss"
    articleish_n = articleish_count(html, url)
    # Явный URL статьи важнее «много исходящих ссылок» (типично для статей с сайдбаром).
    if looks_like_article_url(url) and not looks_like_hub_url(url):
        return "article"
    if looks_like_article_url(url) and articleish_n < 4:
        return "article"
    if articleish_n >= 4 or looks_like_hub_url(url):
        return "hub"
    if news_score(url) > 0 and articleish_n >= 2:
        return "hub"
    return "other"


def resolve_page_kind(url: str, html: str, *, llm: Any | None = None, budget: LlmBudget | None = None) -> str:
    kind = classify_page(url, html)
    if llm is None or budget is None:
        return kind
    n = articleish_count(html, url)
    if not is_ambiguous_kind(url, heuristic=kind, articleish_n=n):
        return kind
    decided = classify_kind_llm(llm, url=url, html=html, heuristic=kind, articleish_n=n, budget=budget)
    if not decided:
        if has_article_query(url) and kind == "hub":
            return "article"
        return kind
    if has_article_query(url) and decided == "hub":
        return "article"
    if decided != kind:
        budget.used["kind_changed"] = budget.used.get("kind_changed", 0) + 1
    return decided


def guess_protection(html: str | None, err: str | None) -> str:
    if html and _is_js_cookie_challenge(html):
        return "js_cookie"
    msg = (err or "").lower()
    if "ssl" in msg or "certificate" in msg:
        return "tls_odd"
    if "timeout" in msg:
        return "timeout"
    if "403" in msg:
        return "http_403"
    if err:
        return "unknown"
    return "none"


def collect_seeds(start_url: str, home_html: str | None = None) -> list[str]:
    url = normalize_start_url(start_url)
    origin = origin_of(url)
    seeds = [url]
    robots, _ = fetch_html_safe(urljoin(origin + "/", "robots.txt"))
    if robots:
        for line in robots.splitlines():
            if line.lower().startswith("sitemap:"):
                sm = line.split(":", 1)[1].strip()
                if sm:
                    seeds.append(sm)
    if home_html:
        for href, label in extract_hrefs(home_html, url):
            if "rss" in f"{href} {label}".lower() or "atom" in f"{href} {label}".lower() or "sitemap" in href.lower():
                seeds.append(href)
    for path in ("/sitemap.xml",) + FEED_PATHS[:5]:
        seeds.append(urljoin(origin + "/", path.lstrip("/")))
    out: list[str] = []
    seen: set[str] = set()
    for s in seeds:
        key = s.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def crawl_domain(
    start_url: str,
    *,
    max_urls: int = MAX_URLS,
    max_depth: int = MAX_DEPTH,
    llm: Any | None = None,
    budget: LlmBudget | None = None,
) -> dict[str, Any]:
    url = normalize_start_url(start_url)
    domain = domain_from_url(url)
    budget = budget or LlmBudget()
    home_html, home_err = fetch_html_safe(url)
    seeds = collect_seeds(url, home_html)
    queue: deque[tuple[str, int]] = deque()
    visited: set[str] = set()
    pages: list[dict[str, Any]] = []
    rss_items: list[dict[str, str]] = []

    def enqueue(candidate: str, depth: int) -> None:
        key = candidate.rstrip("/").lower()
        if key in visited:
            return
        if any(q[0].rstrip("/").lower() == key for q in queue):
            return
        queue.append((candidate, depth))

    visited.add(url.rstrip("/").lower())
    if home_html and not home_err:
        kind = classify_page(url, home_html)
        pages.append(
            {
                "url": url,
                "ok": True,
                "error": None,
                "kind": kind,
                "score": news_score(url),
                "needs_browser": html_looks_js_heavy(home_html) or html_has_load_more(home_html),
                "bytes": len(home_html),
            }
        )
        if looks_like_rss(home_html):
            for item in parse_rss_items(home_html):
                if item.get("link") and same_site(item["link"], url):
                    rss_items.append(item)
        else:
            for href, label in extract_hrefs(home_html, url):
                if news_score(href, label) < 0:
                    continue
                enqueue(href, 1)
    else:
        pages.append({"url": url, "ok": False, "error": home_err, "kind": "fail", "score": 0})

    for seed in seeds:
        if seed.rstrip("/").lower() != url.rstrip("/").lower():
            enqueue(seed, 0)

    while queue and len(visited) < max_urls:
        current, depth = queue.popleft()
        key = current.rstrip("/").lower()
        if key in visited:
            continue
        visited.add(key)
        html, err = fetch_html_safe(current)
        if current.rstrip("/") == url.rstrip("/") or current.rstrip("/") == origin_of(url):
            home_html, home_err = html, err
        if err or not html:
            pages.append({"url": current, "ok": False, "error": err, "kind": "fail", "score": 0})
            continue
        kind = classify_page(current, html)
        score = news_score(current)
        needs_browser = html_looks_js_heavy(html) or (kind == "hub" and html_has_load_more(html))
        page = {
            "url": current,
            "ok": True,
            "error": None,
            "kind": kind,
            "score": score,
            "needs_browser": needs_browser,
            "bytes": len(html),
        }
        pages.append(page)
        if kind == "rss" or looks_like_rss(html):
            for item in parse_rss_items(html):
                if item.get("link") and same_site(item["link"], url):
                    rss_items.append(item)
            continue
        if current.lower().endswith(".xml") or "<urlset" in html[:500].lower() or "<sitemapindex" in html[:800].lower():
            for loc in parse_sitemap_locs(html)[:40]:
                if same_site(loc, url) and news_score(loc) >= 0:
                    enqueue(loc, depth + 1)
            continue
        if depth >= max_depth:
            continue
        for href, label in extract_hrefs(html, current):
            if news_score(href, label) < 0:
                continue
            enqueue(href, depth + 1)

    if home_html:
        theme = classify_theme(home_html, url=url, extra_text=url)
        host = domain.lower()
        if not theme.get("accepted") and any(
            token in host for token in ("neft", "gaz", "oil", "petro", "lukoil", "novatek")
        ):
            theme = {
                "theme": "oilgas",
                "hits": theme.get("hits") or 0,
                "accepted": True,
                "reason": "домен похож на нефтегаз",
                "method": "domain",
            }
        theme = refine_theme_once(llm, domain=domain, url=url, html=home_html, keyword_theme=theme, budget=budget)
    else:
        theme = {
            "theme": "unknown",
            "hits": 0,
            "accepted": False,
            "reason": f"страница не загрузилась: {home_err}",
            "method": "fetch_fail",
        }

    hubs = [p for p in pages if p.get("ok") and p.get("kind") == "hub" and (p.get("score") or 0) >= 0]
    hubs.sort(key=lambda p: p.get("score") or 0, reverse=True)
    if not hubs and home_html:
        hubs = [{"url": url, "score": news_score(url), "kind": "hub", "ok": True, "needs_browser": html_looks_js_heavy(home_html)}]
    articles = [p for p in pages if p.get("ok") and p.get("kind") == "article" and (p.get("score") or 0) > 0]
    articles.sort(key=lambda p: p.get("score") or 0, reverse=True)

    return {
        "engine": "crawl_trafilatura",
        "version": 2,
        "start_url": url,
        "domain": domain,
        "theme": theme,
        "protection": guess_protection(home_html, home_err),
        "home_ok": bool(home_html) and not home_err,
        "home_error": home_err,
        "hubs": hubs[:12],
        "article_candidates": articles[:40],
        "rss_items": rss_items[:40],
        "pages_fetched": len(visited),
        "needs_browser": any(p.get("needs_browser") for p in hubs[:5]),
        "llm_gates": bool(llm is not None and getattr(llm, "enabled", False)),
        "llm_stats": budget.as_dict(),
    }
