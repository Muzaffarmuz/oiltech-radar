import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

import requests
from bs4 import BeautifulSoup


SOURCE_DOMAIN = "nprom.online"
ALLOWED_NETLOCS = {SOURCE_DOMAIN, f"www.{SOURCE_DOMAIN}"}
DEFAULT_BASE_URL = "https://nprom.online/trends/"
DEFAULT_POST_PREFIX_EXCLUDE = {
    "mainthemes",
    "tag",
    "author",
    "page",
    "wp-content",
    "wp-json",
}


RU_MONTHS = {
    "января": 1,
    "январь": 1,
    "февраля": 2,
    "февраль": 2,
    "марта": 3,
    "март": 3,
    "апреля": 4,
    "апрель": 4,
    "мая": 5,
    "май": 5,
    "июня": 6,
    "июнь": 6,
    "июля": 7,
    "июль": 7,
    "августа": 8,
    "август": 8,
    "сентября": 9,
    "сентябрь": 9,
    "октября": 10,
    "октябрь": 10,
    "ноября": 11,
    "ноябрь": 11,
    "декабря": 12,
    "декабрь": 12,
}


DATE_RE_WORDS = re.compile(r"(\d{1,2})\s+([А-Яа-яёЁ]+)\s+(\d{4})")
DATE_RE_DOTS = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})")


def subtract_months(d: date, months: int) -> date:
    year = d.year
    month = d.month - months
    while month <= 0:
        month += 12
        year -= 1

    # Clamp day to last day of target month.
    if month == 2:
        is_leap = (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0))
        last_day = 29 if is_leap else 28
    elif month in (1, 3, 5, 7, 8, 10, 12):
        last_day = 31
    else:
        last_day = 30

    return date(year, month, min(d.day, last_day))


def normalize_whitespace(s: str) -> str:
    s = s.replace("\u00a0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def parse_article_date_from_text(text: str) -> Optional[date]:
    text = text.strip()

    m = DATE_RE_DOTS.search(text)
    if m:
        day_s, month_s, year_s = m.groups()
        try:
            return date(int(year_s), int(month_s), int(day_s))
        except ValueError:
            return None

    m = DATE_RE_WORDS.search(text)
    if not m:
        return None
    day_s, month_word, year_s = m.groups()
    month = RU_MONTHS.get(month_word.lower())
    if not month:
        return None
    try:
        return date(int(year_s), month, int(day_s))
    except ValueError:
        return None


def is_trends_article_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.netloc not in ALLOWED_NETLOCS:
        return False
    path = parsed.path or ""
    if not path.startswith("/trends/"):
        return False
    if path.rstrip("/") == "/trends":
        return False
    if "/trends/page/" in path:
        return False
    return True


def is_probable_post_url(url: str) -> bool:
    """
    Generic post URL detector for nprom.online.
    Many posts use a 2-segment permalink: /news/<slug>/, /market/<slug>/, /technologies/<slug>/, etc.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.netloc not in ALLOWED_NETLOCS:
        return False
    path = parsed.path or ""
    if "/page/" in path:
        return False
    parts = [p for p in path.split("/") if p]
    if len(parts) != 2:
        return False
    if parts[0].lower() in DEFAULT_POST_PREFIX_EXCLUDE:
        return False
    if parts[1].lower() in ("page", "feed"):
        return False
    return True


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    netloc = SOURCE_DOMAIN if parsed.netloc in ALLOWED_NETLOCS else parsed.netloc
    path = parsed.path or "/"
    return f"{parsed.scheme}://{netloc}{path}"


def extract_trends_article_links(list_html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(list_html, "html.parser")
    links: list[str] = []
    for a in soup.select("a[href]"):
        href = a.get("href")
        if not href:
            continue
        absolute = urljoin(page_url, href)
        if is_trends_article_url(absolute):
            links.append(canonicalize_url(absolute.split("#", 1)[0]))

    # Stable order + de-dup while preserving first occurrence.
    seen: set[str] = set()
    out: list[str] = []
    for u in links:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def extract_section_article_links(list_html: str, page_url: str) -> list[str]:
    """
    Extract article links from a themed section page like:
    https://nprom.online/mainthemes/czifrovye-resheniya/

    Strategy: collect internal "post-like" URLs between the section H1 and the
    "Пагинация записей" block (which appears before "Рекомендуем" etc).
    """
    soup = BeautifulSoup(list_html, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        # Fallback: if no H1, behave like broad extractor inside main.
        container = soup.find("main") or soup
        candidates: list[str] = []
        for a in container.select("a[href]"):
            absolute = urljoin(page_url, a.get("href"))
            if is_probable_post_url(absolute):
                candidates.append(canonicalize_url(absolute.split("#", 1)[0]))
        seen: set[str] = set()
        out: list[str] = []
        for u in candidates:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    end_marker = soup.find(string=re.compile(r"\bПагинация\s+записей\b", re.IGNORECASE))
    end_tag = end_marker.parent if end_marker else None

    in_range = False
    candidates: list[str] = []
    for tag in soup.find_all(True):
        if tag is h1:
            in_range = True
            continue
        if not in_range:
            continue
        if end_tag is not None and tag is end_tag:
            break
        if end_tag is None and tag.get_text(" ", strip=True).lower() == "рекомендуем":
            # Secondary heuristic.
            break

        for a in tag.select("a[href]"):
            href = a.get("href")
            if not href:
                continue
            absolute = urljoin(page_url, href)
            if is_probable_post_url(absolute):
                candidates.append(canonicalize_url(absolute.split("#", 1)[0]))

    seen: set[str] = set()
    out: list[str] = []
    for u in candidates:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def pick_main_container(soup: BeautifulSoup):
    for selector in (
        "article .entry-content",
        "article .post-content",
        "article .single__content",
        "article .article__content",
        "article .content",
        "article",
        "main",
        "body",
    ):
        el = soup.select_one(selector)
        if el is not None:
            return el
    return soup


def extract_article_text(soup: BeautifulSoup) -> str:
    for tag in soup.select("script, style, noscript"):
        tag.decompose()

    container = pick_main_container(soup)
    for tag in container.select("nav, aside, header, footer, form"):
        tag.decompose()
    for tag in container.select(
        ".breadcrumbs, .breadcrumb, .share, .social, .related, .post-tags, .tags, .comments"
    ):
        tag.decompose()

    parts: list[str] = []
    for el in container.select("p, h2, h3, li"):
        txt = normalize_whitespace(el.get_text(" ", strip=True))
        if not txt:
            continue
        # Skip obvious boilerplate.
        if txt.lower().startswith(("поделиться", "читайте также", "источник:", "реклама")):
            continue
        parts.append(txt)

    text = "\n".join(parts)
    return normalize_whitespace(text)


def extract_article_title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        t = normalize_whitespace(h1.get_text(" ", strip=True))
        if t:
            return t
    if soup.title:
        return normalize_whitespace(soup.title.get_text(" ", strip=True))
    return ""


def extract_article_datetime(soup: BeautifulSoup) -> tuple[str, Optional[date]]:
    time_tag = soup.find("time")
    if time_tag:
        dt_attr = (time_tag.get("datetime") or "").strip()
        if dt_attr:
            dt_attr = dt_attr.replace("Z", "+00:00")
            # datetime.fromisoformat supports YYYY-MM-DD and full ISO timestamps.
            try:
                parsed = datetime.fromisoformat(dt_attr)
                return parsed.isoformat(), parsed.date()
            except ValueError:
                try:
                    d = date.fromisoformat(dt_attr[:10])
                    return d.isoformat(), d
                except ValueError:
                    pass

        time_text = normalize_whitespace(time_tag.get_text(" ", strip=True))
        d = parse_article_date_from_text(time_text)
        if d:
            return d.isoformat(), d

    # nprom.online specific: date in a div like <div class="post-toping__date">28 февраля 2026</div>
    date_div = soup.select_one(".post-toping__date")
    if date_div:
        date_text = normalize_whitespace(date_div.get_text(" ", strip=True))
        d = parse_article_date_from_text(date_text)
        if d:
            return d.isoformat(), d

    # Fallback: search near the top of the page text.
    container = pick_main_container(soup)
    top_text = normalize_whitespace(container.get_text("\n", strip=True))[:2000]
    d = parse_article_date_from_text(top_text)
    if not d:
        return "", None
    return d.isoformat(), d


@dataclass(frozen=True)
class TrendItem:
    title: str
    text: str
    datatime: str
    source: str
    link: str


def fetch(session: requests.Session, url: str, timeout_s: int) -> str:
    resp = session.get(url, timeout=timeout_s)
    resp.raise_for_status()
    resp.encoding = resp.encoding or "utf-8"
    return resp.text


def parse_article(session: requests.Session, url: str, timeout_s: int) -> tuple[TrendItem, Optional[date]]:
    html = fetch(session, url, timeout_s=timeout_s)
    soup = BeautifulSoup(html, "html.parser")
    title = extract_article_title(soup)
    datatime, article_date = extract_article_datetime(soup)
    text = extract_article_text(soup)
    item = TrendItem(
        title=title,
        text=text,
        datatime=datatime,
        source=SOURCE_DOMAIN,
        link=url,
    )
    return item, article_date


def save_csv(items: Iterable[TrendItem], path: str) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["title", "text", "datatime", "source", "link"])
        writer.writeheader()
        for it in items:
            writer.writerow(
                {
                    "title": it.title,
                    "text": it.text,
                    "datatime": it.datatime,
                    "source": it.source,
                    "link": it.link,
                }
            )


def save_json(items: Iterable[TrendItem], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            [
                {
                    "title": it.title,
                    "text": it.text,
                    "datatime": it.datatime,
                    "source": it.source,
                    "link": it.link,
                }
                for it in items
            ],
            f,
            ensure_ascii=False,
            indent=2,
        )


def build_page_url(base_url: str, page_num: int) -> str:
    if page_num == 1:
        return base_url
    if not base_url.endswith("/"):
        base_url += "/"
    return urljoin(base_url, f"page/{page_num}/")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape nprom.online/trends posts for the last N months.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--out-prefix", default=str(_DATA_DIR / "nprom_trends"))
    parser.add_argument("--max-pages", type=int, default=200)
    parser.add_argument("--delay", type=float, default=0.7, help="Delay between requests (seconds).")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout (seconds).")
    parser.add_argument("--quiet", action="store_true", help="Disable intermediate progress logs.")
    parser.add_argument(
        "--user-agent",
        default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) nprom_trends_scrape/1.0",
    )
    args = parser.parse_args()

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg, file=sys.stderr)

    today = date.today()
    cutoff = subtract_months(today, args.months)
    log(f"Cutoff date (months={args.months}): {cutoff.isoformat()} (today={today.isoformat()})")

    base_path = (urlparse(args.base_url).path or "/").rstrip("/")
    is_trends_section = base_path == "/trends"
    if is_trends_section:
        log("Mode: trends (only /trends/<slug>/ links)")
    else:
        log("Mode: section (post-like links between H1 and pagination)")

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": args.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.7,en;q=0.6",
        }
    )

    results: list[TrendItem] = []
    seen_links: set[str] = set()
    parsed_total = 0
    kept_total = 0

    for page_num in range(1, args.max_pages + 1):
        page_url = build_page_url(args.base_url, page_num)
        log(f"Page {page_num}: {page_url}")
        try:
            list_html = fetch(session, page_url, timeout_s=args.timeout)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                log("Reached end of pagination (404).")
                break
            raise

        links = (
            extract_trends_article_links(list_html, page_url=page_url)
            if is_trends_section
            else extract_section_article_links(list_html, page_url=page_url)
        )
        links = [u for u in links if u not in seen_links]
        log(f"  Found {len(links)} new article links")
        if not links:
            log("No new links on page; stopping.")
            break

        page_dates: list[date] = []
        for idx, url in enumerate(links, start=1):
            seen_links.add(url)
            try:
                item, item_date = parse_article(session, url, timeout_s=args.timeout)
            except Exception as e:
                print(f"[warn] failed to parse article: {url} ({e})", file=sys.stderr)
                time.sleep(args.delay)
                continue

            parsed_total += 1
            if item_date is not None:
                page_dates.append(item_date)
                if item_date < cutoff:
                    # Older than requested window: skip persisting.
                    log(
                        f"  [{idx}/{len(links)}] skip (old) {item_date.isoformat()} {url}"
                    )
                    time.sleep(args.delay)
                    continue

            results.append(item)
            kept_total += 1
            log(
                f"  [{idx}/{len(links)}] keep {item.datatime or '(no date)'} {url} (kept={kept_total}, parsed={parsed_total})"
            )
            time.sleep(args.delay)

        if page_dates and max(page_dates) < cutoff:
            # Page is entirely older than cutoff and pages are newest->oldest.
            log("Page dates are older than cutoff; stopping.")
            break

    csv_path = f"{args.out_prefix}.csv"
    json_path = f"{args.out_prefix}.json"
    save_csv(results, csv_path)
    save_json(results, json_path)

    print(f"Saved {len(results)} items -> {csv_path}, {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
