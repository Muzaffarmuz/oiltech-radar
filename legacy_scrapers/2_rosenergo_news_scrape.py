#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Парсер новостей с https://rosenergo.gov.ru/press-center/news/

Селекторы подтверждены на живой вёрстке 2026-10-14:

Лента (HTML-фрагмент из dataForNews.php):
  - карточка: ul.b-card-list--news-list li.b-card-list__item
  - ссылка: a.b-card
  - дата в ленте: time.b-card__date[datetime]  (ISO, напр. 2026-10-13)
  - пагинация: GET /local/ajax/dataForNews.php?PAGEN_1=N

Статья:
  - заголовок: h1.b-title.b-title--h1
  - дата: time.b-news-page__date[datetime]  (ISO)
  - текст: абзацы <p> внутри .b-news-page__content

Авторизация: cookie PHPSESSID / BITRIX_SM_GUEST_ID, которые
получаются при первом GET на /press-center/news/.
Sessid в теле POST не нужен — лента отдаётся по GET.
"""

import argparse
import csv
import json
import re
import sys
import time
from datetime import date, timedelta
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

import requests
from bs4 import BeautifulSoup

# ============================================================
# Переменные, которые можно менять руками
# ============================================================
DATE_FROM = "2025-04-01"
DATE_TO = ""
MAX_ARTICLES = 30000
DELAY = 0.4

DEFAULT_BASE_URL = "https://rosenergo.gov.ru/press-center/news/?&name="
DEFAULT_SOURCE = "rosenergo.gov.ru"
DEFAULT_OUT_PREFIX = "rosenergo_news"
DEFAULT_MAX_PAGES = 10
DEFAULT_TIMEOUT = 30
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

AJAX_URL = "https://rosenergo.gov.ru/local/ajax/dataForNews.php"
LIST_REFERER = "https://rosenergo.gov.ru/press-center/news/"


def log(msg: str, quiet: bool = False):
    if not quiet:
        print(msg, file=sys.stderr)


def collapse_spaces(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def clean_url(url: str) -> str:
    parsed = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
         if not k.lower().startswith("utm_")]
    new_query = urlencode(q)
    return urlunparse(parsed._replace(query=new_query, fragment=""))


def parse_date_string(s: str) -> str:
    if not s:
        return ""
    s = collapse_spaces(s)
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    if m:
        d, mo, y = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    return ""


def is_in_range(datestr: str, date_from: str, date_to: str) -> bool:
    if not datestr:
        return True
    if date_from and datestr < date_from:
        return False
    if date_to and datestr > date_to:
        return False
    return True


def fetch_news_list(session, page, timeout, quiet):
    """GET на dataForNews.php?PAGEN_1=N. Возвращает HTML-фрагмент."""
    url = AJAX_URL if page == 1 else f"{AJAX_URL}?PAGEN_1={page}"
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": LIST_REFERER,
        "Accept": "*/*",
    }
    log(f"[list] GET {url}", quiet)
    try:
        r = session.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        print(f"ERROR: AJAX request failed: {e}", file=sys.stderr)
        return None
    if r.status_code != 200:
        print(f"ERROR: AJAX returned {r.status_code}", file=sys.stderr)
        return None
    return r.text


def extract_article_links(html_fragment, base_url):
    """Возвращает список (url, datestr) из HTML-фрагмента ленты."""
    soup = BeautifulSoup(html_fragment, "html.parser")
    results = []
    seen = set()
    for a in soup.select("ul.b-card-list--news-list li.b-card-list__item a.b-card"):
        href = a.get("href", "").strip()
        if not href:
            continue
        full = clean_url(urljoin(base_url, href))
        if not re.search(r"/press-center/news/[^/?#]+/?$", full):
            continue
        if full in seen:
            continue
        seen.add(full)

        datestr = ""
        time_el = a.select_one("time.b-card__date")
        if time_el:
            dt_attr = time_el.get("datetime")
            if dt_attr:
                datestr = parse_date_string(dt_attr)
            if not datestr:
                datestr = parse_date_string(time_el.get_text(" ", strip=True))
        results.append((full, datestr))
    return results


def parse_article(html, url, source, fallback_date=""):
    soup = BeautifulSoup(html, "html.parser")

    title_el = soup.select_one("h1.b-title--h1") or soup.find("h1")
    if not title_el:
        return None
    title = collapse_spaces(title_el.get_text(" ", strip=True))
    if not title:
        return None

    datestr = ""
    date_el = soup.select_one("time.b-news-page__date")
    if date_el:
        dt_attr = date_el.get("datetime")
        if dt_attr:
            datestr = parse_date_string(dt_attr)
        if not datestr:
            datestr = parse_date_string(date_el.get_text(" ", strip=True))
    if not datestr:
        datestr = fallback_date

    content = soup.select_one(".b-news-page__content")
    paragraphs = []
    if content:
        for p in content.find_all("p"):
            txt = collapse_spaces(p.get_text(" ", strip=True))
            if len(txt) >= 40:
                paragraphs.append(txt)
    text = "\n".join(paragraphs)

    return {
        "title": title,
        "text": text,
        "datatime": datestr,
        "source": source,
        "link": url,
    }


def save_csv(items, path):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=",")
        w.writerow(["title", "text", "datatime", "source", "link"])
        for it in items:
            w.writerow([it["title"], it["text"], it["datatime"],
                        it["source"], it["link"]])


def save_json(items, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def collect(args):
    session = requests.Session()
    session.headers.update({"User-Agent": args.user_agent})

    date_from = args.date_from
    date_to = args.date_to
    if not date_to:
        date_to = date.today().strftime("%Y-%m-%d")
    if not date_from:
        date_from = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")

    base = args.base_url or DEFAULT_BASE_URL
    source = DEFAULT_SOURCE
    out_prefix = args.out_prefix or DEFAULT_OUT_PREFIX
    max_articles = args.max_articles if args.max_articles is not None else MAX_ARTICLES
    max_pages = args.max_pages if args.max_pages is not None else DEFAULT_MAX_PAGES
    delay = args.delay if args.delay is not None else DELAY
    quiet = args.quiet

    # Шаг 1: GET на страницу ленты, чтобы получить cookies
    log(f"[init] GET {base}", quiet)
    try:
        r0 = session.get(base, timeout=args.timeout)
    except requests.RequestException as e:
        print(f"ERROR: cannot open news page: {e}", file=sys.stderr)
        return None
    if r0.status_code != 200:
        print(f"ERROR: news page returned {r0.status_code}", file=sys.stderr)
        return None

    # Шаг 2: AJAX-лента
    article_urls = []
    for page in range(1, max_pages + 1):
        fragment = fetch_news_list(session, page, args.timeout, quiet)
        if fragment is None:
            return None
        if not fragment.strip():
            log(f"[list] empty fragment on page {page}", quiet)
            break

        found = extract_article_links(fragment, base)
        if not found:
            log(f"[list] no article links on page {page}", quiet)
            break

        for url, d in found:
            article_urls.append((url, d))

        if max_articles and len(article_urls) >= max_articles * 2:
            break

        time.sleep(delay)

    if not article_urls:
        print("ERROR: no article links found in AJAX feed", file=sys.stderr)
        return None

    seen = set()
    uniq = []
    for url, d in article_urls:
        if url not in seen:
            seen.add(url)
            uniq.append((url, d))
    article_urls = uniq

    # Шаг 3: парсим статьи
    items = []
    for url, fallback_date in article_urls:
        if max_articles and len(items) >= max_articles:
            break

        log(f"[article] {url}", quiet)
        try:
            r = session.get(url, timeout=args.timeout)
        except requests.RequestException as e:
            log(f"skip (request error): {url}: {e}", quiet)
            continue
        if r.status_code != 200:
            log(f"skip (status {r.status_code}): {url}", quiet)
            continue

        item = parse_article(r.text, url, source, fallback_date)
        if not item:
            log(f"skip (no title): {url}", quiet)
            continue

        if not is_in_range(item["datatime"], date_from, date_to):
            log(f"skip (date out of range): {url} ({item['datatime']})", quiet)
            continue

        items.append(item)
        log(f"keep {item['datatime']} {url}", quiet)
        time.sleep(delay)

    if not items:
        print("ERROR: no articles collected", file=sys.stderr)
        return None

    return items, out_prefix


def build_parser():
    p = argparse.ArgumentParser(
        description="Парсер новостей Росэнерго"
    )
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--date-from", default=DATE_FROM)
    p.add_argument("--date-to", default=DATE_TO)
    p.add_argument("--out-prefix", default=None)
    p.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    p.add_argument("--max-articles", type=int, default=MAX_ARTICLES)
    p.add_argument("--delay", type=float, default=DELAY)
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    result = collect(args)
    if result is None:
        sys.exit(1)

    items, out_prefix = result
    csv_path = f"{out_prefix}.csv"
    json_path = f"{out_prefix}.json"

    save_csv(items, csv_path)
    save_json(items, json_path)

    print(f"Saved {len(items)} items -> {csv_path}, {json_path}")
    sys.exit(0)


if __name__ == "__main__":
    main()