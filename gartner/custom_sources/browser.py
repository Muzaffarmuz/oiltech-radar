"""Playwright: добрать HTML хаба, если requests пустой или есть «ещё»."""

from __future__ import annotations

import threading
from typing import Any

from gartner.custom_sources.crawl import extract_hrefs
from gartner.custom_sources.scoring import looks_like_article_url, news_score

CLICK_LABELS = ("ещё", "еще", "показать ещё", "показать еще", "далее", "load more", "show more")

# sync Playwright нельзя вызывать из нескольких потоков сразу
_BROWSER_LOCK = threading.Lock()


def playwright_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401

        return True
    except ImportError:
        return False


def _article_link_count(html: str, url: str) -> int:
    n = 0
    for href, label in extract_hrefs(html, url):
        if news_score(href, label) > 0 and looks_like_article_url(href):
            n += 1
    return n


def fetch_html_browser(url: str, *, load_more_clicks: int = 4, timeout_ms: int = 20000) -> tuple[str | None, str | None]:
    if not playwright_available():
        return None, "playwright не установлен"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, "playwright не установлен"

    html = None
    err = None
    with _BROWSER_LOCK:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_default_timeout(timeout_ms)
                page.goto(url, wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                html = page.content()
                prev = _article_link_count(html, url)
                for _ in range(load_more_clicks):
                    clicked = False
                    for label in CLICK_LABELS:
                        loc = page.get_by_text(label, exact=False).first
                        try:
                            if loc.count() == 0:
                                continue
                            loc.click(timeout=2500)
                            clicked = True
                            page.wait_for_timeout(700)
                            break
                        except Exception:
                            continue
                    if not clicked:
                        break
                    html = page.content()
                    now = _article_link_count(html, url)
                    if now <= prev:
                        break
                    prev = now
                browser.close()
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
            html = html or None
    return html, err


def maybe_browser_html(url: str, html: str | None, *, force: bool = False) -> tuple[str | None, dict[str, Any]]:
    meta = {"used": False, "error": None}
    if not force:
        return html, meta
    fresh, err = fetch_html_browser(url)
    meta["used"] = True
    meta["error"] = err
    if fresh:
        return fresh, meta
    return html, meta
