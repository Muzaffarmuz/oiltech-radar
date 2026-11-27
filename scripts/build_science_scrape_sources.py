"""Собрать JSON источников для скрапа Наука: топ-30 holders ∪ топ-30 science.

  python scripts/build_science_scrape_sources.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UNIQUE = ROOT / "data" / "runs" / "patents" / "unique_orgs.json"
PROGRESS = ROOT / "data" / "exports" / "org_sites_prompt" / "_sites_collect_progress.json"
HOLDERS_SITES = ROOT / "data" / "exports" / "org_sites_prompt" / "all_patent_holders_sites.json"
SCI_SITES = ROOT / "data" / "exports" / "org_sites_prompt" / "science_enterprises_sites.json"
OUT = ROOT / "data" / "exports" / "org_sites_prompt" / "science_scrape_top60.json"


def main() -> None:
    items = json.loads(UNIQUE.read_text(encoding="utf-8"))["items"]
    by_name: dict[str, dict] = {}
    for path in (HOLDERS_SITES, SCI_SITES):
        if path.exists():
            for row in json.loads(path.read_text(encoding="utf-8")):
                if row.get("name"):
                    by_name[row["name"]] = row
    if PROGRESS.exists():
        for name, row in json.loads(PROGRESS.read_text(encoding="utf-8")).get("by_name", {}).items():
            prev = by_name.get(name)
            if not prev or (row.get("official_url") and not prev.get("official_url")):
                by_name[name] = {
                    "name": name,
                    "official_url": row.get("official_url"),
                    "news_url": row.get("news_url"),
                    "lang": row.get("lang"),
                    "confidence": row.get("confidence"),
                    "note": row.get("note"),
                }
            elif prev and row.get("news_url") and not prev.get("news_url"):
                prev["news_url"] = row.get("news_url")

    holders = sorted(items, key=lambda x: -int(x.get("patent_count") or 0))[:30]
    science = sorted(
        [
            x
            for x in items
            if x.get("org_type") in ("university", "nii") and int(x.get("patent_count") or 0) > 0
        ],
        key=lambda x: -int(x.get("patent_count") or 0),
    )[:30]

    selected: dict[str, dict] = {}
    missing: list[dict] = []
    for group, rows in (("holders_top30", holders), ("science_top30", science)):
        for x in rows:
            name = x["canonical_name"]
            site = by_name.get(name) or {}
            url = site.get("news_url") or site.get("official_url")
            if not url:
                missing.append(
                    {
                        "group": group,
                        "name": name,
                        "patent_count": x.get("patent_count"),
                        "org_type": x.get("org_type"),
                    }
                )
                continue
            selected[name] = {
                "name": name,
                "patent_count": x.get("patent_count"),
                "org_type": x.get("org_type"),
                "group": group,
                "official_url": site.get("official_url"),
                "news_url": site.get("news_url"),
                "lang": site.get("lang"),
                "confidence": site.get("confidence"),
                "note": site.get("note"),
            }

    out_rows = sorted(selected.values(), key=lambda r: -int(r.get("patent_count") or 0))
    OUT.write_text(json.dumps(out_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    meta = {
        "sources": len(out_rows),
        "holders_top30": 30,
        "science_top30": 30,
        "union_with_url": len(out_rows),
        "missing_no_url": missing,
        "out": str(OUT),
    }
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
