"""Пересборка всего, что зависит от нормализации патентообладателей.

После правок gartner/patent_orgs.py:
  python scripts/rebuild_patent_orgs.py

Пишет:
  - data/runs/patents/unique_orgs.json (+ _review)
  - data/exports/org_sites_prompt/all_patent_holders.txt|.tsv
  - data/exports/org_sites_prompt/science_enterprises.txt|.tsv
  - data/exports/org_sites_prompt/organizations_az.xlsx
  - data/exports/org_sites_prompt/*_sites.json (+ org_news_sources.json)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gartner.db import connect, init_db
from gartner.patent_orgs import build_unique_org_report, org_merge_key

RUNS = ROOT / "data" / "runs" / "patents"
EXPORT = ROOT / "data" / "exports" / "org_sites_prompt"
SUFFIX_RE = re.compile(r"\s*\(\d+(?:,\s*(?:university|nii))?\)\s*$", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().replace("ё", "е")).strip()


def write_unique_orgs(report: dict) -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    full = RUNS / "unique_orgs.json"
    review = RUNS / "unique_orgs_review.json"
    full.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    slim = {
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
                "raw_examples": (item.get("raw_examples") or [])[:2],
            }
            for item in report["items"]
        ],
    }
    review.write_text(json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"unique_orgs -> {full}")
    print(f"review -> {review}")


def write_holder_lists(report: dict) -> tuple[list[dict], list[dict]]:
    EXPORT.mkdir(parents=True, exist_ok=True)
    items = list(report.get("items") or [])
    holders = sorted(items, key=lambda x: (-int(x.get("patent_count") or 0), _norm(x["canonical_name"])))
    science = [
        x
        for x in holders
        if x.get("org_type") in ("university", "nii") and int(x.get("patent_count") or 0) > 0
    ]

    def lines(rows: list[dict], with_type: bool) -> list[str]:
        out = []
        for r in rows:
            name = r["canonical_name"]
            n = int(r.get("patent_count") or 0)
            if with_type:
                out.append(f"{name} ({n}, {r.get('org_type')})")
            else:
                out.append(f"{name} ({n})")
        return out

    (EXPORT / "all_patent_holders.txt").write_text("\n".join(lines(holders, False)), encoding="utf-8")
    (EXPORT / "science_enterprises.txt").write_text("\n".join(lines(science, True)), encoding="utf-8")

    def tsv(rows: list[dict], with_type: bool) -> str:
        head = ["name", "patent_count"] + (["org_type"] if with_type else [])
        body = ["\t".join(head)]
        for r in rows:
            cols = [r["canonical_name"], str(r.get("patent_count") or 0)]
            if with_type:
                cols.append(str(r.get("org_type") or ""))
            body.append("\t".join(cols))
        return "\n".join(body)

    (EXPORT / "all_patent_holders.tsv").write_text(tsv(holders, False), encoding="utf-8")
    (EXPORT / "science_enterprises.tsv").write_text(tsv(science, True), encoding="utf-8")
    print(f"holders txt/tsv: {len(holders)} · science: {len(science)}")
    return holders, science


def write_excel(holders: list[dict], science: list[dict]) -> None:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    except ImportError:
        import subprocess

        subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl", "-q"])
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    sci_names = {_norm(x["canonical_name"]) for x in science}
    wb = Workbook()
    header_fill = PatternFill("solid", fgColor="17334E")
    header_font = Font(bold=True, color="FFFFFF", name="Calibri", size=11)
    body_font = Font(name="Calibri", size=11)
    thin = Border(
        left=Side(style="thin", color="D0D5DD"),
        right=Side(style="thin", color="D0D5DD"),
        top=Side(style="thin", color="D0D5DD"),
        bottom=Side(style="thin", color="D0D5DD"),
    )

    def style_header(ws):
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(vertical="center")

    def style_body(ws):
        for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=ws.max_column):
            for cell in row:
                cell.font = body_font
                cell.border = thin
                cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions["A"].width = 6
        ws.column_dimensions["B"].width = 80
        ws.column_dimensions["C"].width = 12
        if ws.max_column >= 4:
            ws.column_dimensions["D"].width = 14
        if ws.max_column >= 5:
            ws.column_dimensions["E"].width = 20
        ws.auto_filter.ref = ws.dimensions
        ws.freeze_panes = "A2"

    holders_az = sorted(holders, key=lambda x: _norm(x["canonical_name"]))
    science_az = sorted(science, key=lambda x: _norm(x["canonical_name"]))

    ws1 = wb.active
    ws1.title = "Патентообладатели"
    ws1.append(["№", "Название", "Патентов", "Тип", "Научное предприятие"])
    style_header(ws1)
    for i, r in enumerate(holders_az, 1):
        name = r["canonical_name"]
        ws1.append(
            [
                i,
                name,
                r.get("patent_count") or 0,
                r.get("org_type") or "",
                "да" if _norm(name) in sci_names else "",
            ]
        )
    style_body(ws1)

    ws2 = wb.create_sheet("Научные предприятия")
    ws2.append(["№", "Название", "Патентов", "Тип"])
    style_header(ws2)
    for i, r in enumerate(science_az, 1):
        ws2.append([i, r["canonical_name"], r.get("patent_count") or 0, r.get("org_type") or ""])
    style_body(ws2)

    ws3 = wb.create_sheet("Все вместе А-Я")
    ws3.append(["№", "Название", "Патентов", "Тип", "Научное предприятие"])
    style_header(ws3)
    for i, r in enumerate(holders_az, 1):
        name = r["canonical_name"]
        ws3.append(
            [
                i,
                name,
                r.get("patent_count") or 0,
                r.get("org_type") or "",
                "да" if _norm(name) in sci_names else "",
            ]
        )
    style_body(ws3)

    path = EXPORT / "organizations_az.xlsx"
    wb.save(path)
    print(f"excel -> {path}")


def _load_old_sites() -> dict[str, dict]:
    """Старые URL по нормализованному имени / merge_key / сырому примеру."""
    by: dict[str, dict] = {}
    for fname in (
        "all_patent_holders_sites.json",
        "science_enterprises_sites.json",
        "org_news_sources.json",
        "org_sites_cleaned.json",
    ):
        path = EXPORT / fname
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, dict):
                continue
            if not (item.get("official_url") or item.get("news_url")):
                continue
            name = SUFFIX_RE.sub("", str(item.get("name") or "")).strip()
            if not name:
                continue
            rec = {
                "official_url": item.get("official_url"),
                "news_url": item.get("news_url"),
                "lang": item.get("lang"),
                "confidence": item.get("confidence") or "medium",
                "note": item.get("note"),
            }
            for key in (_norm(name), org_merge_key(name)):
                if key and (key not in by or (rec.get("news_url") and not by[key].get("news_url"))):
                    by[key] = rec
    return by


def write_sites(holders: list[dict], science: list[dict]) -> None:
    old = _load_old_sites()

    def resolve_site(name: str) -> dict:
        for key in (_norm(name), org_merge_key(name)):
            if key and key in old:
                hit = old[key]
                return {
                    "name": name,
                    "official_url": hit.get("official_url"),
                    "news_url": hit.get("news_url"),
                    "lang": hit.get("lang"),
                    "confidence": hit.get("confidence") or "medium",
                    "note": hit.get("note"),
                }
        # частичное: старое имя содержится в новом (Опыт ⊂ НПК «Опыт»)
        n = _norm(name)
        best = None
        for key, hit in old.items():
            if len(key) >= 4 and key in n and (hit.get("official_url") or hit.get("news_url")):
                if best is None or len(key) > len(best[0]):
                    best = (key, hit)
        if best:
            hit = best[1]
            return {
                "name": name,
                "official_url": hit.get("official_url"),
                "news_url": hit.get("news_url"),
                "lang": hit.get("lang"),
                "confidence": hit.get("confidence") or "medium",
                "note": hit.get("note") or "URL перенесён со старого канона",
            }
        return {
            "name": name,
            "official_url": None,
            "news_url": None,
            "lang": None,
            "confidence": "low",
            "note": "Сайт не сопоставлен после ренормализации",
        }

    holders_sites = [resolve_site(r["canonical_name"]) for r in holders]
    science_sites = [resolve_site(r["canonical_name"]) for r in science]
    news = [x for x in holders_sites if x.get("news_url")]

    (EXPORT / "all_patent_holders_sites.json").write_text(
        json.dumps(holders_sites, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (EXPORT / "science_enterprises_sites.json").write_text(
        json.dumps(science_sites, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (EXPORT / "org_news_sources.json").write_text(
        json.dumps(news, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (EXPORT / "org_news_sources_v2.json").write_text(
        json.dumps(news, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    tsv = ["name\tofficial_url\tnews_url\tlang\tconfidence\tnote"]
    for x in science_sites:
        tsv.append(
            "\t".join(
                [
                    x["name"],
                    x.get("official_url") or "",
                    x.get("news_url") or "",
                    x.get("lang") or "",
                    x.get("confidence") or "",
                    (x.get("note") or "").replace("\t", " "),
                ]
            )
        )
    (EXPORT / "science_enterprises_sites.tsv").write_text("\n".join(tsv), encoding="utf-8")

    summary = {
        "holders_total": len(holders_sites),
        "holders_with_official": sum(1 for x in holders_sites if x.get("official_url")),
        "holders_with_news": sum(1 for x in holders_sites if x.get("news_url")),
        "science_total": len(science_sites),
        "science_with_official": sum(1 for x in science_sites if x.get("official_url")),
        "science_with_news": sum(1 for x in science_sites if x.get("news_url")),
        "org_news_sources": len(news),
    }
    (EXPORT / "sites_collection_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("sites:", json.dumps(summary, ensure_ascii=False))


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
    print(f"patents loaded: {len(rows)}")
    report = build_unique_org_report(rows)
    print(
        json.dumps(
            {
                "patents_total": report["patents_total"],
                "patents_with_org": report["patents_with_org"],
                "unique_orgs": report["unique_orgs"],
                "by_type": report["by_type"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    write_unique_orgs(report)
    holders, science = write_holder_lists(report)
    write_excel(holders, science)
    write_sites(holders, science)
    print("science_flow API берёт org_names live из БД — перезапуск портала не обязателен, достаточно обновить страницу.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
