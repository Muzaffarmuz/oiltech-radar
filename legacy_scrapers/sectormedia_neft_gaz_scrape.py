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
from typing import Any, Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

import requests
from bs4 import BeautifulSoup


DEFAULT_BASE_URL = "https://sectormedia.ru/news/neft-i-gaz/"


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
DATE_RE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[T\s](\d{2}):(\d{2})(?::(\d{2}))?)?\b")
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
    split = urlsplit(url)
    query_pairs = []
    for key, value in parse_qsl(split.query, keep_blank_values=True):
        key_lower = key.lower()
        if key_lower.startswith("utm_"):
            continue
        if key_lower in {"gclid", "fbclid", "yclid", "erid"}:
            continue
        query_pairs.append((key, value))
    query = urlencode(query_pairs, doseq=True)
    return urlunsplit((split.scheme, split.netloc, split.path, query, ""))


def parse_date_from_text(text: str, *, today: date) -> tuple[str, Optional[date]]:
    text = normalize_whitespace(text)
    if not text:
        return "", None

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

    match = DATE_RE_ISO.search(text)
    if match:
        y, m, d, hh, mm, ss = match.groups()
        try:
            parsed_date = date(int(y), int(m), int(d))
        except ValueError:
            return "", None
        if hh and mm:
            sec = int(ss) if ss else 0
            return datetime(parsed_date.year, parsed_date.month, parsed_date.day, int(hh), int(mm), sec).isoformat(), parsed_date
        return parsed_date.isoformat(), parsed_date

    match = DATE_RE_DOTS.search(text)
    if match:
        day_s, month_s, year_s = match.groups()
        try:
            d = date(int(year_s), int(month_s), int(day_s))
        except ValueError:
            return "", None
        tm = TIME_RE.search(text)
        if tm:
            hh, mm = int(tm.group(1)), int(tm.group(2))
            return datetime(d.year, d.month, d.day, hh, mm).isoformat(), d
        return d.isoformat(), d

    match = DATE_RE_WORDS_Y.search(text)
    if match:
        day_s, month_word, year_s = match.groups()
        month = RU_MONTHS.get(month_word.lower())
        if not month:
            return "", None
        try:
            d = date(int(year_s), month, int(day_s))
        except ValueError:
            return "", None
        tm = TIME_RE.search(text)
        if tm:
            hh, mm = int(tm.group(1)), int(tm.group(2))
            return datetime(d.year, d.month, d.day, hh, mm).isoformat(), d
        return d.isoformat(), d

    match = DATE_RE_WORDS_NOY.search(text)
    if match:
        day_s, month_word = match.groups()
        month = RU_MONTHS.get(month_word.lower())
        if not month:
            return "", None
        year_guess = today.year
        if month > today.month:
            year_guess -= 1
        try:
            d = date(year_guess, month, int(day_s))
        except ValueError:
            return "", None
        tm = TIME_RE.search(text)
        if tm:
            hh, mm = int(tm.group(1)), int(tm.group(2))
            return datetime(d.year, d.month, d.day, hh, mm).isoformat(), d
        return d.isoformat(), d

    return "", None


def _extract_date_from_json_ld_obj(obj: Any, *, today: date) -> tuple[str, Optional[date]]:
    if isinstance(obj, dict):
        for key in ("datePublished", "dateCreated", "uploadDate", "dateModified"):
            value = obj.get(key)
            if isinstance(value, str):
                dt, d = parse_date_from_text(value, today=today)
                if d is not None:
                    return dt, d
        for value in obj.values():
            dt, d = _extract_date_from_json_ld_obj(value, today=today)
            if d is not None:
                return dt, d
    elif isinstance(obj, list):
        for item in obj:
            dt, d = _extract_date_from_json_ld_obj(item, today=today)
            if d is not None:
                return dt, d
    return "", None


def pick_main_container(soup: BeautifulSoup):
    for selector in (
        "article",
        ".post-content",
        ".entry-content",
        ".single-content",
        ".news-detail",
        ".content",
        "main",
        "body",
    ):
        element = soup.select_one(selector)
        if element is not None:
            return element
    return soup


def extract_article_title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        title = normalize_whitespace(h1.get_text(" ", strip=True))
        if title:
            return title
    if soup.title:
        return normalize_whitespace(soup.title.get_text(" ", strip=True))
    return ""


def extract_article_datetime(soup: BeautifulSoup, *, today: date) -> tuple[str, Optional[date]]:
    for time_selector in ("time[datetime]", "[itemprop='datePublished'][datetime]", "[datetime]"):
        time_tag = soup.select_one(time_selector)
        if time_tag is None:
            continue
        dt_attr = (time_tag.get("datetime") or "").strip().replace("Z", "+00:00")
        if not dt_attr:
            continue
        dt, d = parse_date_from_text(dt_attr, today=today)
        if d is not None:
            return dt, d

    for meta_selector in (
        "meta[property='article:published_time']",
        "meta[property='og:published_time']",
        "meta[name='article:published_time']",
        "meta[name='og:published_time']",
        "meta[name='publish_date']",
        "meta[name='pubdate']",
        "meta[itemprop='datePublished']",
    ):
        meta = soup.select_one(meta_selector)
        if meta is None:
            continue
        val = (meta.get("content") or "").strip()
        if not val:
            continue
        dt, d = parse_date_from_text(val, today=today)
        if d is not None:
            return dt, d

    for script in soup.select("script[type='application/ld+json']"):
        payload = script.string or script.get_text(" ", strip=True)
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except Exception:
            continue
        dt, d = _extract_date_from_json_ld_obj(data, today=today)
        if d is not None:
            return dt, d

    for selector in (
        "time",
        "p[style*='text-align: right']",
        "div[style*='text-align: right']",
        ".main-annonce__heading-date",
        ".page__date",
        ".date",
        ".post-date",
        ".entry-date",
        ".meta-date",
        ".article-date",
        ".news-date",
        ".detail-date",
        ".published-date",
        ".published",
    ):
        element = soup.select_one(selector)
        if element is None:
            continue
        dt, d = parse_date_from_text(element.get_text(" ", strip=True), today=today)
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
        ".breadcrumbs, .breadcrumb, .share, .social, .related, .recommend, .post-tags, .tags, .comments, .comment, .sidebar"
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
    for element in container.select("p, h2, h3, h4, li, blockquote"):
        txt = normalize_whitespace(element.get_text(" ", strip=True))
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


def looks_like_article_url(path: str, *, base_path: str, base_url: str) -> bool:
    clean = (path or "/").strip()
    if "/page/" in clean:
        return False

    parts = [p for p in clean.strip("/").split("/") if p]
    if len(parts) < 2:
        return False
    if parts[0] != "news":
        return False

    # Exclude pure section/category pages like /news/neft-i-gaz/ or /news/sobytiya-neft-i-gaz/
    if len(parts) == 2:
        return False

    # Keep links from the target branch OR links that include the target topic slug.
    topic_slug = (urlsplit(base_url).path or "/").strip("/").split("/")[-1].lower()
    joined = "/".join(parts).lower()
    if clean.startswith(base_path):
        return True
    if topic_slug and topic_slug in joined:
        return True
    return False


def extract_article_links(list_html: str, *, page_url: str, base_url: str, allowed_hosts: set[str]) -> list[str]:
    soup = BeautifulSoup(list_html, "html.parser")
    base_path = (urlsplit(base_url).path or "/").rstrip("/") + "/"

    candidates: list[str] = []
    for a in soup.select(".item-card a.page__link[href]"):
        href = a.get("href")
        if href:
            candidates.append(urljoin(page_url, href))

    for selector in (
        "article a[href]",
        ".news-item a[href]",
        ".post a[href]",
        ".entry-title a[href]",
        "h2 a[href]",
        "h3 a[href]",
    ):
        for a in soup.select(selector):
            href = a.get("href")
            if href:
                candidates.append(urljoin(page_url, href))

    if not candidates:
        container = soup.select_one("main") or soup
        for a in container.select("a[href]"):
            href = a.get("href")
            if href:
                candidates.append(urljoin(page_url, href))

    out: list[str] = []
    seen: set[str] = set()
    for raw_url in candidates:
        url = canonicalize_url(raw_url.split("#", 1)[0])
        split = urlsplit(url)
        if split.scheme not in {"http", "https"}:
            continue
        if not is_same_site(url, allowed_hosts=allowed_hosts):
            continue
        if not looks_like_article_url(split.path or "/", base_path=base_path, base_url=base_url):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def extract_listing_entries(
    list_html: str,
    *,
    page_url: str,
    base_url: str,
    allowed_hosts: set[str],
    today: date,
) -> list["ListingEntry"]:
    soup = BeautifulSoup(list_html, "html.parser")
    base_path = (urlsplit(base_url).path or "/").rstrip("/") + "/"

    out: list[ListingEntry] = []
    seen: set[str] = set()

    cards = soup.select(".item-card")
    for card in cards:
        link_tag = card.select_one("a.page__link[href]") or card.select_one("a[href]")
        if link_tag is None:
            continue
        href = link_tag.get("href")
        if not href:
            continue
        url = canonicalize_url(urljoin(page_url, href).split("#", 1)[0])
        split = urlsplit(url)
        if split.scheme not in {"http", "https"}:
            continue
        if not is_same_site(url, allowed_hosts=allowed_hosts):
            continue
        if not looks_like_article_url(split.path or "/", base_path=base_path, base_url=base_url):
            continue
        if url in seen:
            continue
        seen.add(url)

        listed_datatime = ""
        listed_date: Optional[date] = None
        date_node = card.select_one(".main-annonce__heading-date, .date, time")
        if date_node is not None:
            listed_datatime, listed_date = parse_date_from_text(date_node.get_text(" ", strip=True), today=today)
        out.append(ListingEntry(link=url, listed_datatime=listed_datatime, listed_date=listed_date))

    if out:
        return out

    # Fallback for unexpected list templates.
    candidates: list[str] = []
    container = soup.select_one("main") or soup
    for a in container.select("a[href]"):
        href = a.get("href")
        if href:
            candidates.append(urljoin(page_url, href))
    for raw_url in candidates:
        url = canonicalize_url(raw_url.split("#", 1)[0])
        split = urlsplit(url)
        if split.scheme not in {"http", "https"}:
            continue
        if not is_same_site(url, allowed_hosts=allowed_hosts):
            continue
        if not looks_like_article_url(split.path or "/", base_path=base_path, base_url=base_url):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(ListingEntry(link=url, listed_datatime="", listed_date=None))
    return out


def extract_listing_dates(list_html: str, *, today: date) -> list[date]:
    soup = BeautifulSoup(list_html, "html.parser")
    result: list[date] = []
    for selector in (".main-annonce__heading-date", ".date", "time", ".post-date", ".entry-date", ".meta-date"):
        for element in soup.select(selector):
            _, d = parse_date_from_text(element.get_text(" ", strip=True), today=today)
            if d is not None:
                result.append(d)
    return result


def find_next_page_url(list_html: str, *, page_url: str, page_num: int) -> Optional[str]:
    soup = BeautifulSoup(list_html, "html.parser")
    rel_next = soup.select_one('link[rel="next"][href], a[rel="next"][href]')
    if rel_next is not None:
        href = rel_next.get("href")
        if href:
            return canonicalize_url(urljoin(page_url, href))

    for selector in ("a.next[href]", "a.pagination-next[href]", "a[aria-label*=Next][href]"):
        a = soup.select_one(selector)
        if a is not None and a.get("href"):
            return canonicalize_url(urljoin(page_url, a.get("href")))

    # Fallback: search for /page/N+1/ links.
    target = f"/page/{page_num + 1}/"
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        if target in href:
            return canonicalize_url(urljoin(page_url, href))
    return None


def find_load_more_candidates(list_html: str, *, page_url: str, base_url: str, page_num: int) -> list[str]:
    soup = BeautifulSoup(list_html, "html.parser")
    out: list[str] = []

    # Button-based pagination (e.g. "Показать ещё")
    btn = soup.select_one("button.page__toggle")
    if btn is not None:
        attrs = getattr(btn, "attrs", {}) or {}
        for key in ("data-url", "data-href", "data-next-url", "data-load-url"):
            value = attrs.get(key)
            if value:
                out.append(canonicalize_url(urljoin(page_url, str(value))))

        # Infer URL from page pointer in data attrs, if present.
        data_page = attrs.get("data-page") or attrs.get("data-next-page")
        if isinstance(data_page, str) and data_page.isdigit():
            n = int(data_page) + 1
            out.append(build_page_url(base_url, n))
            out.append(build_bitrix_page_url(base_url, n))
            out.append(build_bitrix_page_url(base_url, n, ajax=True))

    # Generic fallback by expected page number.
    next_num = page_num + 1
    out.append(build_page_url(base_url, next_num))
    out.append(build_bitrix_page_url(base_url, next_num))
    out.append(build_bitrix_page_url(base_url, next_num, ajax=True))

    # Dedup while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for url in out:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def build_page_url(base_url: str, page_num: int) -> str:
    if page_num <= 1:
        return base_url

    split = urlsplit(base_url)
    path = split.path or "/"
    if not path.endswith("/"):
        path += "/"
    path_page = f"{path}page/{page_num}/"

    # Keep query params if base_url already has them.
    return urlunsplit((split.scheme, split.netloc, path_page, split.query, split.fragment))


def build_bitrix_page_url(base_url: str, page_num: int, ajax: bool = False) -> str:
    split = urlsplit(base_url)
    pairs = parse_qsl(split.query, keep_blank_values=True)
    key_candidates = [k for k, _ in pairs if k.upper().startswith("PAGEN_")]
    page_key = key_candidates[0] if key_candidates else "PAGEN_1"

    new_pairs = [(k, v) for (k, v) in pairs if k != page_key and k.lower() not in {"ajax", "is_ajax"}]
    new_pairs.append((page_key, str(page_num)))
    if ajax:
        new_pairs.append(("ajax", "Y"))
    new_query = urlencode(new_pairs, doseq=True)
    return urlunsplit((split.scheme, split.netloc, split.path, new_query, split.fragment))


@dataclass(frozen=True)
class NewsItem:
    title: str
    text: str
    datatime: str
    source: str
    link: str


@dataclass(frozen=True)
class ListingEntry:
    link: str
    listed_datatime: str
    listed_date: Optional[date]


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
    datatime, item_date = extract_article_datetime(soup, today=today)
    if item_date is None:
        datatime = ""
    text = extract_article_text(soup)
    return NewsItem(title=title, text=text, datatime=datatime, source=source, link=url), item_date


def save_csv(items: Iterable[NewsItem], path: str) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["title", "text", "datatime", "source", "link"])
        writer.writeheader()
        for item in items:
            writer.writerow(
                {
                    "title": item.title,
                    "text": item.text,
                    "datatime": item.datatime,
                    "source": item.source,
                    "link": item.link,
                }
            )


def save_json(items: Iterable[NewsItem], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            [
                {
                    "title": item.title,
                    "text": item.text,
                    "datatime": item.datatime,
                    "source": item.source,
                    "link": item.link,
                }
                for item in items
            ],
            f,
            ensure_ascii=False,
            indent=2,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scrape sectormedia news section with pagination for the last N months."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Section URL to start from.")
    parser.add_argument("--months", type=int, default=12, help="How many months back to include.")
    parser.add_argument("--out-prefix", default=str(_DATA_DIR / "sectormedia_neft_gaz"), help="Output files prefix.")
    parser.add_argument("--max-pages", type=int, default=200, help="Max pagination pages.")
    parser.add_argument("--delay", type=float, default=0.7, help="Delay between requests (seconds).")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout (seconds).")
    parser.add_argument("--quiet", action="store_true", help="Disable intermediate progress logs.")
    parser.add_argument("--ca-bundle", default="", help="Path to custom CA bundle (.pem).")
    parser.add_argument("--no-tls-verify", action="store_true", help="Disable TLS cert verification (insecure).")
    parser.add_argument(
        "--user-agent",
        default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) sectormedia_scrape/1.0 (+https://openai.com)",
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
    next_candidates: list[str] = [args.base_url]
    seen_page_urls: set[str] = set()

    for page_num in range(1, args.max_pages + 1):
        if not next_candidates:
            break

        page_url: Optional[str] = None
        list_html = ""
        while next_candidates:
            candidate = next_candidates.pop(0)
            if candidate in seen_page_urls:
                continue
            log(f"Page {page_num}: {candidate}")
            try:
                status, html = fetch_with_tls_fallback(session, candidate, timeout_s=args.timeout)
            except requests.exceptions.SSLError as e:
                print(
                    "TLS/SSL verification failed.\n"
                    f"Try --ca-bundle <path-to-ca.pem> or --no-tls-verify (insecure).\nOriginal error: {e}",
                    file=sys.stderr,
                )
                return 2
            except requests.exceptions.ConnectionError as e:
                print(f"Network error fetching page {candidate}: {e}", file=sys.stderr)
                return 2
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 404:
                    log(f"  candidate 404: {candidate}")
                    continue
                raise

            if status == 404:
                log(f"  candidate 404: {candidate}")
                continue

            page_url = candidate
            list_html = html
            seen_page_urls.add(candidate)
            break

        if page_url is None:
            log("Reached end of pagination (all candidates returned 404/visited).")
            break

        entries = extract_listing_entries(
            list_html,
            page_url=page_url,
            base_url=args.base_url,
            allowed_hosts=allowed_hosts,
            today=today,
        )
        new_entries = [entry for entry in entries if entry.link not in seen_links]
        log(f"  Found {len(new_entries)} new article links")
        if not new_entries:
            log("No new links on page; stopping.")
            break

        page_dates = [entry.listed_date for entry in new_entries if entry.listed_date is not None]
        if not page_dates:
            page_dates = extract_listing_dates(list_html, today=today)
        if page_dates and max(page_dates) < cutoff:
            log("Listing dates on page are older than cutoff; stopping pagination.")
            break

        parsed_ok_on_page = 0
        kept_on_page = 0
        old_on_page = 0
        undated_on_page = 0

        for idx, entry in enumerate(new_entries, start=1):
            url = entry.link
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
                    f"URL: {url}\nOriginal error: {e}\n"
                    "Try --ca-bundle <path-to-ca.pem> or --no-tls-verify (insecure).",
                    file=sys.stderr,
                )
                return 2
            except Exception as e:
                parsed_total += 1
                log(f"  [{idx}/{len(new_entries)}] warn (parse failed) {url} (parsed={parsed_total}, kept={kept_total})")
                if not args.quiet:
                    print(f"[warn] failed to parse article: {url} ({e})", file=sys.stderr)
                time.sleep(args.delay)
                continue

            parsed_total += 1
            parsed_ok_on_page += 1

            if item_date is not None and item_date < cutoff:
                old_on_page += 1
                log(f"  [{idx}/{len(new_entries)}] skip (old) {item_date.isoformat()} {url} (parsed={parsed_total}, kept={kept_total})")
                time.sleep(args.delay)
                continue

            if item_date is None:
                undated_on_page += 1

            results.append(item)
            kept_total += 1
            kept_on_page += 1
            log(f"  [{idx}/{len(new_entries)}] keep {item.datatime or '(no date)'} {url} (parsed={parsed_total}, kept={kept_total})")
            time.sleep(args.delay)

        if parsed_ok_on_page > 0 and kept_on_page == 0 and old_on_page == parsed_ok_on_page and undated_on_page == 0:
            log("All parsed articles on this page are older than cutoff; stopping pagination.")
            break

        next_candidates = []
        next_url = find_next_page_url(list_html, page_url=page_url, page_num=page_num)
        if next_url:
            next_candidates.append(next_url)
        for candidate in find_load_more_candidates(
            list_html,
            page_url=page_url,
            base_url=args.base_url,
            page_num=page_num,
        ):
            if candidate not in next_candidates and candidate not in seen_page_urls:
                next_candidates.append(candidate)

    csv_path = f"{args.out_prefix}.csv"
    json_path = f"{args.out_prefix}.json"
    save_csv(results, csv_path)
    save_json(results, json_path)
    print(f"Saved {len(results)} items -> {csv_path}, {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
