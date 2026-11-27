"""Общие куски ручных скраперов: дата, HTTP, CSV/JSON как у legacy-скриптов."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

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
DATE_RE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)")
DATE_RE_WORDS = re.compile(r"\b(\d{1,2})\s+([а-яё]+)\s+(\d{4})\b", re.IGNORECASE)


@dataclass
class NewsItem:
    title: str
    text: str
    datatime: str
    source: str
    link: str


def period_bounds(date_from: str, date_to: str) -> tuple[date, date]:
    start = date.fromisoformat((date_from or "").strip())
    end_raw = (date_to or "").strip()
    end = date.fromisoformat(end_raw) if end_raw else date.today()
    if start > end:
        raise ValueError(f"DATE_FROM {start.isoformat()} позже DATE_TO {end.isoformat()}")
    return start, end


def subtract_months(d: date, months: int) -> date:
    year = d.year
    month = d.month - months
    while month <= 0:
        month += 12
        year -= 1
    if month == 2:
        is_leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        last_day = 29 if is_leap else 28
    elif month in (1, 3, 5, 7, 8, 10, 12):
        last_day = 31
    else:
        last_day = 30
    return date(year, month, min(d.day, last_day))


def normalize_whitespace(value: str) -> str:
    value = value.replace("\u00a0", " ").replace("\u202f", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def source_domain(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def canonicalize_url(url: str) -> str:
    split = urlsplit(url)
    query_pairs = []
    for key, value in parse_qsl(split.query, keep_blank_values=True):
        low = (key or "").lower()
        if low.startswith("utm_") or low in {"gclid", "fbclid", "yclid", "erid"}:
            continue
        query_pairs.append((key, value))
    query = urlencode(query_pairs, doseq=True)
    path = re.sub(r"/{2,}", "/", split.path)
    return urlunsplit((split.scheme, split.netloc, path, query, ""))


def parse_date(text: str) -> tuple[str, Optional[date]]:
    text = normalize_whitespace(text or "")
    if not text:
        return "", None
    match = DATE_RE_ISO.search(text)
    if match:
        year, month, day = (int(match.group(i)) for i in (1, 2, 3))
        try:
            found = date(year, month, day)
        except ValueError:
            return "", None
        return found.isoformat(), found
    match = DATE_RE_DOTS.search(text)
    if match:
        day, month, year = (int(match.group(i)) for i in (1, 2, 3))
        try:
            found = date(year, month, day)
        except ValueError:
            return "", None
        return found.isoformat(), found
    match = DATE_RE_WORDS.search(text)
    if match:
        day = int(match.group(1))
        month = RU_MONTHS.get(match.group(2).lower())
        year = int(match.group(3))
        if month:
            try:
                found = date(year, month, day)
            except ValueError:
                return "", None
            return found.isoformat(), found
    return "", None


def make_session(user_agent: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.7,en;q=0.6",
        }
    )
    return session


def fetch(session: requests.Session, url: str, timeout_s: int) -> tuple[int, str]:
    response = session.get(url, timeout=timeout_s)
    if response.status_code >= 400:
        response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    return response.status_code, response.text


def text_from_selectors(soup, selectors: str) -> str:
    for tag in soup.select("script, style, noscript"):
        tag.decompose()
    parts: list[str] = []
    seen: set[str] = set()
    for el in soup.select(selectors):
        txt = normalize_whitespace(el.get_text(" ", strip=True))
        if len(txt) < 40 or txt in seen:
            continue
        seen.add(txt)
        parts.append(txt)
    return normalize_whitespace("\n".join(parts))


def save_items(items: Iterable[NewsItem], prefix: str) -> tuple[str, str]:
    rows = list(items)
    csv_path = f"{prefix}.csv"
    json_path = f"{prefix}.json"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["title", "text", "datatime", "source", "link"])
        writer.writeheader()
        for item in rows:
            writer.writerow(
                {
                    "title": item.title,
                    "text": item.text,
                    "datatime": item.datatime,
                    "source": item.source,
                    "link": item.link,
                }
            )
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(
            [
                {
                    "title": item.title,
                    "text": item.text,
                    "datatime": item.datatime,
                    "source": item.source,
                    "link": item.link,
                }
                for item in rows
            ],
            handle,
            ensure_ascii=False,
            indent=2,
        )
    return csv_path, json_path
