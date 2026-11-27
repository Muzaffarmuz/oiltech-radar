"""Выгрузка нефтегаз-патентов РФ через Search Platform → JSONL.

Документация Open API указывает /patsearch/v0.2, но этот шлюз сейчас часто
отдаёт 504. Рабочий endpoint UI/платформы:
  POST https://searchplatform.rospatent.gov.ru/search

База: SEARCHPLATFORM_API_BASE (по умолчанию https://searchplatform.rospatent.gov.ru)
Ключ: SEARCHPLATFORM_API_KEY (из UI «Генерирование ключей»)

Формат строк совместим с scripts/import_patents.py и fetch_rospatent_oilgas.py.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_JSONL = ROOT / "data" / "patents" / "oiltech_patents_raw.jsonl"
OUT_RAW_DIR = ROOT / "data" / "patents" / "searchplatform"
IPC = "E21B OR G01V OR C10G OR C10L OR F17D OR F17C"
_TAG_RE = re.compile(r"<[^>]+>")


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _session() -> requests.Session:
    """Обходим сломанный системный прокси; ретраи на обрывы TLS/прокси."""
    session = requests.Session()
    session.trust_env = False
    session.headers.update(
        {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "OilTechRadar/4 searchplatform-fetch",
        }
    )
    return session


def _api_config() -> tuple[str, str]:
    _load_dotenv()
    key = (os.environ.get("SEARCHPLATFORM_API_KEY") or "").strip()
    if not key:
        raise SystemExit(
            "Нет SEARCHPLATFORM_API_KEY в .env "
            "(JWT из https://searchplatform.rospatent.gov.ru → Генерирование ключей)"
        )
    base = (
        os.environ.get("SEARCHPLATFORM_API_BASE")
        or "https://searchplatform.rospatent.gov.ru"
    ).rstrip("/")
    # Старый Open API path часто 504 — если в .env остался /patsearch/v0.2, срезаем.
    if base.endswith("/patsearch/v0.2"):
        base = base[: -len("/patsearch/v0.2")]
    return key, base


def _strip_tags(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = _TAG_RE.sub("", str(text))
    cleaned = cleaned.replace("&nbsp;", " ").replace("&amp;", "&").strip()
    return cleaned or None


def _names(items: Any) -> str | None:
    if not items:
        return None
    if isinstance(items, str):
        return items.strip() or None
    names: list[str] = []
    for item in items:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        else:
            name = str(item or "").strip()
        if name:
            names.append(name)
    return "; ".join(names) if names else None


def _ipc_from_common(common: dict) -> str | None:
    ipc = (common.get("classification") or {}).get("ipc") or []
    codes: list[str] = []
    for item in ipc:
        if isinstance(item, dict):
            code = str(item.get("fullname") or "").strip()
        else:
            code = str(item or "").strip()
        if code and code not in codes:
            codes.append(code)
    return "; ".join(codes) if codes else None


def _biblio_lang(hit: dict) -> dict:
    biblio = hit.get("biblio") or {}
    for lang in ("ru", "en"):
        block = biblio.get(lang)
        if isinstance(block, dict) and block:
            return block
    for block in biblio.values():
        if isinstance(block, dict) and block:
            return block
    return {}


def hit_to_record(hit: dict) -> dict | None:
    """Маппинг hit POST /search → плоская запись как в openstat JSONL."""
    common = hit.get("common") or {}
    snippet = hit.get("snippet") or {}
    biblio = _biblio_lang(hit)

    office = str(common.get("publishing_office") or "RU").upper()
    number = str(common.get("document_number") or "").lstrip("0") or str(
        common.get("document_number") or ""
    )
    kind = str(common.get("kind") or "").strip()
    if not number:
        return None

    identity = f"{office} {number} {kind}".strip()
    pub = str(common.get("publication_date") or "").replace(".", "-")[:10] or None
    app = common.get("application") or {}
    filing = str(app.get("filing_date") or "").replace(".", "-")[:10] or None
    app_number = str(app.get("number") or "") or None

    title = _strip_tags(biblio.get("title") or snippet.get("title"))
    abstract = _strip_tags(snippet.get("description") or biblio.get("abstract"))
    ipc = _ipc_from_common(common) or _strip_tags(
        (snippet.get("classification") or {}).get("ipc")
        if isinstance(snippet.get("classification"), dict)
        else snippet.get("classification")
    )

    applicant = _names(biblio.get("applicant")) or _strip_tags(snippet.get("applicant"))
    inventor = _names(biblio.get("inventor")) or _strip_tags(snippet.get("inventor"))
    patentee = _names(biblio.get("patentee")) or _strip_tags(snippet.get("patentee"))

    return {
        "identity": identity,
        "publication_date": pub,
        "title": title,
        "application_number": app_number,
        "filing_date": filing,
        "ipc": ipc,
        "applicant": applicant,
        "inventor": inventor,
        "patentee": patentee,
        "abstract": abstract,
        "doc_id": hit.get("id"),
        "dataset": hit.get("dataset"),
        "source": "searchplatform",
    }


def _request_with_retries(
    session: requests.Session,
    method: str,
    url: str,
    *,
    headers: dict,
    json_body: dict | None = None,
    timeout: int = 120,
    retries: int = 5,
) -> requests.Response:
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.request(
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=timeout,
            )
            if resp.status_code in {429, 502, 503, 504}:
                wait = min(2 ** attempt, 30)
                print(f"  HTTP {resp.status_code}, sleep {wait}s ({attempt}/{retries})", flush=True)
                time.sleep(wait)
                continue
            return resp
        except (requests.ConnectionError, requests.Timeout) as exc:
            last = exc
            wait = min(2 ** attempt, 30)
            print(f"  net error: {exc!r}; sleep {wait}s ({attempt}/{retries})", flush=True)
            time.sleep(wait)
    raise SystemExit(f"Не удалось достучаться до API после {retries} попыток: {last!r}")


def search_page(
    session: requests.Session,
    *,
    key: str,
    base: str,
    query: str,
    limit: int,
    offset: int,
    sort: str = "publication_date:desc",
) -> dict:
    # cache-buster как в UI (?t=...)
    url = f"{base}/search?t={int(time.time() * 1000)}"
    headers = {"Authorization": f"Bearer {key}"}
    body = {
        "q": query,
        "datasets": ["ru_since_1994"],
        "limit": limit,
        "offset": offset,
        "sort": sort,
    }
    resp = _request_with_retries(session, "POST", url, headers=headers, json_body=body)
    if resp.status_code == 401:
        raise SystemExit("401 Unauthorized — проверьте SEARCHPLATFORM_API_KEY")
    if resp.status_code >= 400:
        raise SystemExit(f"HTTP {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def build_query(date_from: str, date_to: str) -> str:
    """date_from/to в ISO YYYY-MM-DD."""
    return f"IC=({IPC}) AND DP:[{date_from} TO {date_to}]"


def fetch_range(
    session: requests.Session,
    *,
    key: str,
    base: str,
    date_from: str,
    date_to: str,
    page_size: int = 100,
    max_pages: int = 200,
    sleep_s: float = 0.4,
) -> list[dict]:
    query = build_query(date_from, date_to)
    print(f"SEARCH {date_from}..{date_to}", flush=True)
    rows: list[dict] = []
    seen: set[str] = set()
    offset = 0
    total = None
    for page in range(max_pages):
        data = search_page(
            session,
            key=key,
            base=base,
            query=query,
            limit=page_size,
            offset=offset,
        )
        if total is None:
            total = int(data.get("total") or 0)
            available = int(data.get("available") or 0)
            print(f"  total={total} available={available}", flush=True)
        hits = data.get("hits") or []
        if not hits:
            break
        for hit in hits:
            rec = hit_to_record(hit)
            if not rec:
                continue
            key_id = str(rec.get("doc_id") or rec.get("identity") or "")
            if not key_id or key_id in seen:
                continue
            seen.add(key_id)
            rows.append(rec)
        offset += len(hits)
        print(f"  page {page + 1}: +{len(hits)} (unique={len(rows)})", flush=True)
        if offset >= int(data.get("available") or 0) or len(hits) < page_size:
            break
        time.sleep(sleep_s)
    return rows


def merge_jsonl(path: Path, new_rows: list[dict]) -> int:
    """Дописать/обновить JSONL по identity; вернуть итоговый размер."""
    by_id: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            identity = str(item.get("identity") or "").strip()
            if identity:
                by_id[identity] = item
    for item in new_rows:
        identity = str(item.get("identity") or "").strip()
        if identity:
            by_id[identity] = item
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for item in by_id.values():
            f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
    return len(by_id)


def default_periods() -> list[tuple[str, str]]:
    """Кварталы 2024–2026 (свежие данные поверх openstat)."""
    return [
        ("2024-01-01", "2024-03-31"),
        ("2024-04-01", "2024-06-30"),
        ("2024-07-01", "2024-09-30"),
        ("2024-10-01", "2024-12-31"),
        ("2025-01-01", "2025-03-31"),
        ("2025-04-01", "2025-06-30"),
        ("2025-07-01", "2025-09-30"),
        ("2025-10-01", "2025-12-31"),
        ("2026-01-01", "2026-03-31"),
        ("2026-04-01", "2026-06-30"),
        ("2026-07-01", "2026-09-30"),
        ("2026-10-01", "2026-12-31"),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch patents from Rospatent Search Platform")
    parser.add_argument("--from", dest="date_from", help="YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", help="YYYY-MM-DD")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--probe", action="store_true", help="Один тестовый запрос и выход")
    parser.add_argument(
        "--out",
        type=Path,
        default=OUT_JSONL,
        help="Путь JSONL (по умолчанию oiltech_patents_raw.jsonl)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Перезаписать JSONL только новыми данными (без merge со старым)",
    )
    args = parser.parse_args()

    key, base = _api_config()
    session = _session()

    if args.probe:
        data = search_page(
            session,
            key=key,
            base=base,
            query=f"IC=({IPC})",
            limit=1,
            offset=0,
        )
        print(json.dumps({
            "total": data.get("total"),
            "available": data.get("available"),
            "sample": hit_to_record((data.get("hits") or [{}])[0]) if data.get("hits") else None,
        }, ensure_ascii=False, indent=2))
        return 0

    periods: list[tuple[str, str]]
    if args.date_from and args.date_to:
        periods = [(args.date_from, args.date_to)]
    elif args.date_from or args.date_to:
        raise SystemExit("Укажите оба --from и --to")
    else:
        periods = default_periods()

    all_rows: list[dict] = []
    OUT_RAW_DIR.mkdir(parents=True, exist_ok=True)
    for date_from, date_to in periods:
        batch = fetch_range(
            session,
            key=key,
            base=base,
            date_from=date_from,
            date_to=date_to,
            page_size=args.page_size,
        )
        dump = OUT_RAW_DIR / f"hits_{date_from}_{date_to}.jsonl"
        with dump.open("w", encoding="utf-8") as f:
            for item in batch:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"  saved {len(batch)} -> {dump.name}", flush=True)
        all_rows.extend(batch)

    if args.replace:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as f:
            for item in all_rows:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        total = len(all_rows)
    else:
        total = merge_jsonl(args.out, all_rows)

    print(f"Готово: новых/обновлённых пачек {len(all_rows)}, в JSONL уникальных {total} -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
