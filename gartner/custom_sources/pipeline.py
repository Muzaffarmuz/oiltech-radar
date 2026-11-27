"""Домен → краул → статьи (trafilatura). Основной контур 3.2."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from gartner.custom_sources.article_extract import extract_article_page, extract_probe_dict, polish_title
from gartner.custom_sources.browser import maybe_browser_html, playwright_available
from gartner.custom_sources.crawl import (
    classify_page,
    crawl_domain,
    extract_hrefs,
    find_next_href,
    html_has_load_more,
    html_looks_js_heavy,
    resolve_page_kind,
)
from gartner.custom_sources.llm_gates import LlmBudget, has_article_query, judge_article_keep, polish_title_llm
from gartner.custom_sources.engine import ArticleRecord, parse_date_any
from gartner.custom_sources.fetch import fetch_html_safe
from gartner.custom_sources.firecrawl import (
    article_from_markdown,
    firecrawl_active,
    firecrawl_enabled,
    firecrawl_fallback,
)
from gartner.custom_sources.rules import domain_from_url, normalize_start_url
from gartner.custom_sources.scoring import looks_like_article_url, news_score, same_site


def _discovery_failed(discovered: dict[str, Any]) -> bool:
    if not discovered.get("home_ok"):
        return True
    if not (discovered.get("hubs") or discovered.get("article_candidates") or discovered.get("rss_items")):
        return True
    theme = discovered.get("theme") or {}
    blocked = discovered.get("needs_browser") or (discovered.get("protection") or "none") != "none"
    # отказ по тематике на JS-оболочке / за защитой — это «не увидели сайт», а не «чужой сайт»
    return not theme.get("accepted") and bool(blocked)


def _discovery_rank(discovered: dict[str, Any]) -> tuple[int, int, int]:
    theme = discovered.get("theme") or {}
    found = (
        len(discovered.get("article_candidates") or [])
        + len(discovered.get("rss_items") or [])
        + len(discovered.get("hubs") or [])
    )
    return (int(bool(discovered.get("home_ok"))), int(bool(theme.get("accepted"))), found)


def discover_source(
    start_url: str,
    *,
    llm: Any | None = None,
    budget: LlmBudget | None = None,
) -> dict[str, Any]:
    url = normalize_start_url(start_url)
    discovered = crawl_domain(url, llm=llm, budget=budget)
    if not _discovery_failed(discovered) or not firecrawl_enabled() or firecrawl_active():
        return discovered
    with firecrawl_fallback():
        retry = crawl_domain(url, llm=llm, budget=budget)
    return retry if _discovery_rank(retry) > _discovery_rank(discovered) else discovered


def _apply_llm_gates(
    rec: ArticleRecord,
    *,
    llm: Any | None,
    budget: LlmBudget,
) -> ArticleRecord | None:
    if llm is None:
        return rec
    new_title = polish_title_llm(llm, title=rec.title, text=rec.text, url=rec.link, budget=budget)
    if new_title:
        rec.title = new_title
        budget.used["title_fixed"] = budget.used.get("title_fixed", 0) + 1
    keep = judge_article_keep(llm, url=rec.link, title=rec.title, text=rec.text, budget=budget)
    if keep is False:
        return None
    return rec


def _hub_article_links(html: str, hub_url: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    weak: list[str] = []
    for href, label in extract_hrefs(html, hub_url):
        if not same_site(href, hub_url):
            continue
        score = news_score(href, label)
        articleish = looks_like_article_url(href)
        key = href.rstrip("/").lower()
        if key in seen:
            continue
        if score > 0 and (articleish or score >= 4):
            seen.add(key)
            found.append(href)
        elif articleish or score >= 2:
            # запасной пул: /press-tsentr/.../slug без явных id
            weak.append(href)
    if len(found) < 3:
        for href in weak:
            key = href.rstrip("/").lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(href)
            if len(found) >= 80:
                break
    return found


def _expand_hub_html(
    hub_url: str,
    html: str | None,
    *,
    use_browser: bool,
    max_hub_pages: int = 4,
) -> tuple[str | None, int]:
    pages = 1
    current_html = html
    current_url = hub_url
    if use_browser and (html_looks_js_heavy(html or "") or html_has_load_more(html or "")):
        current_html, meta = maybe_browser_html(hub_url, html, force=playwright_available())
        if not current_html:
            current_html = html
        _ = meta
    combined_links = list(_hub_article_links(current_html or "", hub_url))
    next_url = find_next_href(current_html or "", current_url) if current_html else None
    while next_url and pages < max_hub_pages:
        nxt_html, err = fetch_html_safe(next_url)
        if err or not nxt_html:
            break
        pages += 1
        extra = _hub_article_links(nxt_html, next_url)
        before = len(combined_links)
        for u in extra:
            if u not in combined_links:
                combined_links.append(u)
        if len(combined_links) == before:
            break
        next_url = find_next_href(nxt_html, next_url)
        current_html = nxt_html
    return current_html, pages


def _record_from_rss(item: dict[str, str], source: str, start_url: str) -> ArticleRecord | None:
    link = item.get("link") or ""
    try:
        link = urljoin(start_url, link)
        if not same_site(link, start_url):
            return None
    except Exception:
        return None
    text = " ".join((item.get("text") or "").split())
    title = polish_title(item.get("title") or "", text or item.get("title") or "")
    if len(text) < 200:
        return None
    if news_score(link, title) < 0:
        return None
    return ArticleRecord(
        title=title[:500],
        text=text[:50000],
        datatime=parse_date_any(item.get("date") or ""),
        source=source,
        link=link,
    )


def _extract_with_fallback(html: str, link: str, source: str) -> ArticleRecord | None:
    rec = extract_article_page(html, link, source_name=source)
    if rec is None and firecrawl_active():
        rec = article_from_markdown(link, source_name=source)
    return rec


def scrape_discovered(
    discovered: dict[str, Any],
    *,
    max_articles: int = 12,
    use_browser: bool | None = None,
    llm: Any | None = None,
    budget: LlmBudget | None = None,
    max_hub_pages: int = 4,
    force_browser: bool = False,
) -> tuple[list[ArticleRecord], dict[str, Any]]:
    """Сбор статей по профилю; если наш проход пуст — повтор через Firecrawl."""
    budget = budget or LlmBudget()
    kwargs = {
        "max_articles": max_articles,
        "use_browser": use_browser,
        "llm": llm,
        "budget": budget,
        "max_hub_pages": max_hub_pages,
        "force_browser": force_browser,
    }
    articles, stats = _scrape_discovered_once(discovered, **kwargs)
    if articles or not firecrawl_enabled() or firecrawl_active():
        return articles, stats
    with firecrawl_fallback():
        fb_articles, fb_stats = _scrape_discovered_once(discovered, **kwargs)
    if fb_articles:
        return fb_articles, fb_stats
    return articles, stats


def _scrape_discovered_once(
    discovered: dict[str, Any],
    *,
    max_articles: int,
    use_browser: bool | None,
    llm: Any | None,
    budget: LlmBudget,
    max_hub_pages: int,
    force_browser: bool,
) -> tuple[list[ArticleRecord], dict[str, Any]]:
    start = discovered["start_url"]
    source = discovered.get("domain") or domain_from_url(start)
    if force_browser and playwright_available():
        use_browser = True
    elif use_browser is None:
        use_browser = bool(discovered.get("needs_browser")) and playwright_available()

    links: list[str] = []
    seen: set[str] = set()

    def add_link(u: str) -> None:
        key = u.rstrip("/").lower()
        if key in seen:
            return
        seen.add(key)
        links.append(u)

    for item in discovered.get("rss_items") or []:
        if item.get("link"):
            add_link(urljoin(start, item["link"]))

    for cand in discovered.get("article_candidates") or []:
        add_link(cand["url"])

    pages_fetched = 0
    hub_used: list[str] = []
    hubs = list(discovered.get("hubs") or [])
    if not hubs:
        hubs = [{"url": start}]
    for hub in hubs:
        hub_url = hub["url"]
        html, err = fetch_html_safe(hub_url)
        html, pages = _expand_hub_html(
            hub_url,
            html if not err else None,
            use_browser=use_browser,
            max_hub_pages=max_hub_pages,
        )
        pages_fetched += pages
        hub_used.append(hub_url)
        if html:
            for u in _hub_article_links(html, hub_url):
                add_link(u)
        if len(links) >= max_articles * 4:
            break

    articles: list[ArticleRecord] = []
    seen_text: set[str] = set()

    for item in discovered.get("rss_items") or []:
        rec = _record_from_rss(item, source, start)
        if rec:
            rec = _apply_llm_gates(rec, llm=llm, budget=budget)
        if rec:
            key = rec.text[:400]
            if key in seen_text:
                continue
            seen_text.add(key)
            articles.append(rec)
        if len(articles) >= max_articles:
            break

    for link in links:
        if len(articles) >= max_articles:
            break
        if not same_site(link, start):
            continue
        if classify_page(link, "") == "other" and news_score(link) <= 0:
            continue
        html, err = fetch_html_safe(link)
        if err or not html:
            continue
        kind = resolve_page_kind(link, html, llm=llm, budget=budget)
        if kind != "article" and not (
            kind == "hub" and (has_article_query(link) or looks_like_article_url(link))
        ):
            continue
        rec = _extract_with_fallback(html, link, source)
        if not rec:
            continue
        rec = _apply_llm_gates(rec, llm=llm, budget=budget)
        if not rec:
            continue
        key = rec.text[:400]
        if key in seen_text:
            continue
        seen_text.add(key)
        articles.append(rec)

    # Пустой хаб при обычном HTTP → один проход Playwright (JS-ленты вроде tatneft)
    if not articles and not use_browser and playwright_available() and hubs:
        for hub in hubs[:2]:
            hub_url = hub.get("url") or start
            html, meta = maybe_browser_html(hub_url, None, force=True)
            pages_fetched += 1
            use_browser = True
            if html:
                for u in _hub_article_links(html, hub_url):
                    add_link(u)
            _ = meta
        for link in links:
            if len(articles) >= max_articles:
                break
            if not same_site(link, start):
                continue
            html, err = fetch_html_safe(link)
            if err or not html:
                html, _meta = maybe_browser_html(link, None, force=True)
            if not html:
                continue
            kind = resolve_page_kind(link, html, llm=llm, budget=budget)
            if kind != "article" and not (
                kind == "hub" and (has_article_query(link) or looks_like_article_url(link))
            ):
                continue
            rec = _extract_with_fallback(html, link, source)
            if not rec:
                continue
            rec = _apply_llm_gates(rec, llm=llm, budget=budget)
            if not rec:
                continue
            key = rec.text[:400]
            if key in seen_text:
                continue
            seen_text.add(key)
            articles.append(rec)

    stats = {
        "links_found": len(links),
        "pages_fetched": pages_fetched,
        "hubs_used": hub_used,
        "browser": use_browser,
        "articles": len(articles),
        "llm_stats": budget.as_dict(),
    }
    return articles, stats


def scrape_profile(
    profile: dict[str, Any],
    *,
    max_articles: int = 40,
    llm: Any | None = None,
    budget: LlmBudget | None = None,
    max_hub_pages: int = 4,
) -> tuple[list[ArticleRecord], dict[str, Any]]:
    return scrape_discovered(
        profile,
        max_articles=max_articles,
        llm=llm,
        budget=budget,
        max_hub_pages=max_hub_pages,
    )
