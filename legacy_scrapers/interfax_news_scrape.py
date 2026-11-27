"""Ручной сбор новостей Интерфакса: https://www.interfax.ru/news/"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from manual_common import NewsItem, canonicalize_url, fetch, make_session, normalize_whitespace, parse_date, period_bounds, save_items, source_domain, text_from_selectors

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "manual_sources"
DEFAULT_BASE_URL = "https://www.interfax.ru/news/"
ARTICLE_RE = re.compile(r"^/[a-z0-9-]+/\d{5,}/?$", re.IGNORECASE)
DAY_RE = re.compile(r"/news/(\d{4})/(\d{2})/(\d{2})")

# Период сбора включительно, с точностью до дня. Формат YYYY-MM-DD.
# Пустая DATE_TO — по сегодняшний день.
# Аргументы --date-from и --date-to перекрывают эти значения.
DATE_FROM = "2025-10-14"
DATE_TO = ""
# Сколько новостей оставлять за один день. 0 — без ограничения.
# При 20 за день в месяце будет не больше 600, и каждый день попадёт в выборку.
MAX_PER_DAY = 20


def extract_links(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[str] = []
    seen: set[str] = set()
    for anchor in soup.select("a[href]"):
        href = anchor.get("href") or ""
        url = canonicalize_url(urljoin(page_url, href).split("#", 1)[0])
        path = urljoin(page_url, href)
        path_only = path.split("interfax.ru", 1)[-1]
        if "interfax.ru" not in url:
            continue
        match_path = "/" + url.split("interfax.ru/", 1)[-1]
        if not ARTICLE_RE.match(match_path.split("?", 1)[0]):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def page_day_from_url(url: str) -> date | None:
    match = DAY_RE.search(url)
    if not match:
        return None
    year, month, day = (int(match.group(i)) for i in (1, 2, 3))
    try:
        return date(year, month, day)
    except ValueError:
        return None


def previous_day(html: str, page_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.select("a.newsButton[href], a[href]"):
        text = normalize_whitespace(anchor.get_text(" ", strip=True)).lower()
        href = anchor.get("href") or ""
        if text == "назад" and "/news/" in href:
            return urljoin(page_url, href)
    return ""


def parse_article(session: requests.Session, url: str, timeout_s: int) -> tuple[str, str, str]:
    _status, html = fetch(session, url, timeout_s)
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.find("h1")
    title = normalize_whitespace(title_el.get_text(" ", strip=True) if title_el else "")
    time_el = soup.select_one("time") or soup.select_one(".time")
    datatime, _item_date = parse_date(time_el.get_text(" ", strip=True) if time_el else "")
    text = text_from_selectors(soup, "article p")
    return title, text, datatime


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape interfax.ru/news for a date range.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--date-from", default=DATE_FROM, help="Нижняя граница YYYY-MM-DD, включительно.")
    parser.add_argument("--date-to", default=DATE_TO, help="Верхняя граница YYYY-MM-DD, включительно. Пусто — сегодня.")
    parser.add_argument("--out-prefix", default=str(_DATA_DIR / "interfax_news"))
    parser.add_argument("--max-pages", type=int, default=40, help="Сколько дневных лент обойти назад.")
    parser.add_argument("--max-articles", type=int, default=0)
    parser.add_argument("--max-per-day", type=int, default=MAX_PER_DAY, help="Потолок новостей на один день. 0 — без ограничения.")
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--user-agent", default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) interfax_news_scrape/1.0")
    args = parser.parse_args()

    def log(message: str) -> None:
        if not args.quiet:
            print(message, file=sys.stderr)

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        date_from, date_to = period_bounds(args.date_from, args.date_to)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    source = source_domain(args.base_url)
    session = make_session(args.user_agent)
    results: list[NewsItem] = []
    seen: set[str] = set()
    day_counts: dict[date, int] = {}
    page_url = args.base_url

    for page_num in range(1, args.max_pages + 1):
        log(f"Page {page_num}: {page_url}")
        try:
            _status, html = fetch(session, page_url, args.timeout)
        except requests.RequestException as exc:
            if results:
                csv_path, json_path = save_items(results, args.out_prefix)
                print(f"Saved {len(results)} items -> {csv_path}, {json_path}")
            print(f"Не удалось прочитать ленту Интерфакса: {exc}", file=sys.stderr)
            return 2
        links = [url for url in extract_links(html, page_url) if url not in seen]
        log(f"  Found {len(links)} article links")
        if not links:
            break
        old_on_page = 0
        page_day = page_day_from_url(page_url) or date_to
        if page_day < date_from:
            break
        kept_for_day = 0
        for url in links:
            if args.max_per_day and kept_for_day >= args.max_per_day:
                break
            if url in seen:
                continue
            seen.add(url)
            try:
                title, text, datatime = parse_article(session, url, args.timeout)
            except requests.RequestException as exc:
                log(f"  warn {url} ({exc})")
                time.sleep(args.delay)
                continue
            _raw, item_date = parse_date(datatime)
            if item_date and item_date != page_day:
                seen.discard(url)
                time.sleep(args.delay)
                continue
            if item_date and item_date > date_to:
                time.sleep(args.delay)
                continue
            if item_date and item_date < date_from:
                old_on_page += 1
                time.sleep(args.delay)
                continue
            if item_date and args.max_per_day and day_counts.get(item_date, 0) >= args.max_per_day:
                time.sleep(args.delay)
                continue
            if not title or not item_date:
                continue
            day_counts[item_date] = day_counts.get(item_date, 0) + 1
            kept_for_day += 1
            results.append(NewsItem(title=title, text=text, datatime=datatime, source=source, link=url))
            log(f"  keep {datatime or '(no date)'} {url}")
            time.sleep(args.delay)
            if args.max_articles and len(results) >= args.max_articles:
                break
        if results:
            save_items(results, args.out_prefix)
            log(f"  checkpoint {len(results)}")
        if args.max_articles and len(results) >= args.max_articles:
            break
        if links and old_on_page == len(links):
            break
        page_url = previous_day(html, page_url)
        if not page_url:
            break

    csv_path, json_path = save_items(results, args.out_prefix)
    print(f"Saved {len(results)} items -> {csv_path}, {json_path}")
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
