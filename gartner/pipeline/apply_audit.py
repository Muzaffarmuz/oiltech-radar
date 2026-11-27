"""Сборка отчётов портала из data/for_recluster/_audit/*/audited.jsonl.

В портал попадают только audit_status in {kept, reassigned}.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gartner.config import FLOW_TAGS_DIR, RUNS_DIR
from gartner.pipeline.cluster_audit import load_jsonl, record_id

AUDIT_ROOT = RUNS_DIR.parent / "for_recluster" / "_audit"
KEEP_STATUSES = frozenset({"kept", "reassigned"})

PORTAL_TARGETS = {
    "policy": FLOW_TAGS_DIR / "policy_clusters_report.json",
    "investments": FLOW_TAGS_DIR / "investments_clusters_report.json",
    "science_news": RUNS_DIR / "science_org_news" / "clusters_report.json",
    "patents": RUNS_DIR / "patents" / "audited_portal.json",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _kept_rows(corpus: str) -> list[dict[str, Any]]:
    path = AUDIT_ROOT / corpus / "audited.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"нет аудита: {path}")
    return [r for r in load_jsonl(path) if r.get("audit_status") in KEEP_STATUSES]


def _cluster_catalog(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    members: dict[str, list[dict[str, Any]]] = defaultdict(list)
    titles: dict[str, str] = {}
    for row in rows:
        cid = str(row.get("cluster_id") or "").strip()
        if not cid:
            continue
        members[cid].append(row)
        titles[cid] = str(row.get("cluster_title") or cid)
    clusters = []
    for cid, items in sorted(members.items(), key=lambda p: -len(p[1])):
        sub_counts: Counter[str] = Counter()
        sub_titles: dict[str, str] = {}
        for item in items:
            sid = str(item.get("sub_cluster_id") or "").strip()
            if not sid:
                continue
            sub_counts[sid] += 1
            sub_titles[sid] = str(item.get("sub_cluster_title") or sid)
        subs = [
            {
                "id": sid,
                "local_id": sid.rsplit("_s", 1)[-1] if "_s" in sid else sid,
                "title": sub_titles[sid],
                "member_count": n,
            }
            for sid, n in sorted(sub_counts.items(), key=lambda p: -p[1])
        ]
        clusters.append(
            {
                "id": cid,
                "title": titles[cid],
                "description": "",
                "member_count": len(items),
                "subclusters": subs,
            }
        )
    return clusters


def _by_month(rows: list[dict[str, Any]], date_key: str = "datatime") -> list[dict[str, int]]:
    counts: Counter[str] = Counter()
    for row in rows:
        raw = str(row.get(date_key) or row.get("date") or row.get("publication_date") or "")
        month = raw.replace(".", "-")[:7]
        if len(month) == 7:
            counts[month] += 1
    return [{"month": m, "count": counts[m]} for m in sorted(counts, reverse=True)]


def build_flow_report(corpus: str, *, flow: str) -> dict[str, Any]:
    rows = _kept_rows(corpus)
    clusters = _cluster_catalog(rows)
    index = []
    for row in rows:
        aid = record_id(row)
        date = str(row.get("datatime") or row.get("date") or "")[:10]
        cid = str(row.get("cluster_id") or "").strip()
        noise = 0 if cid else 1
        index.append(
            {
                "patent_id": aid,
                "article_id": aid,
                "identity": row.get("source") or "",
                "title": str(row.get("title") or "")[:180],
                "abstract": str(row.get("text") or row.get("abstract") or "")[:1200],
                "date": date,
                "date_norm": date,
                "patentee": row.get("source") or "",
                "link": row.get("link") or "",
                "source": row.get("source") or "",
                "cluster_id": cid or None,
                "cluster_title": row.get("cluster_title") or None,
                "sub_cluster_id": row.get("sub_cluster_id") or None,
                "sub_cluster_title": row.get("sub_cluster_title") or None,
                "is_noise": noise,
                "kind": "news",
            }
        )
    index.sort(key=lambda i: (1 if i.get("date_norm") else 0, i.get("date_norm") or ""), reverse=True)
    noise = sum(1 for i in index if i.get("is_noise"))
    return {
        "source": "flow_news_clusters",
        "flow": flow,
        "mode": "news",
        "method": "audit_lab",
        "year_from": 2022,
        "n_articles": len(index),
        "n_clusters": len(clusters),
        "n_subclusters": sum(len(c.get("subclusters") or []) for c in clusters),
        "noise": noise,
        "articles": len(index),
        "by_month": _by_month(rows),
        "clusters": clusters,
        "index": index,
        "note": f"Корпус после Lab-аудита ({_now()}): только kept/reassigned.",
        "audit_applied_at": _now(),
        "audit_corpus": corpus,
    }


def build_science_news_report() -> dict[str, Any]:
    rows = _kept_rows("science_news")
    clusters = _cluster_catalog(rows)
    org_counter: Counter[str] = Counter()
    index = []
    for row in rows:
        aid = record_id(row)
        date = str(row.get("datatime") or row.get("date") or "")[:10]
        org = str(row.get("org_name") or "")
        if org:
            org_counter[org] += 1
        cid = str(row.get("cluster_id") or "").strip()
        index.append(
            {
                "patent_id": aid,
                "article_id": aid,
                "identity": row.get("source") or "",
                "title": str(row.get("title") or "")[:180],
                "abstract": str(row.get("text") or "")[:1200],
                "date": date,
                "date_norm": date,
                "patentee": org[:120],
                "link": row.get("link") or "",
                "source": row.get("source") or "",
                "cluster_id": cid or None,
                "cluster_title": row.get("cluster_title") or None,
                "sub_cluster_id": row.get("sub_cluster_id") or None,
                "sub_cluster_title": row.get("sub_cluster_title") or None,
                "is_noise": 0 if cid else 1,
                "org_names": [org] if org else [],
            }
        )
    index.sort(key=lambda i: (1 if i.get("date_norm") else 0, i.get("date_norm") or ""), reverse=True)
    filter_orgs = [
        {"name": name, "patent_count": n}
        for name, n in sorted(org_counter.items(), key=lambda p: (-p[1], p[0].lower()))
    ]
    return {
        "source": "science_news_clusters",
        "mode": "news",
        "method": "audit_lab",
        "n_articles": len(index),
        "n_clusters": len(clusters),
        "n_subclusters": sum(len(c.get("subclusters") or []) for c in clusters),
        "noise": sum(1 for i in index if i.get("is_noise")),
        "articles": len(index),
        "patents": {
            "total": len(index),
            "members": len(index),
            "clustered": sum(1 for i in index if not i.get("is_noise")),
            "noise": sum(1 for i in index if i.get("is_noise")),
        },
        "by_month": _by_month(rows),
        "clusters": clusters,
        "science_orgs": {
            "total": len(filter_orgs),
            "items": [
                {"name": o["name"], "org_type": "unknown", "patent_count": o["patent_count"]}
                for o in filter_orgs
            ],
            "note": "После Lab-аудита.",
        },
        "filter_orgs": filter_orgs,
        "index": index,
        "note": f"Научные новости после Lab-аудита ({_now()}): только kept/reassigned.",
        "audit_applied_at": _now(),
    }


def build_patents_portal() -> dict[str, Any]:
    """Лёгкий индекс для science_flow_payload: id → новая тема."""
    rows = _kept_rows("patents")
    clusters = _cluster_catalog(rows)
    items = {}
    for row in rows:
        pid = record_id(row)
        items[pid] = {
            "patent_id": pid,
            "cluster_id": row.get("cluster_id") or None,
            "cluster_title": row.get("cluster_title") or None,
            "sub_cluster_id": row.get("sub_cluster_id") or None,
            "sub_cluster_title": row.get("sub_cluster_title") or None,
            "is_noise": 0 if row.get("cluster_id") else 1,
            "audit_status": row.get("audit_status"),
        }
    return {
        "source": "audit_lab",
        "applied_at": _now(),
        "n_patents": len(items),
        "n_clusters": len(clusters),
        "clusters": clusters,
        "items": items,
        "note": "Патенты после Lab-аудита: портал показывает только эти id.",
    }


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    bak = path.with_name(path.stem + ".pre_audit.json")
    if not bak.exists():
        shutil.copy2(path, bak)
    return bak


def apply_all() -> dict[str, Any]:
    results: dict[str, Any] = {}
    mapping = {
        "policy": (lambda: build_flow_report("policy", flow="policy"), PORTAL_TARGETS["policy"]),
        "investments": (
            lambda: build_flow_report("investments", flow="investments"),
            PORTAL_TARGETS["investments"],
        ),
        "science_news": (build_science_news_report, PORTAL_TARGETS["science_news"]),
        "patents": (build_patents_portal, PORTAL_TARGETS["patents"]),
    }
    for name, (builder, dest) in mapping.items():
        payload = builder()
        dest.parent.mkdir(parents=True, exist_ok=True)
        bak = backup(dest)
        dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        results[name] = {
            "dest": str(dest),
            "backup": str(bak) if bak else None,
            "n": payload.get("n_articles")
            or payload.get("n_patents")
            or payload.get("articles")
            or len(payload.get("items") or {}),
            "n_clusters": payload.get("n_clusters"),
        }
    marker = AUDIT_ROOT / "APPLIED_TO_PORTAL.json"
    marker.write_text(json.dumps({"applied_at": _now(), "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    return results
