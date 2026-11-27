import argparse
import csv
import json
import re
import sys
import time
import urllib3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

import requests
from bs4 import BeautifulSoup


DEFAULT_BASE_URL = "https://neftegaz.ru/science/"


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


DATE_RE_DOTS = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
DATE_RE_WORDS_Y = re.compile(r"\b(\d{1,2})\s+([а-яё]+)\s+(\d{4})\b", re.IGNORECASE)
DATE_RE_WORDS_NOY = re.compile(r"\b(\d{1,2})\s+([а-яё]+)\b", re.IGNORECASE)
TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")


def subtract_months(d: date, months: int) -> date:
    year = d.year
    month = d.month - months
    while month <= 0:
        month += 12
        year -= 1

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


def source_domain_from_base_url(base_url: str) -> str:
    host = (urlsplit(base_url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    parts = [p for p in host.split(".") if p]
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def canonicalize_url(url: str) -> str:
    """
    Remove fragment and common tracking params to make de-duping stable.
    Keeps non-tracking query params (if any).
    """
    split = urlsplit(url)
    query_pairs = []
    for k, v in parse_qsl(split.query, keep_blank_values=True):
        kl = (k or "").lower()
        if kl.startswith("utm_"):
            continue
        if kl in {"gclid", "fbclid", "yclid", "erid"}:
            continue
        query_pairs.append((k, v))
    query = urlencode(query_pairs, doseq=True)
    return urlunsplit((split.scheme, split.netloc, split.path, query, ""))


def parse_date_from_text(text: str, *, today: date) -> tuple[str, Optional[date]]:
    """
    Returns (datatime_str, date_obj).
    datatime_str is normalized to ISO-like output when parsing succeeds,
    otherwise ("", None).
    """
    text = normalize_whitespace(text)
    if not text:
        return "", None

    # ISO in free text (rare); try fromisoformat heuristics.
    iso_candidate = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso_candidate)
        return dt.isoformat(), dt.date()
    except ValueError:
        pass
    try:
        d = date.fromisoformat(iso_candidate[:10])
        return d.isoformat(), d
    except ValueError:
        pass

    m = DATE_RE_DOTS.search(text)
    if m:
        day_s, month_s, year_s = m.groups()
        try:
            d = date(int(year_s), int(month_s), int(day_s))
        except ValueError:
            return "", None
        t = TIME_RE.search(text)
        if t:
            hh, mm = int(t.group(1)), int(t.group(2))
            return datetime(d.year, d.month, d.day, hh, mm, 0).isoformat(), d
        return d.isoformat(), d

    m = DATE_RE_WORDS_Y.search(text)
    if m:
        day_s, month_word, year_s = m.groups()
        month = RU_MONTHS.get(month_word.lower())
        if not month:
            return "", None
        try:
            d = date(int(year_s), month, int(day_s))
        except ValueError:
            return "", None
        t = TIME_RE.search(text)
        if t:
            hh, mm = int(t.group(1)), int(t.group(2))
            return datetime(d.year, d.month, d.day, hh, mm, 0).isoformat(), d
        return d.isoformat(), d

    # Formats like "02 марта 15:05" (no year).
    m = DATE_RE_WORDS_NOY.search(text)
    if m:
        day_s, month_word = m.groups()
        month = RU_MONTHS.get(month_word.lower())
        if not month:
            return "", None
        day_i = int(day_s)

        year_guess = today.year
        # If the month is "ahead" of current month, assume it's from previous year (Jan -> Dec).
        if month > today.month:
            year_guess -= 1
        try:
            d = date(year_guess, month, day_i)
        except ValueError:
            return "", None
        t = TIME_RE.search(text)
        if t:
            hh, mm = int(t.group(1)), int(t.group(2))
            return datetime(d.year, d.month, d.day, hh, mm, 0).isoformat(), d
        return d.isoformat(), d

    return "", None


def pick_main_container(soup: BeautifulSoup):
    for selector in (
        "article",
        ".detail_news",
        ".detail_news__text",
        ".detail_news__content",
        ".news-detail",
        ".news_detail",
        ".detail_text",
        ".entry-content",
        "main",
        "body",
    ):
        el = soup.select_one(selector)
        if el is not None:
            return el
    return soup


def extract_article_title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        t = normalize_whitespace(h1.get_text(" ", strip=True))
        if t:
            return t
    if soup.title:
        return normalize_whitespace(soup.title.get_text(" ", strip=True))
    return ""


def extract_article_datetime(soup: BeautifulSoup, *, today: date) -> tuple[str, Optional[date]]:
    time_tag = soup.select_one("time[datetime]")
    if time_tag is not None:
        dt_attr = (time_tag.get("datetime") or "").strip()
        if dt_attr:
            dt_attr = dt_attr.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(dt_attr)
                return dt.isoformat(), dt.date()
            except ValueError:
                try:
                    d = date.fromisoformat(dt_attr[:10])
                    return d.isoformat(), d
                except ValueError:
                    pass

    for selector in (
        "time",
        ".post-toping__date",
        ".detail_news__date",
        ".news-detail__date",
        ".article__date",
        ".meta .date",
    ):
        el = soup.select_one(selector)
        if el is None:
            continue
        dt, d = parse_date_from_text(el.get_text(" ", strip=True), today=today)
        if d is not None:
            return dt, d

    container = pick_main_container(soup)
    top_text = normalize_whitespace(container.get_text("\n", strip=True))[:2500]
    return parse_date_from_text(top_text, today=today)


def extract_article_text(soup: BeautifulSoup) -> str:
    for tag in soup.select("script, style, noscript"):
        tag.decompose()

    container = pick_main_container(soup)

    for tag in container.select("nav, aside, header, footer, form"):
        tag.decompose()

    for tag in container.select(
        ".breadcrumbs, .breadcrumb, .share, .social, .related, .recommend, .post-tags, .tags, .comments, "
        ".comment, .footer, .sidebar"
    ):
        tag.decompose()

    for tag in list(container.select("[class]")):
        attrs = getattr(tag, "attrs", None)
        if not isinstance(attrs, dict):
            continue
        classes = attrs.get("class")
        if not isinstance(classes, list):
            continue
        cls = " ".join(classes)
        if re.search(r"\b(share|social|tag|comment|recommend|related|footer|header|nav|sidebar|breadcrumbs)\b", cls, re.I):
            tag.decompose()

    parts: list[str] = []
    seen: set[str] = set()
    for el in container.select("p, h2, h3, h4, li, blockquote"):
        txt = normalize_whitespace(el.get_text(" ", strip=True))
        if not txt:
            continue
        low = txt.lower()
        if low.startswith(
            (
                "поделиться",
                "подпишитесь",
                "подписаться",
                "рекомендуем",
                "читайте также",
                "теги:",
                "комментарии",
                "источник:",
            )
        ):
            continue
        if txt in seen:
            continue
        seen.add(txt)
        parts.append(txt)

    return normalize_whitespace("\n".join(parts))


def is_same_site(url: str, *, allowed_hosts: set[str]) -> bool:
    try:
        host = (urlsplit(url).hostname or "").lower()
    except Exception:
        return False
    return host in allowed_hosts


def looks_like_article_path(path: str) -> bool:
    # neftegaz.ru articles in the provided section usually contain numeric IDs like /917052-.../
    return bool(re.search(r"/\d{5,}[-/]", path))


def extract_article_links(list_html: str, *, page_url: str, base_url: str, allowed_hosts: set[str]) -> list[str]:
    soup = BeautifulSoup(list_html, "html.parser")
    base_path = (urlsplit(base_url).path or "/").rstrip("/") + "/"

    # neftegaz.ru listing: prefer the known card selector
    candidates: list[str] = []
    card_links = soup.select(".news_week__item .title a[href]")
    for a in card_links:
        href = a.get("href")
        if not href:
            continue
        candidates.append(urljoin(page_url, href))

    strict_article_heuristic = not bool(card_links)
    if not candidates:
        container = soup.select_one("main") or soup
        for a in container.select("a[href]"):
            href = a.get("href")
            if not href:
                continue
            candidates.append(urljoin(page_url, href))

    out: list[str] = []
    seen: set[str] = set()
    for u in candidates:
        u = canonicalize_url(u.split("#", 1)[0])
        split = urlsplit(u)
        if split.scheme not in {"http", "https"}:
            continue
        if not is_same_site(u, allowed_hosts=allowed_hosts):
            continue
        path = split.path or "/"
        if not path.startswith(base_path):
            continue
        if path.rstrip("/") == base_path.rstrip("/"):
            continue
        if strict_article_heuristic and not looks_like_article_path(path):
            continue
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def extract_listing_dates(list_html: str, *, today: date) -> list[date]:
    soup = BeautifulSoup(list_html, "html.parser")
    out: list[date] = []

    for el in soup.select(".news_week__item .date"):
        dt, d = parse_date_from_text(el.get_text(" ", strip=True), today=today)
        if d is not None:
            out.append(d)

    if not out:
        for el in soup.select(".date, time"):
            dt, d = parse_date_from_text(el.get_text(" ", strip=True), today=today)
            if d is not None:
                out.append(d)

    return out


def find_next_page_url(list_html: str, *, page_url: str, page_num: int) -> Optional[str]:
    soup = BeautifulSoup(list_html, "html.parser")
    rel_next = soup.select_one('link[rel="next"][href], a[rel="next"][href]')
    if rel_next is not None:
        href = rel_next.get("href")
        if href:
            return canonicalize_url(urljoin(page_url, href))

    for sel in (
        "a.next[href]",
        "a.pagination__next[href]",
        "a[aria-label*=След][href]",
        "a[title*=След][href]",
    ):
        a = soup.select_one(sel)
        if a is not None and a.get("href"):
            return canonicalize_url(urljoin(page_url, a.get("href")))

    # Bitrix-style: try to locate link with next PAGEN_* value.
    hrefs = [a.get("href") for a in soup.select("a[href]") if a.get("href")]
    for href in hrefs:
        absu = urljoin(page_url, href)
        qs = dict(parse_qsl(urlsplit(absu).query))
        for k, v in qs.items():
            if k.startswith("PAGEN_") and v.isdigit() and int(v) == page_num + 1:
                return canonicalize_url(absu)
    return None


def build_bitrix_page_url(base_url: str, page_num: int) -> str:
    if page_num == 1:
        return base_url
    split = urlsplit(base_url)
    pairs = parse_qsl(split.query, keep_blank_values=True)
    keys = [k for k, _ in pairs if k.startswith("PAGEN_")]
    key = keys[0] if keys else "PAGEN_1"

    new_pairs = [(k, v) for (k, v) in pairs if k != key]
    new_pairs.append((key, str(page_num)))
    new_query = urlencode(new_pairs, doseq=True)
    return urlunsplit((split.scheme, split.netloc, split.path, new_query, split.fragment))


@dataclass(frozen=True)
class NewsItem:
    title: str
    text: str
    datatime: str
    source: str
    link: str


def fetch(session: requests.Session, url: str, timeout_s: int) -> tuple[int, str]:
    resp = session.get(url, timeout=timeout_s)
    status = resp.status_code
    if status == 404:
        return status, ""
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding or "utf-8"
    return status, resp.text


def parse_article(
    session: requests.Session,
    url: str,
    *,
    source: str,
    timeout_s: int,
    today: date,
    fetch_fn,
) -> tuple[NewsItem, Optional[date]]:
    status, html = fetch_fn(session, url, timeout_s=timeout_s)
    if status == 404:
        r = requests.Response()
        r.status_code = 404
        r.url = url
        raise requests.HTTPError("404 Not Found", response=r)
    soup = BeautifulSoup(html, "html.parser")
    title = extract_article_title(soup)
    datatime, article_date = extract_article_datetime(soup, today=today)
    if article_date is None:
        datatime = ""
    text = extract_article_text(soup)
    return (
        NewsItem(
            title=title,
            text=text,
            datatime=datatime,
            source=source,
            link=url,
        ),
        article_date,
    )


def save_csv(items: Iterable[NewsItem], path: str) -> None:
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


def save_json(items: Iterable[NewsItem], path: str) -> None:
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scrape news/publications from a site section with pagination for the last N months."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Section URL to start from.")
    parser.add_argument("--months", type=int, default=12, help="How many months back to include.")
    parser.add_argument("--out-prefix", default=str(_DATA_DIR / "neftegaz_science"), help="Output files prefix.")
    parser.add_argument("--max-pages", type=int, default=200, help="Max pagination pages.")
    parser.add_argument("--delay", type=float, default=0.7, help="Delay between requests (seconds).")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout (seconds).")
    parser.add_argument("--quiet", action="store_true", help="Disable intermediate progress logs.")
    parser.add_argument(
        "--ca-bundle",
        default="",
        help="Path to a custom CA bundle (.pem). Useful behind корпоративный proxy/антивирус, when SSL verify fails.",
    )
    parser.add_argument(
        "--no-tls-verify",
        action="store_true",
        help="Disable TLS certificate verification (insecure; last resort).",
    )
    parser.add_argument(
        "--user-agent",
        default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) site_news_scrape/1.0 (+https://openai.com)",
    )
    args = parser.parse_args()

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg, file=sys.stderr)

    today = date.today()
    cutoff = subtract_months(today, args.months)
    source = source_domain_from_base_url(args.base_url)
    allowed_hosts = {source, f"www.{source}"}

    log(f"base_url={args.base_url}")
    log(f"months={args.months}")
    log(f"cutoff={cutoff.isoformat()} (today={today.isoformat()})")

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": args.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.7,en;q=0.6",
        }
    )
    if args.ca_bundle:
        session.verify = args.ca_bundle
        log(f"TLS verify: custom CA bundle: {args.ca_bundle}")
    elif args.no_tls_verify:
        session.verify = False
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        log("TLS verify: DISABLED (--no-tls-verify)")
    else:
        log("TLS verify: enabled (default)")

    tls_auto_fallback_used = False

    def fetch_with_tls_fallback(sess: requests.Session, url: str, timeout_s: int) -> tuple[int, str]:
        nonlocal tls_auto_fallback_used
        try:
            return fetch(sess, url, timeout_s=timeout_s)
        except requests.exceptions.SSLError:
            if args.ca_bundle or args.no_tls_verify or tls_auto_fallback_used:
                raise
            tls_auto_fallback_used = True
            sess.verify = False
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            log("warn: TLS verify failed; auto-fallback to insecure mode (verify=False)")
            return fetch(sess, url, timeout_s=timeout_s)

    results: list[NewsItem] = []
    seen_links: set[str] = set()
    parsed_total = 0
    kept_total = 0

    next_url: Optional[str] = args.base_url

    for page_num in range(1, args.max_pages + 1):
        if not next_url:
            break

        page_url = next_url
        log(f"Page {page_num}: {page_url}")

        try:
            status, list_html = fetch_with_tls_fallback(session, page_url, timeout_s=args.timeout)
        except requests.exceptions.SSLError as e:
            print(
                "TLS/SSL verification failed.\n"
                "If you are behind a corporate proxy/antivirus, try one of:\n"
                f"  1) python {__file__} --base-url \"{args.base_url}\" --ca-bundle C:\\path\\to\\corp-ca.pem\n"
                f"  2) python {__file__} --base-url \"{args.base_url}\" --no-tls-verify   (insecure)\n"
                f"Original error: {e}",
                file=sys.stderr,
            )
            return 2
        except requests.exceptions.ConnectionError as e:
            print(f"Network error fetching page {page_url}: {e}", file=sys.stderr)
            return 2
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                log("Reached end of pagination (404).")
                break
            raise

        if status == 404:
            log("Reached end of pagination (404).")
            break

        links = extract_article_links(list_html, page_url=page_url, base_url=args.base_url, allowed_hosts=allowed_hosts)
        new_links = [u for u in links if u not in seen_links]
        log(f"  Found {len(new_links)} new article links")
        if not new_links:
            log("No new links on page; stopping.")
            break

        page_dates = extract_listing_dates(list_html, today=today)
        if page_dates and max(page_dates) < cutoff:
            log("Listing dates on page are older than cutoff; stopping pagination.")
            break

        parsed_ok_on_page = 0
        kept_on_page = 0
        old_on_page = 0
        undated_on_page = 0

        for idx, url in enumerate(new_links, start=1):
            seen_links.add(url)
            try:
                item, item_date = parse_article(
                    session,
                    url,
                    source=source,
                    timeout_s=args.timeout,
                    today=today,
                    fetch_fn=fetch_with_tls_fallback,
                )
            except requests.exceptions.SSLError as e:
                print(
                    "TLS/SSL verification failed while fetching an article.\n"
                    "Try --ca-bundle <path-to-ca.pem> or --no-tls-verify (insecure).\n"
                    f"URL: {url}\n"
                    f"Original error: {e}",
                    file=sys.stderr,
                )
                return 2
            except Exception as e:
                parsed_total += 1
                log(f"  [{idx}/{len(new_links)}] warn (parse failed) {url} (parsed={parsed_total}, kept={kept_total})")
                if not args.quiet:
                    print(f"[warn] failed to parse article: {url} ({e})", file=sys.stderr)
                time.sleep(args.delay)
                continue

            parsed_total += 1
            parsed_ok_on_page += 1

            if item_date is not None and item_date < cutoff:
                old_on_page += 1
                log(f"  [{idx}/{len(new_links)}] skip (old) {item_date.isoformat()} {url} (parsed={parsed_total}, kept={kept_total})")
                time.sleep(args.delay)
                continue
            if item_date is None:
                undated_on_page += 1

            results.append(item)
            kept_total += 1
            kept_on_page += 1
            log(
                f"  [{idx}/{len(new_links)}] keep {item.datatime or '(no date)'} {url} (parsed={parsed_total}, kept={kept_total})"
            )
            time.sleep(args.delay)

        if parsed_ok_on_page > 0 and kept_on_page == 0 and old_on_page == parsed_ok_on_page and undated_on_page == 0:
            log("All parsed articles on this page are older than cutoff; stopping pagination.")
            break

        # Next page discovery: prefer parsing, fallback to Bitrix-like ?PAGEN_1=N
        next_url = find_next_page_url(list_html, page_url=page_url, page_num=page_num)
        if not next_url:
            next_url = build_bitrix_page_url(args.base_url, page_num + 1)

    csv_path = f"{args.out_prefix}.csv"
    json_path = f"{args.out_prefix}.json"
    save_csv(results, csv_path)
    save_json(results, json_path)

    print(f"Saved {len(results)} items -> {csv_path}, {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
