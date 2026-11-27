"""Боевая кластеризация: один best-run + assign новых точек."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

import numpy as np

from gartner.config import CACHE_DIR, Settings, ensure_dirs, get_settings
from gartner.db import clear_subclusters, connect, init_db, utc_now
from gartner.pipeline.embeddings import load_embeddings
from gartner.pipeline.subcluster import assign_subcluster_for_event

CENTROIDS_PATH = CACHE_DIR / "cluster_centroids.npz"
PARAMS_PATH = CACHE_DIR / "cluster_params.json"


def default_params(settings: Settings) -> dict[str, Any]:
    return {
        "umap_n_neighbors": settings.umap_n_neighbors,
        "umap_min_dist": settings.umap_min_dist,
        "umap_n_components": settings.umap_n_components,
        "hdbscan_min_cluster_size": settings.hdbscan_min_cluster_size,
        "hdbscan_min_samples": settings.hdbscan_min_samples,
        "view": settings.cluster_view,
        "random_state": 42,
    }


def _fallback_kmeans(embeddings: np.ndarray, n_clusters: int = 8) -> tuple[np.ndarray, np.ndarray]:
    from sklearn.cluster import MiniBatchKMeans

    k = max(2, min(n_clusters, len(embeddings)))
    model = MiniBatchKMeans(n_clusters=k, random_state=42, n_init=10)
    labels = model.fit_predict(embeddings)
    # pseudo probabilities = inverse distance to centroid normalized
    dists = model.transform(embeddings)
    probs = 1.0 / (1.0 + dists[np.arange(len(labels)), labels])
    return labels.astype(int), probs.astype(float)


def run_full_cluster(settings: Settings | None = None) -> dict[str, Any]:
    """Полный пересчёт HDBSCAN (или KMeans fallback)."""
    init_db()
    ensure_dirs()
    settings = settings or get_settings()
    params = default_params(settings)
    embeddings, event_ids = load_embeddings()
    if len(event_ids) < 3:
        return {"status": "skip", "reason": "not_enough_events", "n": int(len(event_ids))}

    labels: np.ndarray
    probs: np.ndarray
    xy: np.ndarray
    method = "umap_hdbscan"
    # для малых выборок уменьшаем min_cluster_size
    mcs = int(params["hdbscan_min_cluster_size"])
    if len(event_ids) < 40:
        mcs = min(mcs, max(3, len(event_ids) // 5))
    n_neighbors = min(int(params["umap_n_neighbors"]), max(2, len(event_ids) - 1))

    def _svd_xy(emb: np.ndarray) -> np.ndarray:
        from sklearn.decomposition import TruncatedSVD

        k = 2 if emb.shape[1] >= 2 else 1
        svd = TruncatedSVD(n_components=k, random_state=42)
        out = svd.fit_transform(emb)
        if out.shape[1] == 1:
            out = np.column_stack([out[:, 0], np.zeros(len(out))])
        return out

    try:
        import hdbscan
        import umap

        reducer = umap.UMAP(
            n_neighbors=n_neighbors,
            min_dist=params["umap_min_dist"],
            n_components=min(int(params["umap_n_components"]), max(2, len(event_ids) - 2)),
            metric="cosine",
            random_state=params["random_state"],
        )
        reduced = reducer.fit_transform(embeddings)
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=mcs,
            min_samples=min(int(params["hdbscan_min_samples"]), mcs),
            metric="euclidean",
            cluster_selection_method="eom",
            prediction_data=True,
        )
        labels = clusterer.fit_predict(reduced)
        probs = clusterer.probabilities_
        n_found = len({int(x) for x in labels.tolist() if int(x) >= 0})
        if n_found == 0:
            raise RuntimeError("HDBSCAN produced only noise")
        try:
            reducer_2d = umap.UMAP(
                n_neighbors=n_neighbors,
                min_dist=params["umap_min_dist"],
                n_components=2,
                metric="cosine",
                random_state=params["random_state"],
            )
            xy = reducer_2d.fit_transform(embeddings)
        except Exception:
            xy = _svd_xy(embeddings)
        method = "umap_hdbscan"
    except Exception:
        # fallback без umap/hdbscan или при полном noise
        k = max(3, min(8, len(event_ids) // 2))
        labels, probs = _fallback_kmeans(embeddings, n_clusters=k)
        xy = _svd_xy(embeddings)
        method = "kmeans_fallback"

    # центроиды в исходном embedding space
    centroids: dict[str, np.ndarray] = {}
    for label in sorted(set(labels.tolist())):
        if int(label) < 0:
            continue
        mask = labels == label
        centroids[str(int(label))] = embeddings[mask].mean(axis=0)

    cid_list = list(centroids.keys())
    if cid_list:
        mat = np.vstack([centroids[c] for c in cid_list]).astype("float32")
        np.savez_compressed(CENTROIDS_PATH, cluster_ids=np.array(cid_list), centroids=mat)
    PARAMS_PATH.write_text(json.dumps({**params, "method": method}, ensure_ascii=False, indent=2), encoding="utf-8")

    now = utc_now()
    clear_subclusters()
    with connect() as conn:
        # сброс membership
        conn.execute("DELETE FROM cluster_members")
        # upsert clusters skeleton
        existing = {r["cluster_id"] for r in conn.execute("SELECT cluster_id FROM clusters").fetchall()}
        for label in sorted(set(labels.tolist())):
            if int(label) < 0:
                continue
            cid = f"c{int(label)}"
            if cid not in existing:
                conn.execute(
                    """
                    INSERT INTO clusters(cluster_id, title, description, stage, segment_focus,
                        innovation_score, execution_score, centroid_json, title_embedding_json, created_at, updated_at)
                    VALUES(?, ?, '', '', '', NULL, NULL, NULL, NULL, ?, ?)
                    """,
                    (cid, f"Тема {cid}", now, now),
                )
        for eid, label, prob, x, y in zip(event_ids, labels, probs, xy[:, 0], xy[:, 1], strict=False):
            is_noise = 1 if int(label) < 0 else 0
            cid = None if is_noise else f"c{int(label)}"
            conn.execute(
                """
                INSERT INTO cluster_members(event_id, cluster_id, probability, is_noise, umap_x, umap_y, assigned_at,
                    sub_cluster_id, sub_probability)
                VALUES(?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                ON CONFLICT(event_id) DO UPDATE SET
                    cluster_id=excluded.cluster_id,
                    probability=excluded.probability,
                    is_noise=excluded.is_noise,
                    umap_x=excluded.umap_x,
                    umap_y=excluded.umap_y,
                    assigned_at=excluded.assigned_at,
                    sub_cluster_id=NULL,
                    sub_probability=NULL
                """,
                (str(eid), cid, float(prob), is_noise, float(x), float(y), now),
            )

    n_clusters = len({int(l) for l in labels.tolist() if int(l) >= 0})
    noise = int((labels < 0).sum())
    return {
        "status": "ok",
        "method": method,
        "n_events": int(len(event_ids)),
        "n_clusters": n_clusters,
        "noise": noise,
    }


def assign_new_events(settings: Settings | None = None) -> dict[str, Any]:
    """Присвоить unassigned события ближайшему центроиду."""
    init_db()
    settings = settings or get_settings()
    if not CENTROIDS_PATH.exists():
        return run_full_cluster(settings)

    payload = np.load(CENTROIDS_PATH, allow_pickle=True)
    cluster_ids = payload["cluster_ids"].astype(str)
    centroids = payload["centroids"].astype("float32")
    if len(cluster_ids) == 0:
        return run_full_cluster(settings)

    embeddings, event_ids = load_embeddings()
    # после смены модели эмбеддингов старые центроиды несовместимы
    if len(embeddings) and int(embeddings.shape[1]) != int(centroids.shape[1]):
        return {
            "status": "recluster_dim_mismatch",
            "embedding_dim": int(embeddings.shape[1]),
            "centroid_dim": int(centroids.shape[1]),
            **run_full_cluster(settings),
        }

    with connect() as conn:
        assigned = {
            r["event_id"]
            for r in conn.execute("SELECT event_id FROM cluster_members WHERE is_noise=0 AND cluster_id IS NOT NULL").fetchall()
        }

    threshold = settings.assign_similarity_threshold
    now = utc_now()
    assigned_n = 0
    unassigned_n = 0

    id_to_vec = {str(eid): embeddings[i] for i, eid in enumerate(event_ids)}
    with connect() as conn:
        all_events = [r["event_id"] for r in conn.execute("SELECT event_id FROM events").fetchall()]
        for eid in all_events:
            if eid in assigned:
                continue
            vec = id_to_vec.get(eid)
            if vec is None:
                unassigned_n += 1
                conn.execute(
                    """
                    INSERT INTO cluster_members(event_id, cluster_id, probability, is_noise, umap_x, umap_y, assigned_at)
                    VALUES(?, NULL, 0, 1, NULL, NULL, ?)
                    ON CONFLICT(event_id) DO UPDATE SET is_noise=1, cluster_id=NULL, assigned_at=excluded.assigned_at
                    """,
                    (eid, now),
                )
                continue
            # cosine similarity to centroids
            norms = np.linalg.norm(centroids, axis=1) * (np.linalg.norm(vec) + 1e-8)
            sims = (centroids @ vec) / np.where(norms == 0, 1.0, norms)
            best_i = int(np.argmax(sims))
            best = float(sims[best_i])
            if best >= threshold:
                cid = str(cluster_ids[best_i])
                # ensure cluster id format cN
                if not cid.startswith("c"):
                    cid = f"c{cid}" if cid.isdigit() else cid
                sub_id = assign_subcluster_for_event(eid, cid, vec)
                conn.execute(
                    """
                    INSERT INTO cluster_members(event_id, cluster_id, probability, is_noise, umap_x, umap_y, assigned_at,
                        sub_cluster_id, sub_probability)
                    VALUES(?, ?, ?, 0, NULL, NULL, ?, ?, ?)
                    ON CONFLICT(event_id) DO UPDATE SET
                        cluster_id=excluded.cluster_id,
                        probability=excluded.probability,
                        is_noise=0,
                        assigned_at=excluded.assigned_at,
                        sub_cluster_id=excluded.sub_cluster_id,
                        sub_probability=excluded.sub_probability
                    """,
                    (eid, cid, best, now, sub_id, best if sub_id else None),
                )
                assigned_n += 1
            else:
                conn.execute(
                    """
                    INSERT INTO cluster_members(event_id, cluster_id, probability, is_noise, umap_x, umap_y, assigned_at)
                    VALUES(?, NULL, ?, 1, NULL, NULL, ?)
                    ON CONFLICT(event_id) DO UPDATE SET is_noise=1, cluster_id=NULL, probability=excluded.probability, assigned_at=excluded.assigned_at
                    """,
                    (eid, best, now),
                )
                unassigned_n += 1

    # если слишком много unassigned — полный пересчёт
    with connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
        noise = conn.execute("SELECT COUNT(*) AS n FROM cluster_members WHERE is_noise=1").fetchone()["n"]
    if total and noise / total > 0.35:
        return {"status": "recluster_triggered", "assigned": assigned_n, "unassigned": unassigned_n, **run_full_cluster(settings)}

    return {"status": "ok", "assigned": assigned_n, "unassigned": unassigned_n}
