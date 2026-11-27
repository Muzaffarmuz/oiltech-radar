"""Из 1965 патентов → уникальные организации + тип + ключи (для ручного разбора)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gartner.db import connect, init_db
from gartner.patent_orgs import build_unique_org_report

OUT = ROOT / "data" / "runs" / "patents" / "unique_orgs.json"
OUT_REVIEW = ROOT / "data" / "runs" / "patents" / "unique_orgs_review.json"


def main() -> int:
    init_db()
    rows: list[dict] = []
    with connect() as conn:
        for row in conn.execute(
            """
            SELECT patent_id, identity, publication_date, title,
                   applicant, inventor, patentee, ipc, directions_json
            FROM patents
            """
        ).fetchall():
            rows.append(dict(row))

    report = build_unique_org_report(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # укороченный файл для глаз: без длинных keys
    review = {
        "patents_total": report["patents_total"],
        "patents_with_org": report["patents_with_org"],
        "unique_orgs": report["unique_orgs"],
        "by_type": report["by_type"],
        "dictionary_keys": report["dictionary_keys"],
        "note": report.get("note"),
        "clusters_total": report.get("clusters_total"),
        "subclusters_total": report.get("subclusters_total"),
        "items": [
            {
                "canonical_name": item["canonical_name"],
                "org_type": item["org_type"],
                "patent_count": item["patent_count"],
                "matched_dictionary": item["matched_dictionary"],
                "dictionary_source": item.get("dictionary_source"),
                "clusters": item.get("clusters") or [],
                "subclusters": item.get("subclusters") or [],
                "raw_examples": item["raw_examples"][:2],
            }
            for item in report["items"]
        ],
    }
    OUT_REVIEW.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        k: report[k]
        for k in (
            "patents_total",
            "patents_with_org",
            "unique_orgs",
            "by_type",
            "dictionary_keys",
        )
    }
    summary["top_clusters"] = (report.get("clusters_total") or [])[:8]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"full -> {OUT}")
    print(f"review -> {OUT_REVIEW}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
