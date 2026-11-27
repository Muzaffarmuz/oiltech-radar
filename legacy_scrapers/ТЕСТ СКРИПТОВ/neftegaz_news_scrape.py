"""Ручной сбор новостей Neftegaz.ru: https://neftegaz.ru/news/

Использует ваш реальный профиль Chrome (через playwright-byob),
чтобы пройти WAF-проверку с уже существующими cookie.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR.parent))

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from playwright_byob import launch_chrome
from bs4 import BeautifulSoup

from manual_common import (
    NewsItem,
    canonicalize_url,
    normalize_whitespace,
    parse_date,
    period_bounds,
    save_items,
    source_domain,
    text_from_selectors,
)

DEFAULT_BASE_URL = "https://neftegaz.ru/news/"
ARTICLE_RE = re.compile(r"/\d{5,}[-/]")

DATE_FROM = "2025-09-15"
DATE_TO = ""

BLOCK_STATUS_CODES = {403, 429, 468, 503}


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


def parse_article_html(html: str) -> tuple[str, str, str]:
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
    parser.add_argument("--out-prefix", default=str(_SCRIPT_DIR / "neftegaz_news"))
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--max-articles", type=int, default=0)
    parser.add_argument("--delay", type=float, default=2.0, help="Пауза между запросами, секунды.")
    parser.add_argument("--timeout", type=int, default=60, help="Таймаут навигации Playwright, секунды.")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--user-data-dir", default=None,
                        help="Путь к профилю Chrome. По умолчанию — ваш стандартный профиль.")
    parser.add_argument("--profile-directory", default="Default",
                        help="Название профиля в Chrome (Default, Profile 1 и т.д.).")
    args = parser.parse_args()

    def log(message: str) -> None:
        if not args.quiet:
            print(message, file=sys.stderr)

    try:
        date_from, date_to = period_bounds(args.date_from, args.date_to)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    source = source_domain(args.base_url)
    results: list[NewsItem] = []
    seen: set[str] = set()

    with sync_playwright() as pw:
        # Запуск вашего реального Chrome с указанным профилем
        launch_kwargs = {
            "headless": False,  # ВАЖНО: показываем окно, чтобы WAF видел реальный браузер
        }
        if args.user_data_dir:
            launch_kwargs["user_data_dir"] = args.user_data_dir
        if args.profile_directory:
            launch_kwargs["profile_directory"] = args.profile_directory

        try:
            context = launch_chrome(pw, **launch_kwargs)
        except Exception as exc:
            print(
                f"Не удалось запустить Chrome с вашим профилем: {exc}\n\n"
                f"Возможные причины:\n"
                f"  1. Chrome уже открыт. Закройте все окна Chrome и повторите.\n"
                f"  2. Профиль называется иначе. Посмотрите в Chrome: chrome://version\n"
                f"  3. Путь к профилю другой. По умолчанию это "
                f"C:\\Users\\<Имя>\\AppData\\Local\\Google\\Chrome\\User Data\n\n"
                f"Попробуйте запустить с --user-data-dir и --profile-directory явно.",
                file=sys.stderr,
            )
            return 2

        page = context.new_page()

        for page_num in range(1, args.max_pages + 1):
            list_url = build_page_url(args.base_url, page_num)
            log(f"Page {page_num}: {list_url}")

            try:
                response = page.goto(list_url, timeout=args.timeout * 1000, wait_until="domcontentloaded")
            except PlaywrightTimeoutError:
                print(f"Таймаут при загрузке {list_url}", file=sys.stderr)
                break

            if response is None:
                print(f"Нет ответа для {list_url}", file=sys.stderr)
                break

            status = response.status
            if status in BLOCK_STATUS_CODES:
                print(
                    f"neftegaz.ru вернул статус {status} даже с вашим профилем.\n"
                    f"Значит, WAF проверяет что-то ещё (IP, отпечаток устройства).\n"
                    f"Попробуйте:\n"
                    f"  1. Открыть сайт вручную в этом же окне Chrome, пройти проверку, "
                    f"затем запустить скрипт снова (не закрывая окно).\n"
                    f"  2. Использовать VPN для смены IP.",
                    file=sys.stderr,
                )
                break

            # Даём JS-челленджу выполниться
            page.wait_for_timeout(3000)

            html = page.content()
            links = [link for link in extract_links(html, list_url) if link not in seen]
            log(f"  Found {len(links)} article links")
            if not links:
                break

            old_on_page = 0
            for link in links:
                seen.add(link)
                try:
                    page.goto(link, timeout=args.timeout * 1000, wait_until="domcontentloaded")
                    page.wait_for_timeout(1500)
                    article_html = page.content()
                except PlaywrightTimeoutError:
                    log(f"  warn {link} (timeout)")
                    time.sleep(args.delay)
                    continue

                title, text, datatime = parse_article_html(article_html)
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

                results.append(
                    NewsItem(title=title, text=text, datatime=datatime, source=source, link=link)
                )
                log(f"  keep {datatime or '(no date)'} {link}")
                time.sleep(args.delay)
                if args.max_articles and len(results) >= args.max_articles:
                    break

            if args.max_articles and len(results) >= args.max_articles:
                break
            if links and old_on_page == len(links):
                break

        context.close()

    csv_path, json_path = save_items(results, args.out_prefix)
    print(f"Saved {len(results)} items -> {csv_path}, {json_path}")
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())