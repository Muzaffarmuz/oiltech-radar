"""Метки потоков в articles: импорт sidecar + опциональный LLM для новых."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gartner.config import FLOW_TAGS_DIR, RUNS_DIR, ensure_dirs
from gartner.db import connect, init_db, utc_now
from gartner.flow_tags import normalize_flow_tags

DEFAULT_SIDECARS = (
    FLOW_TAGS_DIR / "tagged.json",
    FLOW_TAGS_DIR / "tagged_radar.json",
)


def _load_tag_map(paths: list[Path] | None = None) -> dict[str, dict[str, Any]]:
    """link -> {flow_tags, tag_reasons} из JSON-сайдкаров экспериментов."""
    found: dict[str, dict[str, Any]] = {}
    for path in paths or list(DEFAULT_SIDECARS):
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            continue
        for row in payload:
            link = str(row.get("link") or "").strip()
            if not link:
                continue
            tags_raw = row.get("flow_tags") or []
            if not isinstance(tags_raw, list):
                continue
            try:
                tags = normalize_flow_tags([str(t).strip() for t in tags_raw if str(t).strip()])
            except ValueError:
                continue
            reasons = row.get("tag_reasons") or {}
            if not isinstance(reasons, dict):
                reasons = {}
            # поздний файл / повтор не затирает уже заполненные метки без нужды —
            # приоритет у более полного списка
            prev = found.get(link)
            if prev and len(prev.get("flow_tags") or []) > len(tags):
                continue
            found[link] = {
                "flow_tags": tags,
                "tag_reasons": {str(k): str(v) for k, v in reasons.items() if k in tags},
            }
    return found


def apply_flow_tags_from_sidecars(
    *,
    paths: list[Path] | None = None,
    only_untagged: bool = True,
) -> dict[str, int]:
    """Проставляет flow_tags_json по link из tagged.json / tagged_radar.json."""
    init_db()
    tag_map = _load_tag_map(paths)
    if not tag_map:
        return {"sidecars_links": 0, "updated": 0, "skipped": 0, "missing_in_db": 0}

    updated = 0
    skipped = 0
    missing = 0
    now = utc_now()
    with connect() as conn:
        for link, payload in tag_map.items():
            row = conn.execute(
                "SELECT article_id, flow_tags_json FROM articles WHERE link=?",
                (link,),
            ).fetchone()
            if not row:
                missing += 1
                continue
            if only_untagged and row["flow_tags_json"]:
                skipped += 1
                continue
            conn.execute(
                """
                UPDATE articles
                SET flow_tags_json=?, tag_reasons_json=?, flow_tagged_at=?
                WHERE article_id=?
                """,
                (
                    json.dumps(payload["flow_tags"], ensure_ascii=False),
                    json.dumps(payload["tag_reasons"], ensure_ascii=False),
                    now,
                    row["article_id"],
                ),
            )
            updated += 1
    return {
        "sidecars_links": len(tag_map),
        "updated": updated,
        "skipped": skipped,
        "missing_in_db": missing,
    }


def _parse_directions(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    fine = payload.get("fine") if isinstance(payload.get("fine"), list) else []
    coarse = payload.get("coarse") if isinstance(payload.get("coarse"), list) else []
    if not fine and not coarse:
        return None
    return {
        "fine": [str(x) for x in fine if str(x).strip()],
        "coarse": [str(x) for x in coarse if str(x).strip()],
        "reason": str(payload.get("reason") or ""),
    }


def flow_payload_for_tag(tag: str) -> dict[str, Any]:
    """Сводка статей с меткой потока из БД (основной источник портала)."""
    init_db()
    items: list[dict[str, Any]] = []
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT title, datatime, source, link, flow_tags_json, tag_reasons_json,
                   science_directions_json
            FROM articles
            WHERE flow_tags_json IS NOT NULL AND flow_tags_json != '' AND flow_tags_json != '[]'
            """
        ).fetchall()
    for row in rows:
        try:
            tags = json.loads(row["flow_tags_json"] or "[]")
        except json.JSONDecodeError:
            continue
        if not isinstance(tags, list) or tag not in tags:
            continue
        try:
            reasons = json.loads(row["tag_reasons_json"] or "{}")
        except json.JSONDecodeError:
            reasons = {}
        if not isinstance(reasons, dict):
            reasons = {}
        item: dict[str, Any] = {
            "title": str(row["title"] or ""),
            "date": str(row["datatime"] or ""),
            "source": str(row["source"] or ""),
            "link": str(row["link"] or ""),
            "reason": str(reasons.get(tag) or ""),
            "tags": [str(t) for t in tags if t != tag],
        }
        directions = _parse_directions(row["science_directions_json"] if "science_directions_json" in row.keys() else None)
        if directions:
            item["directions"] = directions
        items.append(item)

    items.sort(key=lambda item: (1 if item["date"] else 0, item["date"]), reverse=True)
    dated = [item for item in items if item["date"]]
    by_source: dict[str, int] = {}
    by_month: dict[str, int] = {}
    for item in items:
        source = item["source"] or "(без источника)"
        by_source[source] = by_source.get(source, 0) + 1
        if len(item["date"]) >= 7:
            month = item["date"][:7]
            by_month[month] = by_month.get(month, 0) + 1
    payload: dict[str, Any] = {
        "articles": len(items),
        "year_2026": sum(1 for item in dated if item["date"].startswith("2026")),
        "sources": len(by_source),
        "with_digital": sum(1 for item in items if "digital" in item["tags"]),
        "with_news": sum(1 for item in items if "news" in item["tags"]),
        "without_cbr": sum(1 for item in items if item["source"] != "cbr.ru"),
        "undated": len(items) - len(dated),
        "by_source": [
            {"source": source, "count": count}
            for source, count in sorted(by_source.items(), key=lambda pair: (-pair[1], pair[0]))
        ],
        "by_month": [{"month": month, "count": by_month[month]} for month in sorted(by_month)],
        "items": items,
        "source": "db",
    }
    if tag == "science":
        from gartner.config import get_settings
        from gartner.patents import (
            aggregate_patent_counts,
            merge_direction_bars,
            normalize_pub_date,
            patent_chart_since,
        )
        from gartner.science_analytics import (
            build_science_centers,
            build_science_to_market,
            count_news_by_coarse,
        )
        from gartner.science_directions import aggregate_counts, taxonomy_meta

        directed = [item for item in items if item.get("directions")]
        article_coarse = aggregate_counts(directed, "coarse")
        article_fine = aggregate_counts(directed, "fine")
        patent_rows: list[Any] = []
        patent_full_for_centers: list[Any] = []
        science_full_rows: list[Any] = []
        news_rows: list[Any] = []
        patent_total = 0
        patent_in_window = 0
        link_total = 0
        since = ""
        until = ""
        months = max(1, int(get_settings().patent_chart_months or 6))
        with connect() as conn:
            patent_total = conn.execute("SELECT COUNT(*) AS n FROM patents").fetchone()["n"]
            link_total = conn.execute(
                "SELECT COUNT(*) AS n FROM article_patent_links"
            ).fetchone()["n"]
            science_full_rows = conn.execute(
                """
                SELECT title, text, science_directions_json, flow_tags_json
                FROM articles
                WHERE flow_tags_json IS NOT NULL AND flow_tags_json != '' AND flow_tags_json != '[]'
                """
            ).fetchall()
            science_full_rows = [
                row
                for row in science_full_rows
                if "science" in _parse_flow_tags(row["flow_tags_json"])
            ]
            news_rows = [
                row
                for row in conn.execute(
                    """
                    SELECT title, text, flow_tags_json
                    FROM articles
                    WHERE flow_tags_json IS NOT NULL AND flow_tags_json != '' AND flow_tags_json != '[]'
                    """
                ).fetchall()
                if "news" in _parse_flow_tags(row["flow_tags_json"])
            ]
            if patent_total:
                since, until = patent_chart_since(conn, months=months)
                raw_rows = conn.execute(
                    """
                    SELECT directions_json, publication_date, patentee, applicant,
                           inventor, title
                    FROM patents
                    WHERE directions_json IS NOT NULL AND directions_json != ''
                    """
                ).fetchall()
                patent_full_for_centers = list(raw_rows)
                if since:
                    patent_rows = [
                        row
                        for row in raw_rows
                        if normalize_pub_date(row["publication_date"]) >= since
                    ]
                else:
                    patent_rows = list(raw_rows)
                patent_in_window = len(patent_rows)
        patent_coarse = aggregate_patent_counts(patent_rows, "coarse") if patent_rows else []
        patent_fine = aggregate_patent_counts(patent_rows, "fine") if patent_rows else []
        news_coarse = count_news_by_coarse(news_rows)
        payload["directions"] = {
            "tagged": len(directed),
            "untagged": len(items) - len(directed),
            "by_coarse": merge_direction_bars(article_coarse, patent_coarse, scale="coarse"),
            "by_fine": merge_direction_bars(article_fine, patent_fine, scale="fine"),
            "articles_by_coarse": article_coarse,
            "patents_by_coarse": patent_coarse,
            "taxonomy": taxonomy_meta(),
        }
        payload["patents"] = {
            "total": patent_total,
            "in_chart": patent_in_window,
            "chart_months": months,
            "since": since,
            "until": until,
            "article_links": link_total,
        }
        payload["science_centers"] = {
            "items": build_science_centers(
                science_rows=science_full_rows,
                patent_rows=patent_full_for_centers,
            ),
            "source": "corpus",
            "note": "По упоминаниям в science-статьях и правообладателях патентов. Не РИНЦ.",
        }
        payload["science_to_market"] = {
            "items": build_science_to_market(
                science_by_coarse=article_coarse,
                patents_by_coarse=patent_coarse,
                news_by_coarse=news_coarse,
            ),
            "threshold": 1.5,
            "formula": "(science + 0.25×patents) / max(news, 1)",
            "news_tagged": len(news_rows),
        }
    return payload


def _parse_flow_tags(raw: str | None) -> list[str]:
    try:
        tags = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [str(t) for t in tags] if isinstance(tags, list) else []


def run_tag_flows_stage(*, import_sidecars: bool = True) -> dict[str, Any]:
    """Этап пайплайна: перенос экспериментальных меток в articles."""
    ensure_dirs()
    report: dict[str, Any] = {}
    if import_sidecars:
        report["import"] = apply_flow_tags_from_sidecars(only_untagged=True)
    with connect() as conn:
        tagged = conn.execute(
            """
            SELECT COUNT(*) AS n FROM articles
            WHERE flow_tags_json IS NOT NULL AND flow_tags_json != '' AND flow_tags_json != '[]'
            """
        ).fetchone()["n"]
        total = conn.execute("SELECT COUNT(*) AS n FROM articles").fetchone()["n"]
    report["articles_tagged"] = tagged
    report["articles_total"] = total
    out = RUNS_DIR / "flow_tags" / "db_tag_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
