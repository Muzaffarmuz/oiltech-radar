"""Импорт oiltech_patents_raw.jsonl → patents + связи со science-статьями."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gartner.db import connect, init_db, utc_now
from gartner.patents import (
    directions_from_patent_row,
    extract_patent_ids_from_text,
    fips_url,
    normalize_patent_id,
)

DEFAULT_JSONL = ROOT / "data" / "patents" / "oiltech_patents_raw.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def upsert_patents(rows: list[dict]) -> dict[str, int]:
    init_db()
    now = utc_now()
    inserted = 0
    updated = 0
    skipped = 0
    fine_counter: Counter[str] = Counter()
    with connect() as conn:
        for raw in rows:
            identity = str(raw.get("identity") or "").strip()
            patent_id = normalize_patent_id(identity)
            if not patent_id:
                skipped += 1
                continue
            directions = directions_from_patent_row(raw)
            for label in directions.get("fine") or []:
                fine_counter[label] += 1
            payload = {
                "patent_id": patent_id,
                "identity": identity,
                "title": str(raw.get("title") or "")[:2000] or None,
                "abstract": str(raw.get("abstract") or "")[:8000] or None,
                "publication_date": str(raw.get("publication_date") or "")[:32] or None,
                "filing_date": str(raw.get("filing_date") or "")[:32] or None,
                "application_number": str(raw.get("application_number") or "")[:64] or None,
                "ipc": str(raw.get("ipc") or "")[:500] or None,
                "applicant": str(raw.get("applicant") or "")[:1000] or None,
                "inventor": str(raw.get("inventor") or "")[:1000] or None,
                "patentee": str(raw.get("patentee") or "")[:1000] or None,
                "source_url": fips_url(patent_id, identity) or None,
                "directions_json": json.dumps(directions, ensure_ascii=False),
                "imported_at": now,
            }
            exists = conn.execute(
                "SELECT 1 FROM patents WHERE patent_id=?", (patent_id,)
            ).fetchone()
            conn.execute(
                """
                INSERT INTO patents (
                    patent_id, identity, title, abstract, publication_date, filing_date,
                    application_number, ipc, applicant, inventor, patentee, source_url,
                    directions_json, imported_at
                ) VALUES (
                    :patent_id, :identity, :title, :abstract, :publication_date, :filing_date,
                    :application_number, :ipc, :applicant, :inventor, :patentee, :source_url,
                    :directions_json, :imported_at
                )
                ON CONFLICT(patent_id) DO UPDATE SET
                    identity=excluded.identity,
                    title=excluded.title,
                    abstract=excluded.abstract,
                    publication_date=excluded.publication_date,
                    filing_date=excluded.filing_date,
                    application_number=excluded.application_number,
                    ipc=excluded.ipc,
                    applicant=excluded.applicant,
                    inventor=excluded.inventor,
                    patentee=excluded.patentee,
                    source_url=excluded.source_url,
                    directions_json=excluded.directions_json,
                    imported_at=excluded.imported_at
                """,
                payload,
            )
            if exists:
                updated += 1
            else:
                inserted += 1
    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "fine_top": fine_counter.most_common(12),
    }


def link_science_articles() -> dict[str, int]:
    init_db()
    now = utc_now()
    linked = 0
    articles_with_hits = 0
    with connect() as conn:
        patent_ids = {
            row["patent_id"]
            for row in conn.execute("SELECT patent_id FROM patents").fetchall()
        }
        rows = conn.execute(
            """
            SELECT article_id, title, text, flow_tags_json
            FROM articles
            WHERE flow_tags_json IS NOT NULL AND flow_tags_json != '' AND flow_tags_json != '[]'
            """
        ).fetchall()
        for row in rows:
            try:
                tags = json.loads(row["flow_tags_json"] or "[]")
            except json.JSONDecodeError:
                continue
            if "science" not in tags:
                continue
            found = extract_patent_ids_from_text(row["title"] or "", row["text"] or "")
            hits = [pid for pid in found if pid in patent_ids]
            if not hits:
                continue
            articles_with_hits += 1
            for patent_id in hits:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO article_patent_links
                    (article_id, patent_id, match_type, created_at)
                    VALUES (?, ?, 'number_in_text', ?)
                    """,
                    (row["article_id"], patent_id, now),
                )
                linked += cur.rowcount
    return {"articles_with_patent_numbers": articles_with_hits, "links_added": linked}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl", default=str(DEFAULT_JSONL))
    parser.add_argument("--skip-links", action="store_true")
    args = parser.parse_args()
    path = Path(args.jsonl)
    if not path.exists():
        print(f"Нет файла: {path}", file=sys.stderr)
        return 2
    rows = load_jsonl(path)
    report = {"source_rows": len(rows), "upsert": upsert_patents(rows)}
    if not args.skip_links:
        report["links"] = link_science_articles()
    with connect() as conn:
        report["patents_in_db"] = conn.execute("SELECT COUNT(*) AS n FROM patents").fetchone()["n"]
        report["links_in_db"] = conn.execute(
            "SELECT COUNT(*) AS n FROM article_patent_links"
        ).fetchone()["n"]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
