"""Ручной сбор новостей Neftegaz.ru: https://neftegaz.ru/news/

Селекторы карточки те же, что в legacy-скрипте раздела «Наука»:
.news_week__item .title a и путь с числовым id.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from manual_common import NewsItem, canonicalize_url, fetch, make_session, normalize_whitespace, parse_date, period_bounds, save_items, source_domain, text_from_selectors

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "manual_sources"
DEFAULT_BASE_URL = "https://neftegaz.ru/news/"
ARTICLE_RE = re.compile(r"/\d{5,}[-/]")

# Период сбора включительно, с точностью до дня. Формат YYYY-MM-DD.
# Пустая DATE_TO — по сегодняшний день.
# Аргументы --date-from и --date-to перекрывают эти значения.
DATE_FROM = "2025-10-14"
DATE_TO = ""


def build_page_url(base_url: str, page_num: int) -> str:
    if page_num <= 1:
        return base_url
    split = urlsplit(base_url)
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    query["PAGEN_1"] = str(page_num)
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), ""))


def extract_links(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.select(".news_week__item .title a[href]")
    if not anchors:
        anchors = soup.select("a[href]")
    out: list[str] = []
    seen: set[str] = set()
    for anchor in anchors:
        href = anchor.get("href") or ""
        url = canonicalize_url(urljoin(page_url, href).split("#", 1)[0])
        if "neftegaz.ru" not in url or not ARTICLE_RE.search(urlsplit(url).path):
            continue
        if "/news/" not in urlsplit(url).path and anchors != soup.select(".news_week__item .title a[href]"):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def parse_article(session: requests.Session, url: str, timeout_s: int) -> tuple[str, str, str]:
    _status, html = fetch(session, url, timeout_s)
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.find("h1")
    title = normalize_whitespace(title_el.get_text(" ", strip=True) if title_el else "")
    date_el = soup.select_one("time") or soup.select_one(".date") or soup.select_one(".news_date")
    blob = date_el.get_text(" ", strip=True) if date_el else ""
    if not blob:
        blob = normalize_whitespace(soup.get_text(" ", strip=True))[:400]
    datatime, _item_date = parse_date(blob)
    text = text_from_selectors(soup, "article p, .news_text p, .detail p, .text p")
    return title, text, datatime


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape neftegaz.ru/news for a date range.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--date-from", default=DATE_FROM, help="Нижняя граница YYYY-MM-DD, включительно.")
    parser.add_argument("--date-to", default=DATE_TO, help="Верхняя граница YYYY-MM-DD, включительно. Пусто — сегодня.")
    parser.add_argument("--out-prefix", default=str(_DATA_DIR / "neftegaz_news"))
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--max-articles", type=int, default=0)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--user-agent", default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) neftegaz_news_scrape/1.0")
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

    for page_num in range(1, args.max_pages + 1):
        page = build_page_url(args.base_url, page_num)
        log(f"Page {page_num}: {page}")
        try:
            _status, html = fetch(session, page, args.timeout)
        except requests.HTTPError as exc:
            print(f"Не удалось прочитать ленту neftegaz.ru: {exc}", file=sys.stderr)
            return 2
        except requests.RequestException as exc:
            print(f"Не удалось прочитать ленту neftegaz.ru: {exc}", file=sys.stderr)
            return 2
        if "ddos" in html.lower() and len(html) < 2000:
            print("neftegaz.ru отдал страницу защиты, а не ленту.", file=sys.stderr)
            return 2
        links = [link for link in extract_links(html, page) if link not in seen]
        log(f"  Found {len(links)} article links")
        if not links:
            break
        old_on_page = 0
        for link in links:
            seen.add(link)
            try:
                title, text, datatime = parse_article(session, link, args.timeout)
            except requests.RequestException as exc:
                log(f"  warn {link} ({exc})")
                time.sleep(args.delay)
                continue
            _raw, item_date = parse_date(datatime)
            if item_date and item_date > date_to:
                time.sleep(args.delay)
                continue
            if item_date and item_date < date_from:
                old_on_page += 1
                time.sleep(args.delay)
                continue
            if not title:
                continue
            results.append(NewsItem(title=title, text=text, datatime=datatime, source=source, link=link))
            log(f"  keep {datatime or '(no date)'} {link}")
            time.sleep(args.delay)
            if args.max_articles and len(results) >= args.max_articles:
                break
        if args.max_articles and len(results) >= args.max_articles:
            break
        if links and old_on_page == len(links):
            break

    csv_path, json_path = save_items(results, args.out_prefix)
    print(f"Saved {len(results)} items -> {csv_path}, {json_path}")
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
