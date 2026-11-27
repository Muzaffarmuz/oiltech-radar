"""Кластеризация статей потоков policy / investments (KMeans + Lab LLM имена).

Корпус: SQLite articles с меткой потока.
Отчёты:
  data/runs/flow_tags/policy_clusters_report.json
  data/runs/flow_tags/investments_clusters_report.json

Не использует заглушки FLOW_CLUSTER_DEFS из UI.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from gartner.config import CACHE_DIR, FLOW_TAGS_DIR, Settings, ensure_dirs, get_settings
from gartner.db import connect, init_db
from gartner.llm import LLMClient
from gartner.pipeline.science_news_cluster import (
    _fallback_kmeans,
    _heuristic_name,
    _local_tfidf_embeddings,
    _normalize,
    _svd_xy,
    article_text,
)
from gartner.pipeline.subcluster import compress_label
from gartner.science_directions import COARSE_DIRECTIONS

ALLOWED_FLOWS = ("policy", "investments")
MIN_YEAR_DEFAULT = 2022
DEFAULT_N_CLUSTERS = 20
DEFAULT_MAX_SUBCLUSTERS = 5

# Релевантность «политика/рынок ТЭК» — шире, чем чистый oilgas.
_POLICY_RELEVANT_RE = re.compile(
    r"нефт|нефтегаз|газпром|роснефт|лукойл|новатэк|татнефть|сибур|транснефт|"
    r"спг|\blng\b|urals|брент|\bbrent\b|баррел|опек|\bopec\b|"
    r"санкц|эмбарго|пошлин|квот|экспорт|импорт|дизел|бензин|топлив|"
    r"нпз|гпз|трубопровод|нефтепровод|газопровод|месторожд|скважин|бурен|"
    r"углеводород|недропольз|минэнерго|антимонопол|потолок цен|"
    r"ключев\w*\s+ставк|инфляц|валютн|курс рубл|"
    r"(?<![а-яa-z])газ(?![а-яa-zё])|(?<![а-яa-z])газа(?![а-яa-zё])",
    re.IGNORECASE,
)
_POLICY_OFFTOPIC_RE = re.compile(
    r"дрон|беспилот|аэропорт|пво|авиарейс|авиакомпани|авиацион|"
    r"рейс задержан|закрытие неба|шахеди",
    re.IGNORECASE,
)
_TRUSTED_POLICY_SOURCES = {
    "cbr.ru",
    "rosenergo.gov.ru",
    "neftegaz.ru",
    "nprom.online",
    "novatek.ru",
    "sectormedia.ru",
}


def _article_blob(row: dict[str, Any]) -> str:
    title = str(row.get("title") or "")
    body = str(row.get("text") or row.get("abstract") or "")[:500]
    return f"{title}\n{body}".lower().replace("ё", "е")


def is_policy_relevant(row: dict[str, Any]) -> bool:
    """True, если статья полезна для потока policy (ТЭК / рынок / регулятор)."""
    blob = _article_blob(row)
    source = str(row.get("source") or "")
    if _POLICY_OFFTOPIC_RE.search(blob) and not _POLICY_RELEVANT_RE.search(blob):
        return False
    if source in _TRUSTED_POLICY_SOURCES:
        return True
    return bool(_POLICY_RELEVANT_RE.search(blob))


def filter_flow_rows(
    rows: list[dict[str, Any]],
    flow: str,
    *,
    relevant_only: bool = False,
    interfax_per_day: int = 0,
    dedupe_titles: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Состричь малоинформативные статьи до кластеризации / для slim-отчёта.

    interfax_per_day: 0 = без лимита; >0 = не больше N Interfax в день (лучшие по длине текста).
    """
    stats = {
        "input": len(rows),
        "drop_irrelevant": 0,
        "drop_dup_title": 0,
        "drop_interfax_cap": 0,
        "output": 0,
    }
    kept: list[dict[str, Any]] = []
    for row in rows:
        if relevant_only and flow == "policy" and not is_policy_relevant(row):
            stats["drop_irrelevant"] += 1
            continue
        kept.append(row)

    if dedupe_titles:
        seen: set[str] = set()
        uniq: list[dict[str, Any]] = []
        for row in kept:
            key = re.sub(r"\s+", " ", str(row.get("title") or "").strip().lower())
            if key and key in seen:
                stats["drop_dup_title"] += 1
                continue
            if key:
                seen.add(key)
            uniq.append(row)
        kept = uniq

    if interfax_per_day and interfax_per_day > 0:
        from collections import defaultdict

        by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
        other: list[dict[str, Any]] = []
        for row in kept:
            if str(row.get("source") or "") == "interfax.ru":
                day = str(row.get("datatime") or row.get("date") or row.get("date_norm") or "")[:10]
                by_day[day or "unknown"].append(row)
            else:
                other.append(row)
        capped: list[dict[str, Any]] = []
        for day_rows in by_day.values():
            day_rows = sorted(
                day_rows,
                key=lambda r: len(str(r.get("text") or r.get("abstract") or "")),
                reverse=True,
            )
            capped.extend(day_rows[:interfax_per_day])
            stats["drop_interfax_cap"] += max(0, len(day_rows) - interfax_per_day)
        kept = other + capped

    stats["output"] = len(kept)
    return kept, stats

CLUSTER_PROMPTS = {
    "policy": """Ты — старший аналитик внешних условий нефтегаза (политика, рынок, регулирование).
Сформулируй ОДНУ высокоуровневую тему (3–7 слов) по группе близких новостей.
Без названий СМИ и дат. Фокус: санкции, законы, ставка, цены, экспорт, аварии, регулятор.
Верни ТОЛЬКО JSON: {"name":"...","description":"1-2 предложения","confidence":0.0}
""",
    "investments": """Ты — старший аналитик инвестиций и корпоративных сделок в ТЭК.
Сформулируй ОДНУ высокоуровневую тему (3–7 слов) по группе близких новостей.
Без названий СМИ и дат. Фокус: сделки, раунды, капвложения, гранты, СП, IPO.
Верни ТОЛЬКО JSON: {"name":"...","description":"1-2 предложения","confidence":0.0}
""",
}

SUB_PROMPTS = {
    "policy": """Ты строишь иерархическую таксономию тем «политика и рынок» нефтегаза.
Верни ТОЛЬКО JSON: {"cluster_name":"...","confidence":0.0}
ПРАВИЛА: 2–5 слов, НА РУССКОМ, без пустышек, конкретный аспект родительской темы.
""",
    "investments": """Ты строишь иерархическую таксономию тем «инвестиции и стартапы» ТЭК.
Верни ТОЛЬКО JSON: {"cluster_name":"...","confidence":0.0}
ПРАВИЛА: 2–5 слов, НА РУССКОМ, без пустышек, конкретный аспект родительской темы.
""",
}


def report_path(flow: str) -> Path:
    return FLOW_TAGS_DIR / f"{flow}_clusters_report.json"


def embed_path(flow: str) -> Path:
    return CACHE_DIR / f"flow_{flow}_embeddings.npz"


def embed_manifest_path(flow: str) -> Path:
    return CACHE_DIR / f"flow_{flow}_embedding_manifest.json"


def article_id_from_link(link: str) -> str:
    return hashlib.sha1((link or "").encode("utf-8")).hexdigest()[:16]


def oilgas_lab_keep_path(flow: str) -> Path:
    return FLOW_TAGS_DIR / f"{flow}_oilgas_lab_keep.json"


def load_keep_ids(path: Path | None) -> set[str] | None:
    """None = без фильтра; set = оставить только эти article_id."""
    if path is None:
        return None
    if not path.exists():
        raise FileNotFoundError(f"keep-ids not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        ids = raw.get("keep_ids") or raw.get("article_ids") or []
    else:
        ids = raw
    if not isinstance(ids, list):
        raise ValueError(f"bad keep-ids format: {path}")
    return {str(x) for x in ids if str(x).strip()}


def load_flow_articles(
    flow: str,
    *,
    year_from: int = MIN_YEAR_DEFAULT,
    limit: int = 0,
    relevant_only: bool = False,
    interfax_per_day: int = 0,
    dedupe_titles: bool = True,
    keep_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    if flow not in ALLOWED_FLOWS:
        raise ValueError(f"flow must be one of {ALLOWED_FLOWS}")
    init_db()
    rows_out: list[dict[str, Any]] = []
    with connect() as conn:
        db_rows = conn.execute(
            """
            SELECT title, text, datatime, source, link, flow_tags_json
            FROM articles
            WHERE flow_tags_json IS NOT NULL AND flow_tags_json != '' AND flow_tags_json != '[]'
              AND link IS NOT NULL AND link != ''
            ORDER BY datatime DESC
            """
        ).fetchall()
    for row in db_rows:
        try:
            tags = json.loads(row["flow_tags_json"] or "[]")
        except json.JSONDecodeError:
            continue
        if not isinstance(tags, list) or flow not in tags:
            continue
        date = str(row["datatime"] or "")[:10]
        year = date[:4]
        if year_from and (len(year) < 4 or not year.isdigit() or int(year) < year_from):
            continue
        title = str(row["title"] or "").strip()
        text = str(row["text"] or "").strip()
        if len(title) < 8 and len(text) < 80:
            continue
        link = str(row["link"] or "").strip()
        rows_out.append(
            {
                "article_id": article_id_from_link(link),
                "title": title,
                "text": text,
                "datatime": date,
                "source": str(row["source"] or ""),
                "link": link,
            }
        )
    # дедуп по article_id
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows_out:
        by_id.setdefault(row["article_id"], row)
    out = list(by_id.values())
    out, filt_stats = filter_flow_rows(
        out,
        flow,
        relevant_only=relevant_only,
        interfax_per_day=interfax_per_day,
        dedupe_titles=dedupe_titles,
    )
    drop_keep = 0
    if keep_ids is not None:
        filtered = [r for r in out if r["article_id"] in keep_ids]
        drop_keep = len(out) - len(filtered)
        out = filtered
        filt_stats["drop_oilgas_lab"] = drop_keep
    if limit and limit > 0:
        out = out[: int(limit)]
    print(
        f"[flow-cluster:{flow}] load_articles n={len(out)} year_from={year_from} "
        f"filter={filt_stats}",
        flush=True,
    )
    return out


def _rewrite_report_index(
    flow: str,
    *,
    keep_ids: set[str],
    filter_meta: dict[str, Any],
    note: str,
    backup_suffix: str = "full",
) -> dict[str, Any]:
    """Ужать clusters_report до keep_ids, пересчитать счётчики, имена кластеров сохранить."""
    path = report_path(flow)
    if not path.exists():
        return {"status": "skip", "reason": "no_report", "flow": flow}
    report = json.loads(path.read_text(encoding="utf-8"))
    index = list(report.get("index") or [])
    new_index = [
        i for i in index if str(i.get("article_id") or i.get("patent_id")) in keep_ids
    ]

    by_cluster: Counter[str] = Counter()
    by_sub: Counter[str] = Counter()
    org_counter: Counter[str] = Counter()
    by_month: Counter[str] = Counter()
    for item in new_index:
        cid = item.get("cluster_id")
        if cid:
            by_cluster[str(cid)] += 1
        sid = item.get("sub_cluster_id")
        if sid:
            by_sub[str(sid)] += 1
        src = str(item.get("source") or "")
        if src:
            org_counter[src] += 1
        month = str(item.get("date_norm") or item.get("date") or "")[:7]
        if len(month) == 7:
            by_month[month] += 1

    clusters_out = []
    for c in report.get("clusters") or []:
        cid = str(c.get("id") or "")
        n = int(by_cluster.get(cid) or 0)
        if n <= 0:
            continue
        subs = []
        for s in c.get("subclusters") or []:
            sid = str(s.get("id") or "")
            sn = int(by_sub.get(sid) or 0)
            if sn <= 0:
                continue
            sub = dict(s)
            sub["member_count"] = sn
            subs.append(sub)
        row = dict(c)
        row["member_count"] = n
        row["subclusters"] = sorted(subs, key=lambda s: -int(s.get("member_count") or 0))
        clusters_out.append(row)
    clusters_out.sort(key=lambda c: -int(c.get("member_count") or 0))

    prev_filter = dict(report.get("filter") or {})
    report["index"] = new_index
    report["clusters"] = clusters_out
    report["n_articles"] = len(new_index)
    report["articles"] = len(new_index)
    report["n_clusters"] = len(clusters_out)
    report["n_subclusters"] = sum(len(c.get("subclusters") or []) for c in clusters_out)
    report["noise"] = int(sum(1 for i in new_index if i.get("is_noise")))
    report["filter"] = {**prev_filter, **filter_meta}
    report["by_month"] = [{"month": m, "count": by_month[m]} for m in sorted(by_month, reverse=True)]
    report["filter_orgs"] = [
        {"name": name, "patent_count": count}
        for name, count in sorted(org_counter.items(), key=lambda p: (-p[1], p[0].lower()))
    ]
    report["patents"] = {
        "total": len(new_index),
        "members": len(new_index),
        "clustered": int(sum(1 for i in new_index if not i.get("is_noise"))),
        "noise": int(sum(1 for i in new_index if i.get("is_noise"))),
    }
    report["note"] = note
    bak = path.with_name(f"{flow}_clusters_report.{backup_suffix}.json")
    if not bak.exists():
        bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "ok",
        "flow": flow,
        "report": str(path),
        "backup": str(bak) if bak.exists() else None,
        "filter": report["filter"],
        "n_articles": len(new_index),
        "n_clusters": len(clusters_out),
        "n_subclusters": report["n_subclusters"],
    }


def slim_existing_report(
    flow: str,
    *,
    relevant_only: bool = True,
    interfax_per_day: int = 2,
    dedupe_titles: bool = True,
) -> dict[str, Any]:
    """Ужать уже готовый clusters_report без повторного Lab (имена кластеров сохраняются)."""
    path = report_path(flow)
    if not path.exists():
        return {"status": "skip", "reason": "no_report", "flow": flow}
    report = json.loads(path.read_text(encoding="utf-8"))
    index = list(report.get("index") or [])
    for item in index:
        if not item.get("datatime"):
            item["datatime"] = item.get("date_norm") or item.get("date") or ""
    kept, stats = filter_flow_rows(
        index,
        flow,
        relevant_only=relevant_only,
        interfax_per_day=interfax_per_day,
        dedupe_titles=dedupe_titles,
    )
    keep_ids = {str(i.get("article_id") or i.get("patent_id")) for i in kept}
    return _rewrite_report_index(
        flow,
        keep_ids=keep_ids,
        filter_meta={
            "relevant_only": relevant_only,
            "interfax_per_day": interfax_per_day,
            "dedupe_titles": dedupe_titles,
            **stats,
        },
        note=(
            f"Поток «{flow}»: отфильтровано {stats['input']}→{stats['output']} "
            f"(релевантность ТЭК, Interfax ≤{interfax_per_day}/день). "
            f"Имена кластеров Lab сохранены; для новых границ тем перезапустите cluster_flow_news_lab.py."
        ),
        backup_suffix="full",
    )


def slim_report_keep_ids(
    flow: str,
    keep_ids: set[str],
    *,
    filter_meta: dict[str, Any] | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Ужать отчёт до явного списка article_id (например после Lab oilgas-стрижки)."""
    meta = dict(filter_meta or {})
    meta.setdefault("keep_ids", len(keep_ids))
    return _rewrite_report_index(
        flow,
        keep_ids=keep_ids,
        filter_meta=meta,
        note=note
        or (
            f"Поток «{flow}»: Lab oilgas-фильтр, осталось {len(keep_ids)} статей. "
            f"Для новых границ тем перезапустите cluster_flow_news_lab.py --keep-ids …"
        ),
        backup_suffix="pre_oilgas_lab",
    )


def ensure_embeddings(
    flow: str,
    *,
    force: bool = False,
    local: bool = True,
    llm: LLMClient | None = None,
    year_from: int = MIN_YEAR_DEFAULT,
    limit: int = 0,
    relevant_only: bool = False,
    interfax_per_day: int = 0,
    dedupe_titles: bool = True,
    keep_ids: set[str] | None = None,
) -> dict[str, Any]:
    ensure_dirs()
    FLOW_TAGS_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_flow_articles(
        flow,
        year_from=year_from,
        limit=limit,
        relevant_only=relevant_only,
        interfax_per_day=interfax_per_day,
        dedupe_titles=dedupe_titles,
        keep_ids=keep_ids,
    )
    if len(rows) < 3:
        return {"status": "skip", "reason": "not_enough_articles", "n": len(rows)}

    epath = embed_path(flow)
    mpath = embed_manifest_path(flow)
    if epath.exists() and mpath.exists() and not force:
        try:
            man = json.loads(mpath.read_text(encoding="utf-8"))
            if int(man.get("n") or 0) == len(rows) and man.get("model"):
                return {"status": "cached", "n": len(rows), "model": man.get("model")}
        except Exception:
            pass

    client = llm or LLMClient()
    model = "tfidf-svd-256"
    if local or not client.enabled:
        emb, ids = _local_tfidf_embeddings(rows)
        model = f"tfidf-svd-{emb.shape[1]}"
    else:
        try:
            texts = [article_text(r.get("title") or "", r.get("text") or "") or " " for r in rows]
            ids = np.array([r["article_id"] for r in rows], dtype=str)
            vectors = np.asarray(client.embed(texts, batch_size=16), dtype="float32")
            emb = _normalize(vectors)
            model = get_settings().embedding_model
        except Exception as exc:
            print(f"[flow-cluster:{flow}] API embed fail → TF-IDF: {exc!r}", flush=True)
            emb, ids = _local_tfidf_embeddings(rows)
            model = f"tfidf-svd-{emb.shape[1]}"

    np.savez_compressed(epath, embeddings=emb, article_id=ids)
    mpath.write_text(
        json.dumps(
            {
                "n": int(len(ids)),
                "dim": int(emb.shape[1]),
                "model": model,
                "flow": flow,
                "year_from": year_from,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"status": "ok", "n": int(len(ids)), "dim": int(emb.shape[1]), "model": model}


def load_embeddings(flow: str) -> tuple[np.ndarray, np.ndarray]:
    path = embed_path(flow)
    if not path.exists():
        return np.zeros((0, 64), dtype="float32"), np.array([], dtype=str)
    payload = np.load(path, allow_pickle=True)
    return payload["embeddings"].astype("float32"), payload["article_id"].astype(str)


def _desired_sub_k(n_members: int, *, max_subclusters: int, min_sub: int) -> int:
    """Сколько подкластеров для родителя: 2…max_subclusters по размеру группы."""
    cap = max(2, int(max_subclusters))
    if n_members < 40:
        want = 2
    elif n_members < 80:
        want = 3
    elif n_members < 120:
        want = 4
    else:
        want = cap
    by_size = max(2, n_members // max(min_sub, 2))
    return min(want, cap, by_size)


def run_cluster(
    flow: str,
    *,
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    year_from: int = MIN_YEAR_DEFAULT,
    limit: int = 0,
    n_clusters: int | None = None,
    max_subclusters: int | None = None,
    auto_clusters: bool = False,
    relevant_only: bool = False,
    interfax_per_day: int = 0,
    dedupe_titles: bool = True,
    keep_ids: set[str] | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    client = llm or LLMClient(settings)
    rows_list = load_flow_articles(
        flow,
        year_from=year_from,
        limit=limit,
        relevant_only=relevant_only,
        interfax_per_day=interfax_per_day,
        dedupe_titles=dedupe_titles,
        keep_ids=keep_ids,
    )
    rows = {r["article_id"]: r for r in rows_list}
    embeddings, article_ids = load_embeddings(flow)
    if len(article_ids) < 3:
        return {"status": "skip", "reason": "not_enough", "n": int(len(article_ids))}

    keep = set(rows.keys())
    mask = np.array([str(a) in keep for a in article_ids], dtype=bool)
    if mask.any() and int(mask.sum()) < len(article_ids):
        embeddings = embeddings[mask]
        article_ids = article_ids[mask]

    auto_k = max(6, min(24, max(2, len(article_ids) // 40)))
    if auto_clusters and not (n_clusters and int(n_clusters) >= 2):
        k = auto_k
    else:
        k = int(n_clusters) if n_clusters and int(n_clusters) >= 2 else DEFAULT_N_CLUSTERS
    k = max(2, min(k, max(2, len(article_ids) // 2)))
    sub_cap = (
        int(max_subclusters)
        if max_subclusters is not None and int(max_subclusters) >= 2
        else DEFAULT_MAX_SUBCLUSTERS
    )
    print(
        f"[flow-cluster:{flow}] MiniBatchKMeans k={k} "
        f"(default={DEFAULT_N_CLUSTERS}, auto={auto_k}, max_sub={sub_cap})",
        flush=True,
    )
    labels, probs = _fallback_kmeans(embeddings, n_clusters=k)
    xy = _svd_xy(embeddings)

    use_llm = bool(client.enabled)
    prompt = CLUSTER_PROMPTS[flow]
    sub_prompt = SUB_PROMPTS[flow]
    print(
        f"[flow-cluster:{flow}] naming ({'llm:' + settings.llm_model if use_llm else 'heuristic'})",
        flush=True,
    )

    cluster_titles: dict[int, tuple[str, str]] = {}
    label_ids = sorted({int(x) for x in labels.tolist() if int(x) >= 0})
    for i, label in enumerate(label_ids, start=1):
        mask_l = labels == label
        titles: list[str] = []
        abstracts: list[str] = []
        for aid in article_ids[mask_l]:
            row = rows.get(str(aid)) or {}
            if row.get("title"):
                titles.append(str(row["title"]))
            if row.get("text"):
                abstracts.append(str(row["text"])[:240])
        if not use_llm:
            cluster_titles[label] = _heuristic_name(titles[:40])
            continue
        try:
            print(f"[flow-cluster:{flow}] llm name {i}/{len(label_ids)} fl{label}…", flush=True)
            named = client.json_call(
                prompt,
                {"titles": titles[:18], "abstracts": abstracts[:10], "flow": flow},
                max_retries=2,
            )
            name = str(named.get("name") or "").strip()
            desc = str(named.get("description") or "").strip()
            if not name:
                raise ValueError("empty LLM name")
            cluster_titles[label] = (name[:80], desc or f"Группа новостей вокруг темы «{name}».")
        except Exception as exc:
            print(f"[flow-cluster:{flow}] llm name failed fl{label}: {exc}", flush=True)
            cluster_titles[label] = _heuristic_name(titles[:40])

    # подкластеры
    from sklearn.cluster import MiniBatchKMeans

    min_parent = max(12, int(settings.subcluster_min_parent_size))
    min_sub = int(settings.subcluster_min_size)
    id_to_idx = {str(aid): i for i, aid in enumerate(article_ids)}
    sub_by_parent: dict[str, list[dict[str, Any]]] = {}
    member_sub: dict[str, tuple[str | None, int | None, str | None]] = {}

    for label in label_ids:
        cid = f"fl{label}"
        mask_l = labels == label
        n_members = int(mask_l.sum())
        if n_members < min_parent:
            continue
        local_ids = [str(a) for a in article_ids[mask_l]]
        titles = [(rows.get(a) or {}).get("title") or "" for a in local_ids]
        texts = [(rows.get(a) or {}).get("text") or "" for a in local_ids]
        idx = np.array([id_to_idx[a] for a in local_ids], dtype=int)
        local_emb = embeddings[idx]
        k_sub = _desired_sub_k(n_members, max_subclusters=sub_cap, min_sub=min_sub)
        if k_sub < 2:
            continue
        try:
            km = MiniBatchKMeans(
                n_clusters=k_sub, random_state=42, n_init=8, batch_size=min(128, n_members)
            )
            sl = km.fit_predict(local_emb)
        except Exception:
            continue
        subs: list[dict[str, Any]] = []
        for lid in sorted({int(x) for x in sl.tolist()}):
            smask = sl == lid
            if int(smask.sum()) < min_sub:
                continue
            sub_titles = [titles[j] for j, ok in enumerate(smask.tolist()) if ok]
            sub_abstracts = [str(texts[j])[:200] for j, ok in enumerate(smask.tolist()) if ok]
            sub_name = compress_label(_heuristic_name(sub_titles)[0])
            if use_llm:
                try:
                    print(f"[flow-cluster:{flow}] llm sub {cid}_s{lid}…", flush=True)
                    named = client.json_call(
                        sub_prompt,
                        {
                            "titles": sub_titles[:14],
                            "abstracts": sub_abstracts[:8],
                            "parent_title": cluster_titles.get(label, ("", ""))[0],
                        },
                        max_retries=2,
                    )
                    llm_name = str(named.get("cluster_name") or named.get("name") or "").strip()
                    if llm_name:
                        sub_name = compress_label(llm_name)
                except Exception as exc:
                    print(f"[flow-cluster:{flow}] llm sub failed {cid}_s{lid}: {exc}", flush=True)
            sid = f"{cid}_s{lid}"
            subs.append(
                {"id": sid, "local_id": lid, "title": sub_name, "member_count": int(smask.sum())}
            )
            for j, ok in enumerate(smask.tolist()):
                if ok:
                    member_sub[local_ids[j]] = (sid, lid, sub_name)
        if len(subs) >= 2:
            kept = sorted(subs, key=lambda s: -s["member_count"])[:sub_cap]
            keep_ids = {s["id"] for s in kept}
            for aid, (sid, s_local, s_title) in list(member_sub.items()):
                if sid and sid.startswith(f"{cid}_") and sid not in keep_ids:
                    member_sub.pop(aid, None)
            sub_by_parent[cid] = kept

    counts: Counter[str] = Counter()
    for label in labels.tolist():
        if int(label) >= 0:
            counts[f"fl{int(label)}"] += 1

    clusters_out: list[dict[str, Any]] = []
    for cid in sorted(counts.keys(), key=lambda c: -counts[c]):
        lid = int(cid.replace("fl", ""))
        title, desc = cluster_titles.get(lid, (f"Тема {cid}", ""))
        clusters_out.append(
            {
                "id": cid,
                "title": title,
                "description": desc,
                "member_count": int(counts[cid]),
                "subclusters": sub_by_parent.get(cid, []),
            }
        )

    org_counter: Counter[str] = Counter()
    index: list[dict[str, Any]] = []
    for aid, label, prob, x, y in zip(article_ids, labels, probs, xy[:, 0], xy[:, 1], strict=False):
        row = rows.get(str(aid)) or {}
        is_noise = 1 if int(label) < 0 else 0
        cid = None if is_noise else f"fl{int(label)}"
        ctitle = cluster_titles[int(label)][0] if cid and int(label) in cluster_titles else None
        sid, s_local, s_title = member_sub.get(str(aid), (None, None, None))
        source = str(row.get("source") or "")
        if source:
            org_counter[source] += 1
        date = str(row.get("datatime") or "")[:10]
        index.append(
            {
                "patent_id": str(aid),
                "article_id": str(aid),
                "identity": source,
                "title": (row.get("title") or "")[:180],
                "abstract": (row.get("text") or "")[:1200],
                "date": date,
                "date_norm": date,
                "patentee": source[:120],
                "link": row.get("link") or "",
                "source": source,
                "cluster_id": cid,
                "cluster_title": ctitle,
                "sub_cluster_id": sid,
                "sub_cluster_title": s_title,
                "sub_local_id": s_local,
                "is_noise": is_noise,
                "org_names": [source] if source else [],
                "probability": float(prob),
                "umap_x": float(x),
                "umap_y": float(y),
                "kind": "news",
            }
        )

    index.sort(key=lambda item: (1 if item.get("date_norm") else 0, item.get("date_norm") or ""), reverse=True)
    by_month: Counter[str] = Counter()
    for item in index:
        month = (item.get("date_norm") or "")[:7]
        if len(month) == 7:
            by_month[month] += 1

    filter_orgs = [
        {"name": name, "patent_count": count}
        for name, count in sorted(org_counter.items(), key=lambda p: (-p[1], p[0].lower()))
    ]

    report = {
        "source": "flow_news_clusters",
        "flow": flow,
        "mode": "news",
        "method": "minibatch_kmeans+llm" if use_llm else "minibatch_kmeans+heuristic",
        "year_from": year_from,
        "requested_n_clusters": k,
        "max_subclusters": sub_cap,
        "n_articles": len(index),
        "n_clusters": len(clusters_out),
        "n_subclusters": sum(len(c.get("subclusters") or []) for c in clusters_out),
        "noise": int(sum(1 for i in index if i.get("is_noise"))),
        "articles": len(index),
        "patents": {
            "total": len(index),
            "members": len(index),
            "clustered": int(sum(1 for i in index if not i.get("is_noise"))),
            "noise": int(sum(1 for i in index if i.get("is_noise"))),
        },
        "by_month": [{"month": m, "count": by_month[m]} for m in sorted(by_month, reverse=True)],
        "clusters": clusters_out,
        "science_orgs": {"total": 0, "items": [], "note": ""},
        "filter_orgs": filter_orgs,
        "index": index,
        "note": (
            f"Поток «{flow}»: MiniBatchKMeans k={k}, до {sub_cap} подкластеров, имена Lab LLM. "
            f"Статьи с меткой {flow}, год ≥ {year_from}."
        ),
    }
    out = report_path(flow)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "ok",
        "method": report["method"],
        "n_articles": len(index),
        "n_clusters": len(clusters_out),
        "n_subclusters": report["n_subclusters"],
        "noise": report["noise"],
        "report": str(out),
    }


def run_flow_news_cluster_pipeline(
    flow: str,
    *,
    force_embeddings: bool = True,
    local_embeddings: bool = True,
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    year_from: int = MIN_YEAR_DEFAULT,
    limit: int = 0,
    n_clusters: int | None = None,
    max_subclusters: int | None = None,
    auto_clusters: bool = False,
    relevant_only: bool = False,
    interfax_per_day: int = 0,
    dedupe_titles: bool = True,
    keep_ids: set[str] | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    client = llm or LLMClient(settings)
    emb = ensure_embeddings(
        flow,
        force=force_embeddings,
        local=local_embeddings,
        llm=client,
        year_from=year_from,
        limit=limit,
        relevant_only=relevant_only,
        interfax_per_day=interfax_per_day,
        dedupe_titles=dedupe_titles,
        keep_ids=keep_ids,
    )
    cluster = run_cluster(
        flow,
        settings=settings,
        llm=client,
        year_from=year_from,
        limit=limit,
        n_clusters=n_clusters,
        max_subclusters=max_subclusters,
        auto_clusters=auto_clusters,
        relevant_only=relevant_only,
        interfax_per_day=interfax_per_day,
        dedupe_titles=dedupe_titles,
        keep_ids=keep_ids,
    )
    return {"embeddings": emb, "cluster": cluster}


def _article_tag_meta(flow: str, links: set[str]) -> dict[str, dict[str, Any]]:
    """link → {reason, tags}: причина попадания в поток и соседние потоки."""
    if not links:
        return {}
    init_db()
    out: dict[str, dict[str, Any]] = {}
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT link, flow_tags_json, tag_reasons_json FROM articles
            WHERE instr(flow_tags_json, ?) > 0 AND link IS NOT NULL AND link != ''
            """,
            (flow,),
        ).fetchall()
    for row in rows:
        link = str(row["link"] or "").strip()
        if link not in links:
            continue
        try:
            tags = json.loads(row["flow_tags_json"] or "[]")
        except json.JSONDecodeError:
            tags = []
        try:
            reasons = json.loads(row["tag_reasons_json"] or "{}")
        except json.JSONDecodeError:
            reasons = {}
        reason = str((reasons or {}).get(flow) or "").strip() if isinstance(reasons, dict) else ""
        if reason.lower().startswith("эвристика"):
            reason = ""
        out[link] = {
            "reason": reason[:300],
            "tags": [t for t in tags if isinstance(t, str) and t != flow],
        }
    return out


def _file_date(path: Path) -> str:
    from datetime import datetime

    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return ""


_PAYLOAD_CACHE: dict[str, tuple[tuple[float, ...], dict[str, Any]]] = {}


def _payload_stamp(flow: str) -> tuple[float, ...]:
    paths = [
        report_path(flow),
        FLOW_TAGS_DIR / f"{flow}_enrich_lab.json",
        FLOW_TAGS_DIR / f"{flow}_enrich_lab_decisions.jsonl",
    ]
    return tuple(p.stat().st_mtime if p.exists() else 0.0 for p in paths)


def flow_cluster_payload(flow: str) -> dict[str, Any] | None:
    """Лёгкий payload для портала (без abstract/index-дублей).

    Полный текст — через flow_article_detail.
    """
    path = report_path(flow)
    if not path.exists():
        return None
    stamp = _payload_stamp(flow)
    cached = _PAYLOAD_CACHE.get(flow)
    if cached and cached[0] == stamp:
        return cached[1]
    payload = _build_flow_cluster_payload(flow, path)
    _PAYLOAD_CACHE[flow] = (stamp, payload)
    return payload


def _build_flow_cluster_payload(flow: str, path: Path) -> dict[str, Any]:
    from gartner.pipeline.flow_enrich import load_enrich

    report = json.loads(path.read_text(encoding="utf-8"))
    index = report.get("index") or []
    titles = {
        str(i.get("article_id") or i.get("patent_id") or ""): str(i.get("title") or "") for i in index
    }
    enrich = load_enrich(flow, titles)
    try:
        tag_meta = _article_tag_meta(flow, {str(i.get("link") or "").strip() for i in index})
    except Exception:
        tag_meta = {}
    items: list[dict[str, Any]] = []
    by_source: Counter[str] = Counter()
    by_month: Counter[str] = Counter()
    by_cluster: Counter[str] = Counter()
    n_enriched = 0
    for item in index:
        source = str(item.get("source") or "") or "(без источника)"
        by_source[source] += 1
        date = str(item.get("date_norm") or item.get("date") or "")[:10]
        month = date[:7]
        if len(month) == 7:
            by_month[month] += 1
        cid = item.get("cluster_id") or ("noise" if item.get("is_noise") else "other")
        if cid:
            by_cluster[str(cid)] += 1
        row = {
            "title": (item.get("title") or "")[:160],
            "date": date,
            "source": item.get("source") or "",
            "link": item.get("link") or "",
            "cluster_id": cid,
            "cluster_title": item.get("cluster_title")
            or ("Без устойчивой темы" if item.get("is_noise") else "Кластер"),
            "article_id": item.get("article_id") or item.get("patent_id"),
        }
        if item.get("sub_cluster_id"):
            row["sub_cluster_id"] = item.get("sub_cluster_id")
            row["sub_cluster_title"] = item.get("sub_cluster_title")
        meta = tag_meta.get(str(item.get("link") or "").strip()) or {}
        row["reason"] = meta.get("reason") or ""
        row["tags"] = meta.get("tags") or []
        extra = enrich.get(str(row["article_id"] or ""))
        if extra:
            row["enrich"] = extra
            n_enriched += 1
        items.append(row)

    clusters = []
    for c in report.get("clusters") or []:
        cid = str(c.get("id") or "")
        n = int(by_cluster.get(cid) or 0)
        if n <= 0:
            continue
        row = dict(c)
        row["member_count"] = n
        row["subclusters"] = list(c.get("subclusters") or [])[: int(report.get("max_subclusters") or 5)]
        clusters.append(row)

    return {
        "source": "flow_news_clusters",
        "flow": flow,
        "mode": "news",
        "method": report.get("method"),
        "year_from": report.get("year_from"),
        "requested_n_clusters": report.get("requested_n_clusters"),
        "max_subclusters": report.get("max_subclusters"),
        "n_articles": len(items),
        "n_clusters": len(clusters),
        "n_subclusters": sum(len(c.get("subclusters") or []) for c in clusters),
        "noise": int(sum(1 for i in items if i.get("is_noise"))),
        "articles": len(items),
        "note": report.get("note") or "",
        "generated_at": _file_date(path),
        "directions": list(COARSE_DIRECTIONS),
        "enrich_meta": {
            "n_enriched": n_enriched,
            "n_total": len(items),
            "partial": 0 < n_enriched < len(items),
            "model": "Lab qwen3-32b" if n_enriched else "",
        },
        "clusters": clusters,
        "by_source": [
            {"source": name, "count": count}
            for name, count in sorted(by_source.items(), key=lambda p: (-p[1], p[0].lower()))
        ],
        "by_month": [{"month": m, "count": by_month[m]} for m in sorted(by_month, reverse=True)],
        "items": items,
        # index пустой в list-API — текст только в detail
        "index": [],
        "science_orgs": {"total": 0, "items": [], "note": ""},
        "filter_orgs": [
            {"name": name, "patent_count": count}
            for name, count in sorted(by_source.items(), key=lambda p: (-p[1], p[0].lower()))
        ],
    }


def flow_article_detail(flow: str, article_id: str) -> dict[str, Any] | None:
    path = report_path(flow)
    if not path.exists():
        return None
    report = json.loads(path.read_text(encoding="utf-8"))
    aid = str(article_id)
    for item in report.get("index") or []:
        if str(item.get("article_id") or item.get("patent_id")) == aid:
            from gartner.pipeline.flow_enrich import load_enrich_raw, postprocess

            raw = load_enrich_raw(flow).get(aid)
            link = str(item.get("link") or "").strip()
            try:
                meta = _article_tag_meta(flow, {link}).get(link) or {}
            except Exception:
                meta = {}
            return {
                "enrich": postprocess(flow, raw, title=str(item.get("title") or "")) if raw else None,
                "reason": meta.get("reason") or "",
                "tags": meta.get("tags") or [],
                "article_id": item.get("article_id") or item.get("patent_id"),
                "title": item.get("title") or "",
                "abstract": item.get("abstract") or "",
                "date": item.get("date_norm") or item.get("date") or "",
                "source": item.get("source") or "",
                "link": item.get("link") or "",
                "cluster_id": item.get("cluster_id"),
                "cluster_title": item.get("cluster_title"),
                "sub_cluster_id": item.get("sub_cluster_id"),
                "sub_cluster_title": item.get("sub_cluster_title"),
                "kind": "news",
                "flow": flow,
            }
    return None
