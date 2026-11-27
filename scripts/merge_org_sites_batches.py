"""Свести прогресс + known + websearch-батчи → итоговые сайты (без OpenRouter/DDG).

  python scripts/merge_org_sites_batches.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import collect_org_sites as cos  # noqa: E402

EXPORT = cos.EXPORT
KNOWN = cos.KNOWN
SUBSTRING_RULES = cos.SUBSTRING_RULES
UNIQUE = cos.UNIQUE
empty_row = cos.empty_row
from_tuple = cos.from_tuple
guess_lang = cos.guess_lang
norm = cos.norm
write_outputs = cos.write_outputs

PROGRESS = EXPORT / "_sites_collect_progress.json"


def resolve_known(name: str) -> dict | None:
    key = norm(name)
    if key in KNOWN:
        return from_tuple(name, KNOWN[key], "known")
    for sub, t in SUBSTRING_RULES:
        if sub in key and t is not None:
            return from_tuple(name, t, "substring")
    return None


def load_batches() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(EXPORT.glob("_batch_sites_*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            continue
        for item in raw:
            name = item.get("name")
            if not name:
                continue
            row = {
                "name": name,
                "official_url": item.get("official_url") or None,
                "news_url": item.get("news_url") or None,
                "lang": item.get("lang") or guess_lang(item.get("official_url")),
                "confidence": item.get("confidence") or ("medium" if item.get("official_url") else "low"),
                "note": item.get("note"),
                "source": f"websearch:{path.name}",
            }
            prev = out.get(name)
            if prev and prev.get("official_url") and not row.get("official_url"):
                continue
            if prev and prev.get("confidence") == "high" and row.get("confidence") != "high":
                if prev.get("official_url"):
                    continue
            out[name] = row
    return out


def better(a: dict | None, b: dict) -> dict:
    if not a:
        return b
    a_url = bool(a.get("official_url"))
    b_url = bool(b.get("official_url"))
    if b_url and not a_url:
        return b
    if a_url and not b_url:
        return a
    rank = {"high": 3, "medium": 2, "low": 1}
    if rank.get(b.get("confidence") or "", 0) > rank.get(a.get("confidence") or "", 0):
        return b
    # prefer news
    if b.get("news_url") and not a.get("news_url"):
        return b
    return a


def main() -> None:
    items = json.loads(UNIQUE.read_text(encoding="utf-8"))["items"]
    by_name: dict[str, dict] = {}

    if PROGRESS.exists():
        raw = json.loads(PROGRESS.read_text(encoding="utf-8"))
        for name, row in (raw.get("by_name") or {}).items():
            # отбрасываем мусорные ddg-хиты с явным мусором
            url = (row.get("official_url") or "").lower()
            if any(x in url for x in (".ru.gg", "edunetwork", "edu-inform", "gogov.ru", "openedu.ru", "tmweb.ru", "umcdh.ru")):
                continue
            if row.get("source") in ("ddg", "ddg_miss") and (row.get("confidence") or "") == "low":
                continue
            by_name[name] = row

    for name, row in load_batches().items():
        by_name[name] = better(by_name.get(name), row)

    for item in items:
        name = item["canonical_name"]
        otype = item.get("org_type") or "unknown"
        if otype in ("person", "redacted"):
            by_name[name] = empty_row(name, note="person/redacted", conf="low")
            continue
        known = resolve_known(name)
        if known:
            by_name[name] = better(by_name.get(name), known)
            continue
        if name not in by_name:
            by_name[name] = empty_row(name, note="pending", conf="low")

    # persist progress
    payload = {
        "updated": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
        "count": len(by_name),
        "by_name": by_name,
        "method": "known+websearch_batches+person_skip",
    }
    PROGRESS.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    write_outputs(by_name, items)

    with_url = sum(1 for v in by_name.values() if v.get("official_url"))
    pending = sum(1 for v in by_name.values() if (v.get("note") == "pending") or (v.get("source") == "skip" and not v.get("official_url") and "person" not in (v.get("note") or "")))
    science = [
        x
        for x in items
        if x.get("org_type") in ("university", "nii") and int(x.get("patent_count") or 0) > 0
    ]
    sci_url = sum(1 for x in science if (by_name.get(x["canonical_name"]) or {}).get("official_url"))
    print(
        json.dumps(
            {
                "total": len(items),
                "with_official": with_url,
                "science_with_official": f"{sci_url}/{len(science)}",
                "persons_skipped": sum(1 for x in items if x.get("org_type") in ("person", "redacted")),
                "pending_nonperson_no_url": sum(
                    1
                    for x in items
                    if x.get("org_type") not in ("person", "redacted")
                    and not (by_name.get(x["canonical_name"]) or {}).get("official_url")
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
