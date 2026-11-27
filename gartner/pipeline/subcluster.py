"""Подкластеры внутри крупных тем (логика pt.3.7 + адаптации под меньший корпус).

Для каждого родительского кластера:
- пропускаем мелкие / однородные по topic_label;
- сетка UMAP+HDBSCAN → лучший split по silhouette;
- имена подкластеров через LLM (короткая таксономия).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

import numpy as np

from gartner.company import normalize_text
from gartner.config import CACHE_DIR, Settings, ensure_dirs, get_settings
from gartner.db import cache_get, cache_set, clear_subclusters, connect, init_db, utc_now
from gartner.llm import LLMClient
from gartner.pipeline.embeddings import load_embeddings

SUB_CENTROIDS_PATH = CACHE_DIR / "subcluster_centroids.npz"

BAD_WORDS = {
    "инновации",
    "цифровизация",
    "оптимизация",
    "решения",
    "системы",
    "платформа",
    "современные",
    "умные",
    "интеллектуальные",
    "технологии",
    "process",
    "system",
}

SUB_PROMPT = """Ты строишь иерархическую таксономию для аналитики нефтегазовых технологий.

Верни ТОЛЬКО JSON:
{
 "cluster_name": "...",
 "confidence": 0.0
}

ПРАВИЛА:
- 2–5 слов максимум
- НА РУССКОМ ЯЗЫКЕ
- Без слов-пустышек (цифровизация, инновации, оптимизация, системы)
- Без длинных фраз и названий продуктов
- Фокус на функции или механизме
"""


def compress_label(text: str, max_words: int = 8) -> str:
    text = normalize_text(text)
    text = re.sub(r"['\"«»‘’“”][^'\"«»‘’“”]{1,80}['\"«»‘’“”]", " ", text)
    text = re.sub(r"\b[А-ЯA-Zа-яa-z]+-[\dА-ЯA-Z][\dА-ЯA-Za-zа-я-]*\b", " ", text)
    text = re.sub(r"[\|/•,;+]", " ", text)
    words = [w for w in text.split() if w and w.lower() not in BAD_WORDS]
    if not words:
        return "Смешанный контур"
    return " ".join(words[:max_words])


def _entropy(labels: list[str]) -> float:
    if not labels:
        return 0.0
    counts = np.array(list(Counter(labels).values()), dtype=float)
    probs = counts / counts.sum()
    return float(-(probs * np.log2(probs + 1e-12)).sum())


def _run_umap_hdbscan(
    emb: np.ndarray, nn: int, md: float, nc: int, mcs: int, ms: int, seed: int = 42
) -> tuple[np.ndarray, np.ndarray, float]:
    import hdbscan
    import umap

    reducer = umap.UMAP(
        n_neighbors=min(nn, max(2, len(emb) - 1)),
        min_dist=md,
        n_components=min(nc, max(2, len(emb) - 2)),
        metric="cosine",
        random_state=seed,
    )
    reduced = reducer.fit_transform(emb)
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=mcs,
        min_samples=min(ms, mcs),
        metric="euclidean",
    )
    labels = clusterer.fit_predict(reduced)
    probs = clusterer.probabilities_
    valid = labels >= 0
    score = 0.0
    if int(valid.sum()) > 5 and len({int(x) for x in labels[valid].tolist()}) > 1:
        try:
            from sklearn.metrics import silhouette_score

            score = float(silhouette_score(reduced[valid], labels[valid]))
        except Exception:
            score = 0.0
    return labels.astype(int), probs.astype(float), score


def _run_hdbscan_direct(
    emb: np.ndarray, mcs: int, ms: int
) -> tuple[np.ndarray, np.ndarray, float]:
    """HDBSCAN без UMAP — быстрее и стабильнее на TF-IDF/SVD векторах."""
    import hdbscan
    from sklearn.metrics import silhouette_score

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=mcs,
        min_samples=min(ms, mcs),
        metric="euclidean",
    )
    labels = clusterer.fit_predict(emb)
    probs = clusterer.probabilities_
    valid = labels >= 0
    score = 0.0
    if int(valid.sum()) > 5 and len({int(x) for x in labels[valid].tolist()}) > 1:
        try:
            score = float(silhouette_score(emb[valid], labels[valid]))
        except Exception:
            score = 0.0
    return labels.astype(int), probs.astype(float), score


def _best_split(emb: np.ndarray, min_sub_size: int) -> dict[str, Any] | None:
    if len(emb) < max(8, min_sub_size * 2):
        return None
    best: dict[str, Any] | None = None
    max_mcs = min(20, max(min_sub_size, len(emb) // 3))

    # 1) прямой HDBSCAN (без UMAP)
    for mcs in range(min_sub_size, max_mcs + 1, 2):
        for ms in (1, 2, 3):
            try:
                labels, probs, score = _run_hdbscan_direct(emb, mcs, ms)
            except Exception:
                continue
            n_found = len({int(x) for x in labels.tolist() if int(x) >= 0})
            if n_found < 2:
                continue
            if best is None or score > best["score"]:
                best = {"labels": labels, "probs": probs, "score": score, "n_subs": n_found}
    if best is not None:
        return best

    # 2) запасной путь: UMAP-сетка (медленнее)
    umap_grid = [(5, 0.0, 2), (8, 0.1, 2), (10, 0.0, 5)]
    for nn, md, nc in umap_grid:
        for mcs in range(min_sub_size, max_mcs + 1, 2):
            for ms in (1, 2, 3):
                try:
                    labels, probs, score = _run_umap_hdbscan(emb, nn, md, nc, mcs, ms)
                except Exception:
                    continue
                n_found = len({int(x) for x in labels.tolist() if int(x) >= 0})
                if n_found < 2:
                    continue
                if best is None or score > best["score"]:
                    best = {"labels": labels, "probs": probs, "score": score, "n_subs": n_found}
    return best


def _centroid_examples(topics: list[str], summaries: list[str], vectors: np.ndarray, k: int = 5) -> list[dict[str, str]]:
    if len(vectors) == 0:
        return []
    c = vectors.mean(axis=0)
    n = float(np.linalg.norm(c))
    if n > 0:
        c = c / n
    sims = vectors @ c
    order = np.argsort(sims)[::-1][:k]
    out = []
    for i in order:
        out.append({"topic": topics[int(i)], "summary": summaries[int(i)]})
    return out


def _name_subcluster(
    topics: list[str],
    summaries: list[str],
    vectors: np.ndarray,
    llm: LLMClient | None,
) -> str:
    base = topics[0] if topics else "Контур"
    if llm is None or not llm.enabled or len(topics) < 6:
        return compress_label(base)
    cache_key = f"sub_name:{hash(tuple(sorted(set(topics))[:10]))}"
    cached = cache_get(cache_key)
    if cached and cached.get("cluster_name"):
        return compress_label(str(cached["cluster_name"]))
    payload = {"examples": _centroid_examples(topics, summaries, vectors)}
    try:
        res = llm.json_call(SUB_PROMPT, payload)
    except Exception:
        return compress_label(base)
    name = normalize_text(res.get("cluster_name"))
    conf = float(res.get("confidence") or 0)
    if conf < 0.55 or not name:
        name = compress_label(base)
    else:
        name = compress_label(name)
    cache_set(cache_key, "subcluster_name", {"cluster_name": name, "confidence": conf})
    return name


def run_subclusters(llm: LLMClient | None = None, settings: Settings | None = None) -> dict[str, Any]:
    """Полный пересчёт подкластеров по текущим membership."""
    init_db()
    ensure_dirs()
    settings = settings or get_settings()
    client = llm or LLMClient(settings)
    clear_subclusters()

    embeddings, event_ids = load_embeddings()
    if len(event_ids) == 0:
        return {"status": "skip", "reason": "no_embeddings", "parents": 0, "subclusters": 0}

    id_to_idx = {str(eid): i for i, eid in enumerate(event_ids)}
    min_parent = int(settings.subcluster_min_parent_size)
    min_sub = int(settings.subcluster_min_size)
    min_entropy = float(settings.subcluster_min_entropy)

    with connect() as conn:
        parents = [
            dict(r)
            for r in conn.execute(
                """
                SELECT cluster_id, COUNT(*) AS n
                FROM cluster_members
                WHERE is_noise=0 AND cluster_id IS NOT NULL
                GROUP BY cluster_id
                HAVING n >= ?
                ORDER BY n DESC
                """,
                (min_parent,),
            ).fetchall()
        ]

    now = utc_now()
    parents_split = 0
    sub_total = 0
    centroid_ids: list[str] = []
    centroid_vecs: list[np.ndarray] = []

    for parent in parents:
        cid = parent["cluster_id"]
        with connect() as conn:
            rows = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT m.event_id, e.topic_label, e.ai_summary
                    FROM cluster_members m
                    JOIN events e ON e.event_id = m.event_id
                    WHERE m.cluster_id=? AND m.is_noise=0
                    """,
                    (cid,),
                ).fetchall()
            ]
        rows = [r for r in rows if r["event_id"] in id_to_idx]
        if len(rows) < min_parent:
            continue
        topics = [r.get("topic_label") or "" for r in rows]
        if _entropy(topics) < min_entropy:
            continue

        idx = np.array([id_to_idx[r["event_id"]] for r in rows], dtype=int)
        local_emb = embeddings[idx]
        best = _best_split(local_emb, min_sub)
        if best is None:
            continue

        labels = best["labels"]
        probs = best["probs"]
        local_ids = sorted({int(x) for x in labels.tolist() if int(x) >= 0})
        if len(local_ids) < 2:
            continue

        parents_split += 1
        sid_map: dict[int, str] = {}
        for local_id in local_ids:
            mask = labels == local_id
            if int(mask.sum()) < min_sub:
                continue
            sub_id = f"{cid}_s{local_id}"
            sub_topics = [topics[i] for i, m in enumerate(mask) if m]
            sub_sums = [rows[i].get("ai_summary") or "" for i, m in enumerate(mask) if m]
            title = _name_subcluster(sub_topics, sub_sums, local_emb[mask], client)
            with connect() as conn:
                conn.execute(
                    """
                    INSERT INTO subclusters(subcluster_id, parent_cluster_id, local_id, title, member_count, created_at, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(subcluster_id) DO UPDATE SET
                        title=excluded.title,
                        member_count=excluded.member_count,
                        updated_at=excluded.updated_at
                    """,
                    (sub_id, cid, int(local_id), title, int(mask.sum()), now, now),
                )
            sid_map[local_id] = sub_id
            centroid_ids.append(sub_id)
            vec = local_emb[mask].mean(axis=0)
            nrm = float(np.linalg.norm(vec))
            centroid_vecs.append(vec / nrm if nrm > 0 else vec)
            sub_total += 1

        with connect() as conn:
            for i, row in enumerate(rows):
                lab = int(labels[i])
                sub_id = sid_map.get(lab)
                conn.execute(
                    """
                    UPDATE cluster_members
                    SET sub_cluster_id=?, sub_probability=?
                    WHERE event_id=?
                    """,
                    (sub_id, float(probs[i]) if sub_id else None, row["event_id"]),
                )

    if centroid_ids:
        np.savez_compressed(
            SUB_CENTROIDS_PATH,
            subcluster_ids=np.array(centroid_ids),
            centroids=np.vstack(centroid_vecs).astype("float32"),
        )
    elif SUB_CENTROIDS_PATH.exists():
        SUB_CENTROIDS_PATH.unlink()

    return {
        "status": "ok",
        "parents_considered": len(parents),
        "parents_split": parents_split,
        "subclusters": sub_total,
        "min_parent_size": min_parent,
    }


def assign_subcluster_for_event(event_id: str, parent_cluster_id: str, vec: np.ndarray, threshold: float = 0.65) -> str | None:
    """Инкрементально присвоить событие ближайшему подкластеру родителя."""
    if not SUB_CENTROIDS_PATH.exists():
        return None
    payload = np.load(SUB_CENTROIDS_PATH, allow_pickle=True)
    ids = payload["subcluster_ids"].astype(str)
    cents = payload["centroids"].astype("float32")
    if len(ids) == 0 or cents.shape[1] != vec.shape[0]:
        return None
    mask = np.array([i.startswith(f"{parent_cluster_id}_s") for i in ids])
    if not mask.any():
        return None
    ids = ids[mask]
    cents = cents[mask]
    norms = np.linalg.norm(cents, axis=1) * (float(np.linalg.norm(vec)) + 1e-8)
    sims = (cents @ vec) / np.where(norms == 0, 1.0, norms)
    best_i = int(np.argmax(sims))
    if float(sims[best_i]) < threshold:
        return None
    return str(ids[best_i])
