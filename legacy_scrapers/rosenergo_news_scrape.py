"""Ручной сбор новостей Росэнерго: https://rosenergo.gov.ru/press-center/news/"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from manual_common import NewsItem, canonicalize_url, fetch, make_session, normalize_whitespace, parse_date, period_bounds, save_items, source_domain, text_from_selectors

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "manual_sources"
DEFAULT_BASE_URL = "https://rosenergo.gov.ru/press-center/news/"
AJAX_URL = "https://rosenergo.gov.ru/local/ajax/dataForNews.php"

# Период сбора включительно, с точностью до дня. Формат YYYY-MM-DD.
# Пустая DATE_TO — по сегодняшний день.
# Аргументы --date-from и --date-to перекрывают эти значения.
DATE_FROM = "2025-10-14"
DATE_TO = ""


def extract_links(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[str] = []
    seen: set[str] = set()
    for anchor in soup.select("a[href]"):
        href = anchor.get("href") or ""
        url = canonicalize_url(urljoin(page_url, href).split("#", 1)[0])
        path = url.split("rosenergo.gov.ru", 1)[-1]
        if "/press-center/news/" not in path:
            continue
        slug = path.split("/press-center/news/", 1)[-1].strip("/")
        if not slug or slug.startswith("?"):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def load_list(session: requests.Session, page: int, timeout_s: int) -> str:
    params = {"PAGEN_1": page} if page > 1 else None
    response = session.post(
        AJAX_URL,
        params=params,
        data={"sort": "active_from", "method": "desc", "name": ""},
        headers={"X-Requested-With": "XMLHttpRequest", "Referer": DEFAULT_BASE_URL},
        timeout=timeout_s,
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    return response.text


def parse_article(session: requests.Session, url: str, timeout_s: int) -> tuple[str, str, str]:
    _status, html = fetch(session, url, timeout_s)
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("h1")
    title = normalize_whitespace(title_el.get_text(" ", strip=True) if title_el else "")
    date_el = soup.select_one(".b-news-page__date") or soup.select_one("time")
    datatime, _item_date = parse_date(date_el.get_text(" ", strip=True) if date_el else "")
    text = text_from_selectors(soup, ".b-news-page__content p")
    return title, text, datatime


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape rosenergo.gov.ru press news for a date range.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--date-from", default=DATE_FROM, help="Нижняя граница YYYY-MM-DD, включительно.")
    parser.add_argument("--date-to", default=DATE_TO, help="Верхняя граница YYYY-MM-DD, включительно. Пусто — сегодня.")
    parser.add_argument("--out-prefix", default=str(_DATA_DIR / "rosenergo_news"))
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--max-articles", type=int, default=0)
    parser.add_argument("--delay", type=float, default=0.4)
    parser.add_argument("--timeout", type=int, default=40)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--user-agent", default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) rosenergo_news_scrape/1.0")
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
        log(f"Page {page_num}")
        try:
            html = load_list(session, page_num, args.timeout)
        except requests.RequestException as exc:
            print(f"Не удалось прочитать ленту rosenergo.gov.ru: {exc}", file=sys.stderr)
            return 2
        links = [link for link in extract_links(html, args.base_url) if link not in seen]
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
        if old_on_page == len(links):
            break

    csv_path, json_path = save_items(results, args.out_prefix)
    print(f"Saved {len(results)} items -> {csv_path}, {json_path}")
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
