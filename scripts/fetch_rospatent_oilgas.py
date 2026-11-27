"""Выгрузка нефтегаз-патентов РФ через openstat.rospatent.gov.ru → XLSX → JSONL."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import requests

API_URL = "https://openstat.rospatent.gov.ru/report"
OUT_DIR = ROOT / "data" / "patents" / "raw"
OUT_JSONL = ROOT / "data" / "patents" / "oiltech_patents_raw.jsonl"

FIELDS = [
    "identity",
    "publication_date",
    "title",
    "application.number",
    "application.filing_date",
    "ipc",
    "applicant",
    "inventor",
    "patentee",
    "abstract",
]

IPC = "E21B OR G01V OR C10G OR C10L OR F17D OR F17C"

PERIODS = [
    ("01.01.2024", "31.03.2024"),
    ("01.04.2024", "30.06.2024"),
    ("01.07.2024", "30.09.2024"),
    ("01.10.2024", "31.12.2024"),
    ("01.01.2025", "31.03.2025"),
    ("01.04.2025", "30.06.2025"),
    ("01.07.2025", "30.09.2025"),
]


def fetch_xlsx(start: str, end: str, limit: int = 2000) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    params = {
        "format": "xlsx",
        "limit": limit,
        "fields": FIELDS,
        "q": f"DP >={start} AND DP <={end} AND IC=({IPC})",
        "datasets": ["ru_since_1994"],
        "sort": "relevance",
        "active_page": 1,
        "active_page_session": 1,
    }
    path = OUT_DIR / f"patents_{start.replace('.', '')}_{end.replace('.', '')}.xlsx"
    print(f"GET {start}..{end} -> {path.name}", flush=True)
    r = requests.post(API_URL, data=json.dumps(params), timeout=180)
    r.raise_for_status()
    ctype = r.headers.get("content-type") or ""
    if "sheet" not in ctype and not r.content.startswith(b"PK"):
        raise RuntimeError(
            f"Не XLSX: {r.status_code} {ctype} {r.content[:200]!r}"
        )
    path.write_bytes(r.content)
    return path


COLUMN_MAP = {
    "Документ": "identity",
    "Дата\nпубликации": "publication_date",
    "Дата публикации": "publication_date",
    "Заголовок": "title",
    "№ заявки": "application_number",
    "Дата\nподачи заявки": "filing_date",
    "Дата подачи заявки": "filing_date",
    "МПК": "ipc",
    "Заявитель": "applicant",
    "Изобретатель": "inventor",
    "Патентообладатель": "patentee",
    "Реферат": "abstract",
}


def _normalize_header(value: object) -> str:
    text = str(value or "").strip().replace("\r", "")
    return text


def xlsx_to_records(path: Path) -> list[dict]:
    """В XLSX Роспатента сверху служебные строки; таблица начинается с колонки «Документ»."""
    raw = pd.read_excel(path, header=None)
    header_row = None
    for idx in range(min(20, len(raw))):
        cell = _normalize_header(raw.iloc[idx, 0])
        if cell == "Документ":
            header_row = idx
            break
    if header_row is None:
        raise RuntimeError(f"Не найден заголовок таблицы в {path.name}")

    headers = [_normalize_header(raw.iloc[header_row, col]) for col in range(raw.shape[1])]
    records: list[dict] = []
    for idx in range(header_row + 1, len(raw)):
        identity = raw.iloc[idx, 0]
        if pd.isna(identity) or not str(identity).strip():
            continue
        row: dict = {}
        for col, header in enumerate(headers):
            if not header or header.startswith("Unnamed"):
                continue
            key = COLUMN_MAP.get(header, header)
            value = raw.iloc[idx, col]
            if pd.isna(value):
                row[key] = None
            else:
                row[key] = value if not hasattr(value, "isoformat") else value.isoformat()[:10]
                if isinstance(row[key], str):
                    row[key] = row[key].strip()
        if row.get("identity"):
            records.append(row)
    return records


def write_jsonl(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for item in rows:
            f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")


def rebuild_from_raw() -> list[dict]:
    seen: set[str] = set()
    rows: list[dict] = []
    files = sorted(OUT_DIR.glob("patents_*.xlsx"))
    if not files:
        raise FileNotFoundError(f"Нет xlsx в {OUT_DIR}")
    for path in files:
        batch = xlsx_to_records(path)
        print(f"PARSE {path.name}: {len(batch)}", flush=True)
        for item in batch:
            key = str(item.get("identity") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append(item)
    return rows


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rebuild-only",
        action="store_true",
        help="Не качать заново: пересобрать JSONL из уже скачанных xlsx",
    )
    args = parser.parse_args()

    if args.rebuild_only:
        rows = rebuild_from_raw()
        write_jsonl(rows, OUT_JSONL)
        print(f"Уникальных: {len(rows)} -> {OUT_JSONL}", flush=True)
        return 0

    seen: set[str] = set()
    rows: list[dict] = []
    for start, end in PERIODS:
        path = fetch_xlsx(start, end)
        batch = xlsx_to_records(path)
        print(f"  строк: {len(batch)}", flush=True)
        if len(batch) >= 2000:
            print("  WARN: упёрлись в limit=2000 — дроби период ещё мельче", flush=True)
        for item in batch:
            key = str(item.get("identity") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append(item)
        time.sleep(1.5)

    write_jsonl(rows, OUT_JSONL)
    print(f"Уникальных: {len(rows)} -> {OUT_JSONL}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
