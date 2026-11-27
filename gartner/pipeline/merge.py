"""Склейка и дедуп статей → SQLite articles."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from gartner.company import normalize_text
from gartner.config import MANUAL_SOURCES_DIR, RAW_DIR, SEED_DIR, ensure_dirs
from gartner.db import connect, init_db, utc_now


ARTICLE_FIELDS = ("title", "text", "datatime", "source", "link")

# Запрещённые синтетические URL — портал должен питаться только scrape
SYNTHETIC_LINK_MARKERS = (
    "/seed/",
    "/legacy/",
    "legacy://",
    "example.com/",
    "example.com?",
)


def is_synthetic_link(link: str) -> bool:
    low = (link or "").lower()
    return any(marker in low for marker in SYNTHETIC_LINK_MARKERS)


def article_id_from_link(link: str) -> str:
    return hashlib.sha1(link.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _load_json(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("signals", "items", "articles"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def _load_csv(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(dict(row))
    return rows


def _load_records_from_dir(directory: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not directory.exists():
        return records
    for path in sorted(directory.iterdir()):
        if path.name.startswith("last_scrape"):
            continue
        if path.suffix.lower() == ".json":
            records.extend(_load_json(path))
        elif path.suffix.lower() == ".csv":
            records.extend(_load_csv(path))
    return records


def load_raw_records(raw_dir: Path | None = None) -> list[dict[str, Any]]:
    ensure_dirs()
    records = _load_records_from_dir(raw_dir or RAW_DIR)
    # Ручные выгрузки (ЦБ, Интерфакс, …) — тот же контур, что и scrape
    if raw_dir is None:
        records.extend(_load_records_from_dir(MANUAL_SOURCES_DIR))
    return records


def load_seed_records() -> list[dict[str, Any]]:
    path = SEED_DIR / "seed_articles.json"
    if not path.exists():
        return []
    return _load_json(path)


def normalize_article(raw: dict[str, Any]) -> dict[str, Any] | None:
    title = normalize_text(raw.get("title"))
    text = normalize_text(raw.get("text") or raw.get("summary"))
    link = normalize_text(raw.get("link") or raw.get("url"))
    if not title or not text or not link:
        return None
    if is_synthetic_link(link):
        return None
    if not link.startswith("http://") and not link.startswith("https://"):
        return None
    return {
        "title": title,
        "text": text,
        "datatime": normalize_text(raw.get("datatime") or raw.get("publishedAt") or raw.get("date")),
        "source": normalize_text(raw.get("source")),
        "link": link,
    }


def merge_and_upsert(
    *,
    include_seed: bool = False,
    raw_dir: Path | None = None,
) -> dict[str, int]:
    """Дедуп по link, затем (title, datatime). Пишет в articles.

    include_seed оставлен для совместимости CLI, но синтетические ссылки
    (/seed/, /legacy/, example.com) всегда отбрасываются.
    """
    init_db()
    records = load_raw_records(raw_dir)
    # seed больше не подмешиваем — только реальный scrape из data/raw
    _ = include_seed  # явно игнорируем

    normalized: list[dict[str, Any]] = []
    rejected_synthetic = 0
    for raw in records:
        link = normalize_text(raw.get("link") or raw.get("url"))
        if is_synthetic_link(link):
            rejected_synthetic += 1
            continue
        item = normalize_article(raw)
        if item:
            normalized.append(item)

    by_link: dict[str, dict[str, Any]] = {}
    for item in normalized:
        by_link[item["link"]] = item

    # вторичный дедуп title+date
    seen_title_date: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for item in by_link.values():
        key = (item["title"].lower(), item["datatime"][:10] if item["datatime"] else "")
        if key in seen_title_date:
            continue
        seen_title_date.add(key)
        unique.append(item)

    inserted = 0
    skipped = 0
    now = utc_now()
    with connect() as conn:
        for item in unique:
            aid = article_id_from_link(item["link"])
            existing = conn.execute("SELECT article_id FROM articles WHERE link=?", (item["link"],)).fetchone()
            if existing:
                skipped += 1
                continue
            conn.execute(
                """
                INSERT INTO articles(article_id, title, text, datatime, source, link, scraped_at, processed)
                VALUES(?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (aid, item["title"], item["text"], item["datatime"], item["source"], item["link"], now),
            )
            inserted += 1

    # витрина совместимости
    export_all_merged()
    return {
        "raw": len(records),
        "normalized": len(unique),
        "inserted": inserted,
        "skipped_existing": skipped,
        "rejected_synthetic": rejected_synthetic,
    }


def export_all_merged() -> Path:
    ensure_dirs()
    out = RAW_DIR.parent / "all_merged.csv"
    with connect() as conn:
        rows = conn.execute(
            "SELECT title, text, datatime, source, link FROM articles ORDER BY datatime DESC"
        ).fetchall()
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ARTICLE_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))
    return out
