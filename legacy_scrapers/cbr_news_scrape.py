"""Ручной сбор новостей Банка России: https://www.cbr.ru/news/"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from manual_common import NewsItem, fetch, make_session, normalize_whitespace, parse_date, period_bounds, save_items, source_domain, text_from_selectors

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "manual_sources"
DEFAULT_BASE_URL = "https://www.cbr.ru/news/"
LIST_URL = "https://www.cbr.ru/news/eventandpress/"

# Период сбора включительно, с точностью до дня. Формат YYYY-MM-DD.
# Пустая DATE_TO — по сегодняшний день.
# Аргументы --date-from и --date-to перекрывают эти значения.
DATE_FROM = "2025-10-14"
DATE_TO = ""


def article_url(item: dict) -> str:
    doc = str(item.get("doc_htm") or "").strip()
    if str(item.get("TBLType") or "") == "press":
        return urljoin(DEFAULT_BASE_URL, "/press/pr/?file=" + doc)
    return urljoin(DEFAULT_BASE_URL, "/press/event/?id=" + doc)


def load_page(session: requests.Session, page: int, timeout_s: int) -> list[dict]:
    response = session.get(
        LIST_URL,
        params={
            "page": page,
            "IsEng": "false",
            "type": 100,
            "dateFrom": "",
            "dateTo": "",
            "Tid": "",
            "vol": "",
            "phrase": "",
            "pagesize": 20,
        },
        headers={"X-Requested-With": "XMLHttpRequest", "Referer": DEFAULT_BASE_URL},
        timeout=timeout_s,
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict):
        raise RuntimeError(payload.get("Error") or "ЦБ не отдал список новостей")
    return list(payload)


def parse_article(session: requests.Session, url: str, timeout_s: int) -> tuple[str, str]:
    _status, html = fetch(session, url, timeout_s)
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.find("h1")
    title = normalize_whitespace(title_el.get_text(" ", strip=True) if title_el else "")
    text = text_from_selectors(soup, ".landing-text p, #content p, article p")
    return title, text


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape cbr.ru/news for a date range.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--date-from", default=DATE_FROM, help="Нижняя граница YYYY-MM-DD, включительно.")
    parser.add_argument("--date-to", default=DATE_TO, help="Верхняя граница YYYY-MM-DD, включительно. Пусто — сегодня.")
    parser.add_argument("--out-prefix", default=str(_DATA_DIR / "cbr_news"))
    parser.add_argument("--max-pages", type=int, default=30)
    parser.add_argument("--max-articles", type=int, default=0)
    parser.add_argument("--delay", type=float, default=0.4)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--user-agent", default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) cbr_news_scrape/1.0")
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
    # Без www DDoS-Guard отвечает 403, поэтому сначала открываем живую ленту.
    fetch(session, "https://www.cbr.ru/news/", args.timeout)

    results: list[NewsItem] = []
    seen: set[str] = set()
    for page in range(args.max_pages):
        log(f"Page {page}")
        try:
            rows = load_page(session, page, args.timeout)
        except (requests.RequestException, RuntimeError, json.JSONDecodeError) as exc:
            if results:
                csv_path, json_path = save_items(results, args.out_prefix)
                print(f"Saved {len(results)} items -> {csv_path}, {json_path}")
            print(f"Не удалось прочитать ленту ЦБ: {exc}", file=sys.stderr)
            return 2
        if not rows:
            break
        page_dates: list[date] = []
        for row in rows:
            datatime, item_date = parse_date(str(row.get("DT") or ""))
            if item_date:
                page_dates.append(item_date)
            url = article_url(row)
            if url in seen:
                continue
            seen.add(url)
            if item_date and (item_date < date_from or item_date > date_to):
                continue
            title = normalize_whitespace(str(row.get("name_doc") or ""))
            try:
                parsed_title, text = parse_article(session, url, args.timeout)
            except requests.RequestException as exc:
                log(f"  warn {url} ({exc})")
                time.sleep(args.delay)
                continue
            results.append(
                NewsItem(
                    title=parsed_title or title,
                    text=text,
                    datatime=datatime,
                    source=source,
                    link=url,
                )
            )
            log(f"  keep {datatime or '(no date)'} {url}")
            time.sleep(args.delay)
            if args.max_articles and len(results) >= args.max_articles:
                break
        if args.max_articles and len(results) >= args.max_articles:
            break
        if results:
            save_items(results, args.out_prefix)
            log(f"  checkpoint {len(results)}")
        if page_dates and max(page_dates) < date_from:
            break

    csv_path, json_path = save_items(results, args.out_prefix)
    print(f"Saved {len(results)} items -> {csv_path}, {json_path}")
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
