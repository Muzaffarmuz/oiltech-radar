"""Решения аудита кластеров без вызова модели.

Три шага: тема про нефтегаз или нет; документ на своём месте или нет;
чужой, но нефтегазовый документ переносится в живую тему.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

FIT_MIN = 0.6


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "да", "keep"}
    raise ValueError("boolean missing")


def as_score(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def record_id(row: dict[str, Any]) -> str:
    for key in ("article_id", "patent_id", "id"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def record_text(row: dict[str, Any], limit: int = 1600) -> str:
    for key in ("text", "abstract", "body"):
        value = str(row.get(key) or "").strip()
        if value:
            return value[:limit]
    return ""


def is_assigned(row: dict[str, Any]) -> bool:
    if row.get("is_noise") in (1, True, "1"):
        return False
    return bool(str(row.get("cluster_id") or "").strip())


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_descriptions(report_path: Path) -> dict[str, str]:
    if not report_path.exists():
        return {}
    report = json.loads(report_path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for cluster in report.get("clusters") or []:
        cid = str(cluster.get("id") or cluster.get("cluster_id") or "")
        if cid:
            out[cid] = str(cluster.get("description") or "")
        for sub in cluster.get("subclusters") or []:
            sid = str(sub.get("id") or "")
            if sid:
                out[sid] = str(sub.get("description") or "")
    return out


def taxonomy_jobs(rows: list[dict[str, Any]], descriptions: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Кластеры и подкластеры, в которых реально лежат документы."""
    descriptions = descriptions or {}
    clusters: dict[str, dict[str, Any]] = {}
    subs: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not is_assigned(row):
            continue
        cid = str(row.get("cluster_id") or "")
        cluster = clusters.setdefault(
            cid,
            {
                "kind": "cluster",
                "id": cid,
                "title": str(row.get("cluster_title") or cid),
                "description": descriptions.get(cid, ""),
                "titles": [],
                "member_count": 0,
            },
        )
        cluster["member_count"] += 1
        title = str(row.get("title") or "").strip()
        if title and len(cluster["titles"]) < 12 and title not in cluster["titles"]:
            cluster["titles"].append(title)
        sid = str(row.get("sub_cluster_id") or "").strip()
        if not sid:
            continue
        sub = subs.setdefault(
            sid,
            {
                "kind": "subcluster",
                "id": sid,
                "parent_id": cid,
                "title": str(row.get("sub_cluster_title") or sid),
                "parent_title": str(row.get("cluster_title") or cid),
                "description": descriptions.get(sid, ""),
                "titles": [],
                "member_count": 0,
            },
        )
        sub["member_count"] += 1
        if title and len(sub["titles"]) < 12 and title not in sub["titles"]:
            sub["titles"].append(title)
    return list(clusters.values()) + list(subs.values())


def titles_from_jobs(jobs: list[dict[str, Any]]) -> dict[str, str]:
    return {str(j["id"]): str(j.get("title") or j["id"]) for j in jobs}


def kept_theme_ids(taxonomy: dict[str, dict[str, Any]]) -> tuple[set[str], set[str]]:
    """Подкластер жив только если жив и он, и родительский кластер."""
    kept_clusters = {
        key
        for key, row in taxonomy.items()
        if row.get("kind") == "cluster" and row.get("keep") is True
    }
    kept_subs = {
        key
        for key, row in taxonomy.items()
        if row.get("kind") == "subcluster"
        and row.get("keep") is True
        and str(row.get("parent_id") or "") in kept_clusters
    }
    return kept_clusters, kept_subs


def fit_ok(row: dict[str, Any]) -> bool:
    if row.get("fits") is True:
        return True
    return as_score(row.get("score")) >= FIT_MIN


def needs_reassign(
    row: dict[str, Any],
    fit: dict[str, Any],
    *,
    kept_clusters: set[str],
    kept_subs: set[str],
) -> bool:
    if fit.get("oilgas") is not True:
        return False
    cid = str(row.get("cluster_id") or "")
    sid = str(row.get("sub_cluster_id") or "")
    if not is_assigned(row) or cid not in kept_clusters:
        return True
    if sid and sid not in kept_subs:
        return True
    return not fit_ok(fit)


def apply_audit(
    rows: list[dict[str, Any]],
    fits: dict[str, dict[str, Any]],
    moves: dict[str, dict[str, Any]],
    *,
    kept_clusters: set[str],
    kept_subs: set[str],
    titles: dict[str, str],
) -> list[dict[str, Any]]:
    """Вердикт по каждому документу. Исходные поля не затираются: пишутся audit_*."""
    out: list[dict[str, Any]] = []
    for row in rows:
        rid = record_id(row)
        cid = str(row.get("cluster_id") or "")
        sid = str(row.get("sub_cluster_id") or "")
        fit = fits.get(rid) or {}
        result = dict(row)
        result["audit_prev_cluster_id"] = cid
        result["audit_prev_sub_cluster_id"] = sid
        if fit.get("oilgas") is not True:
            result["audit_status"] = "dropped"
            result["audit_reason"] = str(fit.get("reason") or "не нефтегаз")
            out.append(result)
            continue
        cluster_ok = is_assigned(row) and cid in kept_clusters
        sub_ok = (not sid) or sid in kept_subs
        if cluster_ok and sub_ok and fit_ok(fit):
            result["audit_status"] = "kept"
            result["audit_reason"] = str(fit.get("reason") or "")
            out.append(result)
            continue
        move = moves.get(rid) or {}
        new_cid = str(move.get("cluster_id") or "")
        new_sid = str(move.get("sub_cluster_id") or "")
        if new_cid not in kept_clusters:
            result["audit_status"] = "unassigned"
            result["cluster_id"] = ""
            result["cluster_title"] = ""
            result["sub_cluster_id"] = ""
            result["sub_cluster_title"] = ""
            result["is_noise"] = 1
            result["audit_reason"] = str(
                move.get("reason") or fit.get("reason") or "нет подходящей темы"
            )
            out.append(result)
            continue
        if new_sid not in kept_subs:
            new_sid = ""
        result["audit_status"] = "reassigned"
        result["cluster_id"] = new_cid
        result["cluster_title"] = titles.get(new_cid, new_cid)
        result["sub_cluster_id"] = new_sid
        result["sub_cluster_title"] = titles.get(new_sid, "") if new_sid else ""
        result["is_noise"] = 0
        result["audit_reason"] = str(move.get("reason") or fit.get("reason") or "")
        out.append(result)
    return out


def summarize(rows: list[dict[str, Any]], audited: list[dict[str, Any]]) -> dict[str, Any]:
    status = Counter(str(r.get("audit_status") or "") for r in audited)
    return {
        "input": len(rows),
        "output": len(audited),
        "kept": status.get("kept", 0),
        "reassigned": status.get("reassigned", 0),
        "unassigned": status.get("unassigned", 0),
        "dropped": status.get("dropped", 0),
        "by_status": dict(status),
    }
