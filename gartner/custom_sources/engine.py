"""Фиксированный движок: применяет JSON-правила к HTML (схема A)."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from gartner.custom_sources.fetch import fetch_html_safe
from gartner.custom_sources.rules import ScrapeRules, validate_rules_dict

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

DATE_RE_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
DATE_RE_DOTS = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})")
DATE_RE_WORDS = re.compile(r"(\d{1,2})\s+([А-Яа-яёЁ]+)\s+(\d{4})")
DATE_RE_URL = re.compile(r"/(20\d{2})-(\d{2})-(\d{2})(?:/|$)")


@dataclass
class ArticleRecord:
    title: str
    text: str
    datatime: str
    source: str
    link: str

    def as_dict(self) -> dict[str, str]:
        return {
            "title": self.title,
            "text": self.text,
            "datatime": self.datatime,
            "source": self.source,
            "link": self.link,
        }


@dataclass
class EngineResult:
    ok: bool
    articles: list[ArticleRecord] = field(default_factory=list)
    error: str | None = None
    list_url: str = ""
    pages_fetched: int = 0
    links_found: int = 0


def parse_date_any(raw: str | None) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    m = DATE_RE_ISO.search(text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = DATE_RE_DOTS.search(text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            pass
    m = DATE_RE_WORDS.search(text)
    if m:
        d = int(m.group(1))
        mo = RU_MONTHS.get(m.group(2).lower())
        y = int(m.group(3))
        if mo:
            try:
                return date(y, mo, d).isoformat()
            except ValueError:
                pass
    # datetime from attr
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return ""


def infer_date_from_url(link: str) -> str:
    m = DATE_RE_URL.search(link or "")
    if not m:
        return ""
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return ""


def infer_date_from_html(soup: BeautifulSoup) -> str:
    for sel, attr in (
        ("meta[property='article:published_time']", "content"),
        ("meta[name='pubdate']", "content"),
        ("meta[itemprop='datePublished']", "content"),
        ("time[datetime]", "datetime"),
        ("time", None),
    ):
        node = soup.select_one(sel)
        if not node:
            continue
        raw = str(node.get(attr) or "") if attr else node.get_text(" ", strip=True)
        parsed = parse_date_any(raw)
        if parsed:
            return parsed
    blob = soup.get_text(" ", strip=True)[:4000]
    return parse_date_any(blob)


def _select_text(soup: BeautifulSoup, selector: str) -> str:
    if not selector:
        return ""
    node = soup.select_one(selector)
    if not node:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def extract_list_links(html: str, rules: ScrapeRules, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    seen: set[str] = set()
    base_norm = urlparse(base_url)._replace(fragment="", query="").geturl().rstrip("/")
    for node in soup.select(rules.list.article_link_selector):
        href = node.get(rules.list.link_attr) or node.get("href")
        if not href:
            continue
        abs_url = urljoin(base_url, str(href).strip())
        parsed = urlparse(abs_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        clean = parsed._replace(fragment="", query="").geturl().rstrip("/")
        if clean == base_norm:
            continue
        # отсекаем «корни» разделов без slug статьи (/news, /novosti)
        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) < 2:
            continue
        if abs_url in seen:
            continue
        seen.add(abs_url)
        links.append(abs_url)
    return links


def extract_article(html: str, rules: ScrapeRules, link: str) -> ArticleRecord | None:
    soup = BeautifulSoup(html, "html.parser")
    for sel in rules.article.remove_selectors:
        for node in soup.select(sel):
            node.decompose()
    title = _select_text(soup, rules.article.title_selector)
    text = _select_text(soup, rules.article.text_selector)
    date_raw = ""
    if rules.article.date_selector:
        node = soup.select_one(rules.article.date_selector)
        if node is not None:
            if rules.article.date_attr:
                date_raw = str(node.get(rules.article.date_attr) or "")
            if not date_raw:
                date_raw = node.get_text(" ", strip=True)
    datatime = parse_date_any(date_raw)
    if not datatime:
        datatime = infer_date_from_url(link) or infer_date_from_html(soup)
    if not title or not text or len(text) < 40:
        return None
    return ArticleRecord(
        title=title[:500],
        text=text[:50000],
        datatime=datatime,
        source=rules.source_name,
        link=link,
    )


def find_next_page(html: str, rules: ScrapeRules, current_url: str) -> str | None:
    pag = rules.list.pagination
    strategy = pag.strategy or "none"
    if strategy in {"none", "load_more"}:
        # load_more требует JS — пока не листаем
        if strategy == "none" and pag.next_selector:
            strategy = "next_link"
        else:
            return None

    if strategy == "next_link":
        sel = pag.next_selector
        if not sel:
            return None
        soup = BeautifulSoup(html, "html.parser")
        node = soup.select_one(sel)
        if not node:
            return None
        href = node.get("href")
        if not href:
            return None
        nxt = urljoin(current_url, str(href))
        return nxt if nxt != current_url else None

    if strategy == "page_query":
        param = pag.page_param or "page"
        parsed = urlparse(current_url)
        qs = parse_qs(parsed.query)
        try:
            current = int((qs.get(param) or [pag.page_start])[0])
        except (TypeError, ValueError):
            current = pag.page_start
        nxt_n = current + max(pag.page_step, 1)
        qs[param] = [str(nxt_n)]
        new_query = urlencode(qs, doseq=True)
        return urlunparse(parsed._replace(query=new_query))

    if strategy == "offset":
        param = pag.offset_param or "offset"
        parsed = urlparse(current_url)
        qs = parse_qs(parsed.query)
        try:
            current = int((qs.get(param) or [0])[0])
        except (TypeError, ValueError):
            current = 0
        nxt_n = current + max(pag.offset_step, 1)
        qs[param] = [str(nxt_n)]
        new_query = urlencode(qs, doseq=True)
        return urlunparse(parsed._replace(query=new_query))

    return None


def run_rules_engine(
    rules: ScrapeRules | dict[str, Any],
    *,
    max_articles: int = 40,
    fetch_article_bodies: bool = True,
) -> EngineResult:
    if isinstance(rules, dict):
        rules = validate_rules_dict(rules)

    list_url = rules.list_url
    html, err = fetch_html_safe(list_url)
    if err or not html:
        return EngineResult(ok=False, error=err or "пустой HTML списка", list_url=list_url)

    all_links: list[str] = []
    pages = 0
    current = list_url
    max_pages = rules.list.pagination.max_pages
    visited_pages: set[str] = set()
    prev_link_count = 0

    while current and pages < max_pages and current not in visited_pages:
        visited_pages.add(current)
        if pages == 0:
            page_html = html
        else:
            page_html, page_err = fetch_html_safe(current)
            if page_err or not page_html:
                break
        pages += 1
        before = len(all_links)
        all_links.extend(extract_list_links(page_html, rules, current))
        # page_query/offset: стоп, если страница не дала новых ссылок
        if pages > 1 and len(all_links) == before:
            break
        if len(all_links) == prev_link_count and pages > 1:
            break
        prev_link_count = len(all_links)
        nxt = find_next_page(page_html, rules, current)
        current = nxt or ""

    # unique preserve order
    uniq: list[str] = []
    seen: set[str] = set()
    for link in all_links:
        if link not in seen:
            seen.add(link)
            uniq.append(link)

    if not uniq:
        return EngineResult(
            ok=False,
            error="Не найдены ссылки на статьи по селектору списка",
            list_url=list_url,
            pages_fetched=pages,
            links_found=0,
        )

    articles: list[ArticleRecord] = []
    if not fetch_article_bodies:
        return EngineResult(
            ok=True,
            articles=[],
            list_url=list_url,
            pages_fetched=pages,
            links_found=len(uniq),
        )

    for link in uniq[:max_articles]:
        body, body_err = fetch_html_safe(link)
        if body_err or not body:
            continue
        rec = extract_article(body, rules, link)
        if rec:
            articles.append(rec)

    if not articles:
        return EngineResult(
            ok=False,
            error="Ссылки найдены, но не удалось извлечь статьи (title/text)",
            list_url=list_url,
            pages_fetched=pages,
            links_found=len(uniq),
        )

    return EngineResult(
        ok=True,
        articles=articles,
        list_url=list_url,
        pages_fetched=pages,
        links_found=len(uniq),
    )


def write_articles_raw(articles: list[ArticleRecord], out_prefix: Path) -> Path:
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    rows = [a.as_dict() for a in articles]
    json_path = Path(f"{out_prefix}.json")
    csv_path = Path(f"{out_prefix}.csv")
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    if rows:
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    return json_path
