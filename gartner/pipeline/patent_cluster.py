"""Кластеризация патентов тем же алгоритмом, что и портал (UMAP→HDBSCAN→подкластеры).

Отдельные таблицы/кэши — новостные clusters/cluster_members не трогаем.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

import numpy as np

from gartner.company import normalize_text
from gartner.config import CACHE_DIR, Settings, ensure_dirs, get_settings
from gartner.db import (
    cache_get,
    cache_set,
    clear_patent_subclusters,
    connect,
    init_db,
    utc_now,
)
from gartner.llm import LLMClient
from gartner.pipeline.subcluster import _best_split, _entropy, compress_label

EMBED_PATH = CACHE_DIR / "patent_embeddings.npz"
MANIFEST_PATH = CACHE_DIR / "patent_embedding_manifest.json"
CENTROIDS_PATH = CACHE_DIR / "patent_cluster_centroids.npz"
SUB_CENTROIDS_PATH = CACHE_DIR / "patent_subcluster_centroids.npz"
PARAMS_PATH = CACHE_DIR / "patent_cluster_params.json"
REPORT_PATH = CACHE_DIR.parent / "runs" / "patents" / "patent_clusters_report.json"
AUDITED_PORTAL_PATH = CACHE_DIR.parent / "runs" / "patents" / "audited_portal.json"
FLOW_SNAPSHOT_PATH = CACHE_DIR.parent / "runs" / "patents" / "science_flow_payload.json"
DETAILS_SNAPSHOT_PATH = CACHE_DIR.parent / "runs" / "patents" / "science_patent_details.json"

CLUSTER_PROMPT = """Ты — старший аналитик патентов нефтегаза.
Сформулируй ОДНУ высокоуровневую тему (3–7 слов) по группе близких патентов.
Без названий компаний и номеров патентов.
Верни ТОЛЬКО JSON: {"name":"...","description":"1-2 предложения","confidence":0.0}
"""

SUB_PROMPT = """Ты строишь иерархическую таксономию патентных тем нефтегаза.

Верни ТОЛЬКО JSON:
{
 "cluster_name": "...",
 "confidence": 0.0
}

ПРАВИЛА:
- 2–5 слов максимум
- НА РУССКОМ ЯЗЫКЕ
- Без слов-пустышек (цифровизация, инновации, оптимизация, системы)
- Фокус на технологии или механизме
"""


def patent_text(title: str, abstract: str) -> str:
    title = (title or "").strip()
    abstract = (abstract or "").strip()
    if title and abstract:
        # эмбеддинг-лимит: реферат урезаем
        return f"{title}. {abstract[:1200]}"
    return title or abstract[:1400]


def _hash_embed(text: str, dim: int = 64) -> np.ndarray:
    rng = np.random.default_rng(abs(hash(text)) % (2**32))
    vec = rng.normal(size=dim).astype("float32")
    vec /= max(float(np.linalg.norm(vec)), 1e-8)
    return vec


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return vectors / norms


def _embed_texts(texts: list[str], client: LLMClient) -> np.ndarray:
    if client.enabled:
        # мелкие батчи — OpenRouter/прокси часто рвёт крупные embedding-запросы
        vectors = np.asarray(client.embed(texts, batch_size=16), dtype="float32")
        return _normalize(vectors)
    return np.vstack([_hash_embed(t) for t in texts]).astype("float32")


def _local_tfidf_embeddings(rows: list[dict[str, Any]], *, dim: int = 256) -> tuple[np.ndarray, np.ndarray]:
    """Локальные эмбеддинги без API: TF-IDF + TruncatedSVD (для HDBSCAN при лимите OpenRouter)."""
    from sklearn.decomposition import TruncatedSVD
    from sklearn.feature_extraction.text import TfidfVectorizer

    texts = [patent_text(r.get("title") or "", r.get("abstract") or "") or " " for r in rows]
    ids = np.array([r["patent_id"] for r in rows], dtype=str)
    if len(texts) < 3:
        emb = np.vstack([_hash_embed(t, dim=dim) for t in texts]).astype("float32")
        return emb, ids
    vectorizer = TfidfVectorizer(
        max_features=12000,
        ngram_range=(1, 2),
        min_df=2,
        max_df=0.9,
        sublinear_tf=True,
    )
    matrix = vectorizer.fit_transform(texts)
    n_comp = max(2, min(dim, matrix.shape[1] - 1, matrix.shape[0] - 1))
    svd = TruncatedSVD(n_components=n_comp, random_state=42)
    emb = svd.fit_transform(matrix).astype("float32")
    return _normalize(emb), ids


def load_patent_embeddings() -> tuple[np.ndarray, np.ndarray]:
    ensure_dirs()
    if not EMBED_PATH.exists():
        return np.zeros((0, 64), dtype="float32"), np.array([], dtype=str)
    payload = np.load(EMBED_PATH, allow_pickle=True)
    return payload["embeddings"].astype("float32"), payload["patent_id"].astype(str)


def save_patent_embeddings(embeddings: np.ndarray, patent_ids: np.ndarray) -> None:
    ensure_dirs()
    np.savez_compressed(EMBED_PATH, embeddings=embeddings, patent_id=patent_ids)


def _write_manifest(embeddings: np.ndarray, patent_ids: np.ndarray, model: str) -> None:
    MANIFEST_PATH.write_text(
        json.dumps(
            {
                "rows": int(len(patent_ids)),
                "dim": int(embeddings.shape[1]) if len(embeddings) else 0,
                "model": model,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _load_patent_rows() -> list[dict[str, Any]]:
    with connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                """
                SELECT patent_id, title, abstract, publication_date, patentee, applicant, ipc
                FROM patents
                ORDER BY publication_date ASC, patent_id ASC
                """
            ).fetchall()
        ]


def ensure_patent_embeddings(
    llm: LLMClient | None = None,
    settings: Settings | None = None,
    *,
    force: bool = False,
    local: bool = False,
) -> dict[str, Any]:
    """Эмбеддинги title+abstract для всех патентов."""
    init_db()
    settings = settings or get_settings()
    client = llm or LLMClient(settings)
    rows = _load_patent_rows()
    if not rows:
        empty = np.zeros((0, 64), dtype="float32")
        save_patent_embeddings(empty, np.array([], dtype=str))
        _write_manifest(empty, np.array([], dtype=str), "empty")
        return {"total": 0, "new": 0, "dim": 0}

    if local:
        embeddings, patent_ids = load_patent_embeddings()
        model_name = ""
        if MANIFEST_PATH.exists():
            try:
                model_name = str(
                    json.loads(MANIFEST_PATH.read_text(encoding="utf-8")).get("model") or ""
                )
            except Exception:
                model_name = ""
        if (
            not force
            and model_name == "tfidf-svd-256"
            and len(patent_ids) == len(rows)
            and set(patent_ids.tolist()) == {r["patent_id"] for r in rows}
        ):
            print(f"[patent-embed] reuse local cache ({len(patent_ids)} x {embeddings.shape[1]})", flush=True)
            return {
                "total": int(len(patent_ids)),
                "new": 0,
                "dim": int(embeddings.shape[1]),
                "model": model_name,
            }
        print(f"[patent-embed] local TF-IDF+SVD for {len(rows)} patents", flush=True)
        embeddings, patent_ids = _local_tfidf_embeddings(rows, dim=256)
        save_patent_embeddings(embeddings, patent_ids)
        _write_manifest(embeddings, patent_ids, "tfidf-svd-256")
        return {
            "total": int(len(patent_ids)),
            "new": int(len(patent_ids)),
            "dim": int(embeddings.shape[1]),
            "rebuilt": 1,
            "model": "tfidf-svd-256",
        }

    embeddings, patent_ids = load_patent_embeddings()
    known = set(patent_ids.tolist()) if len(patent_ids) else set()
    model_name = ""
    if MANIFEST_PATH.exists():
        try:
            model_name = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")).get("model", "")
        except Exception:
            model_name = ""

    # Полный rebuild только по --force. Иначе доэмбеддим недостающие (не сжигаем квоту).
    need_rebuild = bool(force)
    if (
        not need_rebuild
        and len(embeddings)
        and client.enabled
        and (model_name in {"hash-fallback", "tfidf-svd-256"} or int(embeddings.shape[1]) < 128)
    ):
        # слабые локальные вектора — при живом API можно пересчитать целиком
        need_rebuild = True

    def _embed_chunked(pending: list[dict[str, Any]], existing_emb: np.ndarray, existing_ids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Эмбеддит пачками и сохраняет прогресс на диск."""
        emb = existing_emb
        ids = existing_ids
        chunk = 64
        for i in range(0, len(pending), chunk):
            part = pending[i : i + chunk]
            texts = [patent_text(r.get("title") or "", r.get("abstract") or "") for r in part]
            print(f"[patent-embed] {min(i + chunk, len(pending))}/{len(pending)} (+{len(ids)})", flush=True)
            vectors = _embed_texts(texts, client)
            new_ids = np.array([r["patent_id"] for r in part], dtype=str)
            if len(emb):
                if emb.shape[1] != vectors.shape[1]:
                    raise RuntimeError(f"dim mismatch {emb.shape[1]} vs {vectors.shape[1]}")
                emb = np.vstack([emb, vectors])
                ids = np.concatenate([ids, new_ids])
            else:
                emb = vectors
                ids = new_ids
            save_patent_embeddings(emb, ids)
            model = settings.embedding_model if client.enabled else "hash-fallback"
            _write_manifest(emb, ids, model)
        return emb, ids

    if need_rebuild:
        empty = np.zeros((0, 64), dtype="float32")
        embeddings, patent_ids = _embed_chunked(rows, empty, np.array([], dtype=str))
        model = settings.embedding_model if client.enabled else "hash-fallback"
        return {
            "total": int(len(patent_ids)),
            "new": int(len(patent_ids)),
            "dim": int(embeddings.shape[1]),
            "rebuilt": 1,
            "model": model,
        }

    # Убрать из кэша id, которых больше нет в БД; доэмбеддить только missing
    if len(patent_ids):
        live_ids = {r["patent_id"] for r in rows}
        keep = np.array([pid in live_ids for pid in patent_ids], dtype=bool)
        if keep.size and not keep.all():
            embeddings = embeddings[keep]
            patent_ids = patent_ids[keep]
            known = set(patent_ids.tolist())
            save_patent_embeddings(embeddings, patent_ids)

    missing = [r for r in rows if r["patent_id"] not in known]
    if not missing:
        return {
            "total": len(rows),
            "new": 0,
            "dim": int(embeddings.shape[1]) if len(embeddings) else 0,
            "model": model_name or ("hash-fallback" if not client.enabled else settings.embedding_model),
        }

    embeddings, patent_ids = _embed_chunked(missing, embeddings, patent_ids)
    model = settings.embedding_model if client.enabled else "hash-fallback"
    return {"total": int(len(patent_ids)), "new": len(missing), "dim": int(embeddings.shape[1]), "model": model}


def _fallback_kmeans(embeddings: np.ndarray, n_clusters: int = 12) -> tuple[np.ndarray, np.ndarray]:
    from sklearn.cluster import MiniBatchKMeans

    k = max(2, min(n_clusters, len(embeddings)))
    model = MiniBatchKMeans(n_clusters=k, random_state=42, n_init=10)
    labels = model.fit_predict(embeddings)
    dists = model.transform(embeddings)
    probs = 1.0 / (1.0 + dists[np.arange(len(labels)), labels])
    return labels.astype(int), probs.astype(float)


def _svd_xy(emb: np.ndarray) -> np.ndarray:
    from sklearn.decomposition import TruncatedSVD

    k = 2 if emb.shape[1] >= 2 else 1
    svd = TruncatedSVD(n_components=k, random_state=42)
    out = svd.fit_transform(emb)
    if out.shape[1] == 1:
        out = np.column_stack([out[:, 0], np.zeros(len(out))])
    return out


def run_full_patent_cluster(settings: Settings | None = None) -> dict[str, Any]:
    init_db()
    ensure_dirs()
    settings = settings or get_settings()
    embeddings, patent_ids = load_patent_embeddings()
    if len(patent_ids) < 3:
        return {"status": "skip", "reason": "not_enough_patents", "n": int(len(patent_ids))}

    mcs = int(settings.hdbscan_min_cluster_size)
    if len(patent_ids) < 40:
        mcs = min(mcs, max(3, len(patent_ids) // 5))
    # для ~2k патентов чуть крупнее кластеры, чем у новостей
    if len(patent_ids) >= 500:
        mcs = max(mcs, 10)
    n_neighbors = min(int(settings.umap_n_neighbors), max(2, len(patent_ids) - 1))
    method = "umap_hdbscan"

    model_name = ""
    if MANIFEST_PATH.exists():
        try:
            model_name = str(json.loads(MANIFEST_PATH.read_text(encoding="utf-8")).get("model") or "")
        except Exception:
            model_name = ""
    # UMAP на TF-IDF+SVD часто зависает (spectral init) — HDBSCAN сразу по векторам
    skip_umap = model_name.startswith("tfidf-svd")

    try:
        import hdbscan

        if skip_umap:
            print("[patent-cluster] HDBSCAN on TF-IDF/SVD (skip UMAP)", flush=True)
            reduced = embeddings
            method = "svd_hdbscan"
        else:
            import umap

            print("[patent-cluster] UMAP → HDBSCAN", flush=True)
            reducer = umap.UMAP(
                n_neighbors=n_neighbors,
                min_dist=float(settings.umap_min_dist),
                n_components=min(int(settings.umap_n_components), max(2, len(patent_ids) - 2)),
                metric="cosine",
                random_state=42,
            )
            reduced = reducer.fit_transform(embeddings)
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=mcs,
            min_samples=min(int(settings.hdbscan_min_samples), mcs),
            metric="euclidean",
            cluster_selection_method="eom",
            prediction_data=True,
        )
        labels = clusterer.fit_predict(reduced)
        probs = clusterer.probabilities_
        n_found = len({int(x) for x in labels.tolist() if int(x) >= 0})
        if n_found == 0:
            raise RuntimeError("HDBSCAN produced only noise")
        xy = _svd_xy(embeddings)
        if not skip_umap:
            try:
                import umap

                reducer_2d = umap.UMAP(
                    n_neighbors=n_neighbors,
                    min_dist=float(settings.umap_min_dist),
                    n_components=2,
                    metric="cosine",
                    random_state=42,
                )
                xy = reducer_2d.fit_transform(embeddings)
            except Exception:
                xy = _svd_xy(embeddings)
    except Exception as exc:
        print(f"[patent-cluster] fallback kmeans: {exc!r}", flush=True)
        k = max(8, min(24, len(patent_ids) // 40))
        labels, probs = _fallback_kmeans(embeddings, n_clusters=k)
        xy = _svd_xy(embeddings)
        method = f"kmeans_fallback:{type(exc).__name__}"

    centroids: dict[str, np.ndarray] = {}
    for label in sorted(set(labels.tolist())):
        if int(label) < 0:
            continue
        mask = labels == label
        centroids[str(int(label))] = embeddings[mask].mean(axis=0)
    if centroids:
        cid_list = list(centroids.keys())
        mat = np.vstack([centroids[c] for c in cid_list]).astype("float32")
        np.savez_compressed(CENTROIDS_PATH, cluster_ids=np.array(cid_list), centroids=mat)

    PARAMS_PATH.write_text(
        json.dumps(
            {
                "umap_n_neighbors": n_neighbors,
                "umap_min_dist": settings.umap_min_dist,
                "umap_n_components": settings.umap_n_components,
                "hdbscan_min_cluster_size": mcs,
                "hdbscan_min_samples": settings.hdbscan_min_samples,
                "method": method,
                "n_patents": int(len(patent_ids)),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    now = utc_now()
    clear_patent_subclusters()
    with connect() as conn:
        conn.execute("DELETE FROM patent_cluster_members")
        conn.execute("DELETE FROM patent_clusters")
        member_counts: Counter[str] = Counter()
        for label in labels.tolist():
            if int(label) >= 0:
                member_counts[f"pc{int(label)}"] += 1
        for label in sorted(set(labels.tolist())):
            if int(label) < 0:
                continue
            cid = f"pc{int(label)}"
            conn.execute(
                """
                INSERT INTO patent_clusters(cluster_id, title, description, member_count, created_at, updated_at)
                VALUES(?, ?, '', ?, ?, ?)
                """,
                (cid, f"Патентная тема {cid}", int(member_counts[cid]), now, now),
            )
        for pid, label, prob, x, y in zip(patent_ids, labels, probs, xy[:, 0], xy[:, 1], strict=False):
            is_noise = 1 if int(label) < 0 else 0
            cid = None if is_noise else f"pc{int(label)}"
            conn.execute(
                """
                INSERT INTO patent_cluster_members(
                    patent_id, cluster_id, probability, is_noise, umap_x, umap_y, assigned_at,
                    sub_cluster_id, sub_probability
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (str(pid), cid, float(prob), is_noise, float(x), float(y), now),
            )

    n_clusters = len({int(l) for l in labels.tolist() if int(l) >= 0})
    noise = int((labels < 0).sum())
    return {
        "status": "ok",
        "method": method,
        "n_patents": int(len(patent_ids)),
        "n_clusters": n_clusters,
        "noise": noise,
        "min_cluster_size": mcs,
    }


def _heuristic_name(titles: list[str]) -> tuple[str, str]:
    if not titles:
        return "Патентное направление", "Кластер близких патентов по эмбеддингам."
    # частые значимые слова из заголовков
    stop = {
        "способ",
        "устройство",
        "система",
        "метод",
        "для",
        "при",
        "или",
        "его",
        "их",
        "and",
        "the",
        "of",
    }
    words: Counter[str] = Counter()
    for t in titles:
        for w in re.findall(r"[А-Яа-яA-Za-z]{4,}", t or ""):
            wl = w.lower()
            if wl not in stop:
                words[wl] += 1
    if words:
        top = [w for w, _ in words.most_common(3)]
        name = " ".join(top)[:48]
        name = name[:1].upper() + name[1:]
    else:
        top_title = titles[0]
        name = top_title if len(top_title) <= 48 else top_title[:45] + "…"
    return name, f"Группа патентов вокруг темы «{name}»."


def enrich_patent_clusters(
    llm: LLMClient | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    init_db()
    settings = get_settings()
    client = llm or LLMClient(settings)
    now = utc_now()
    updated = 0

    with connect() as conn:
        clusters = [dict(r) for r in conn.execute("SELECT * FROM patent_clusters").fetchall()]

    print(
        f"[patent-enrich] clusters={len(clusters)} llm={client.enabled} force={force}",
        flush=True,
    )
    for i, cluster in enumerate(clusters, start=1):
        cid = cluster["cluster_id"]
        with connect() as conn:
            rows = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT p.title, p.abstract, p.patentee
                    FROM patent_cluster_members m
                    JOIN patents p ON p.patent_id = m.patent_id
                    WHERE m.cluster_id=? AND m.is_noise=0
                    """,
                    (cid,),
                ).fetchall()
            ]
        if not rows:
            continue
        titles = [r.get("title") or "" for r in rows]
        current = cluster.get("title") or ""
        looks_placeholder = current.startswith("Патентная тема")
        cache_key = f"patent_cluster_name:{cid}:{hash(tuple(sorted(set(titles))[:12]))}"
        if force:
            named = None
        else:
            named = cache_get(cache_key)
        if named is None:
            if client.enabled:
                try:
                    print(
                        f"[patent-enrich] llm name {i}/{len(clusters)} {cid}…",
                        flush=True,
                    )
                    named = client.json_call(
                        CLUSTER_PROMPT,
                        {
                            "titles": titles[:18],
                            "abstracts": [(r.get("abstract") or "")[:240] for r in rows[:10]],
                        },
                        max_retries=2,
                    )
                except Exception as exc:
                    print(f"[patent-enrich] llm fail {cid}: {exc}", flush=True)
                    name, desc = _heuristic_name(titles)
                    named = {"name": name, "description": desc, "confidence": 0.4}
            else:
                name, desc = _heuristic_name(titles)
                named = {"name": name, "description": desc, "confidence": 0.4}
            cache_set(cache_key, "patent_cluster_name", named)

        new_title = normalize_text(named.get("name")) or _heuristic_name(titles)[0]
        new_desc = normalize_text(named.get("description")) or ""
        title = new_title if force or looks_placeholder or not current else current
        description = (
            new_desc
            if force or looks_placeholder or not cluster.get("description")
            else (new_desc or cluster.get("description") or "")
        )

        with connect() as conn:
            conn.execute(
                """
                UPDATE patent_clusters
                SET title=?, description=?, member_count=?, updated_at=?
                WHERE cluster_id=?
                """,
                (title, description, len(rows), now, cid),
            )
        updated += 1
    return {"clusters_updated": updated}


def _name_subcluster(
    titles: list[str],
    abstracts: list[str],
    vectors: np.ndarray,
    llm: LLMClient | None,
) -> str:
    base = titles[0] if titles else "Контур"
    # Для подкластеров по умолчанию эвристика (OpenRouter часто 429); Cursor LLM — отдельно
    if llm is None or not getattr(llm, "enabled", False) or len(titles) < 5:
        return compress_label(_heuristic_name(titles)[0] if titles else base)
    cache_key = f"patent_sub_name:{hash(tuple(sorted(set(titles))[:10]))}"
    cached = cache_get(cache_key)
    if cached and cached.get("cluster_name"):
        return compress_label(str(cached["cluster_name"]))
    # примеры у центроида
    if len(vectors):
        c = vectors.mean(axis=0)
        n = float(np.linalg.norm(c))
        if n > 0:
            c = c / n
        sims = vectors @ c
        order = np.argsort(sims)[::-1][:5]
        examples = [{"title": titles[int(i)], "abstract": (abstracts[int(i)] or "")[:200]} for i in order]
    else:
        examples = [{"title": t, "abstract": (a or "")[:200]} for t, a in zip(titles[:5], abstracts[:5])]
    try:
        res = llm.json_call(SUB_PROMPT, {"examples": examples})
    except Exception:
        return compress_label(base)
    name = normalize_text(res.get("cluster_name"))
    conf = float(res.get("confidence") or 0)
    if conf < 0.55 or not name:
        name = compress_label(base)
    else:
        name = compress_label(name)
    cache_set(cache_key, "patent_subcluster_name", {"cluster_name": name, "confidence": conf})
    return name


def run_patent_subclusters(llm: LLMClient | None = None, settings: Settings | None = None) -> dict[str, Any]:
    init_db()
    ensure_dirs()
    settings = settings or get_settings()
    client = llm or LLMClient(settings)
    clear_patent_subclusters()

    embeddings, patent_ids = load_patent_embeddings()
    if len(patent_ids) == 0:
        return {"status": "skip", "reason": "no_embeddings", "parents": 0, "subclusters": 0}

    id_to_idx = {str(pid): i for i, pid in enumerate(patent_ids)}
    min_parent = int(settings.subcluster_min_parent_size)
    min_sub = int(settings.subcluster_min_size)
    min_entropy = float(settings.subcluster_min_entropy)

    with connect() as conn:
        parents = [
            dict(r)
            for r in conn.execute(
                """
                SELECT cluster_id, COUNT(*) AS n
                FROM patent_cluster_members
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
                    SELECT m.patent_id, p.title, p.abstract
                    FROM patent_cluster_members m
                    JOIN patents p ON p.patent_id = m.patent_id
                    WHERE m.cluster_id=? AND m.is_noise=0
                    """,
                    (cid,),
                ).fetchall()
            ]
        rows = [r for r in rows if r["patent_id"] in id_to_idx]
        if len(rows) < min_parent:
            continue
        titles = [r.get("title") or "" for r in rows]
        # для патентов entropy по «укороченным» заголовкам
        short = [compress_label(t, max_words=4) for t in titles]
        if _entropy(short) < min_entropy:
            continue

        idx = np.array([id_to_idx[r["patent_id"]] for r in rows], dtype=int)
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
            sub_titles = [titles[i] for i, m in enumerate(mask) if m]
            sub_abs = [rows[i].get("abstract") or "" for i, m in enumerate(mask) if m]
            title = _name_subcluster(sub_titles, sub_abs, local_emb[mask], client)
            with connect() as conn:
                conn.execute(
                    """
                    INSERT INTO patent_subclusters(
                        subcluster_id, parent_cluster_id, local_id, title, member_count, created_at, updated_at
                    )
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
                    UPDATE patent_cluster_members
                    SET sub_cluster_id=?, sub_probability=?
                    WHERE patent_id=?
                    """,
                    (sub_id, float(probs[i]) if sub_id else None, row["patent_id"]),
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


def build_patent_cluster_report() -> dict[str, Any]:
    with connect() as conn:
        clusters = [
            dict(r)
            for r in conn.execute(
                """
                SELECT c.cluster_id, c.title, c.description, c.member_count,
                       COUNT(m.patent_id) AS assigned
                FROM patent_clusters c
                LEFT JOIN patent_cluster_members m
                  ON m.cluster_id = c.cluster_id AND m.is_noise=0
                GROUP BY c.cluster_id
                ORDER BY assigned DESC
                """
            ).fetchall()
        ]
        subs = [
            dict(r)
            for r in conn.execute(
                """
                SELECT subcluster_id, parent_cluster_id, title, member_count
                FROM patent_subclusters
                ORDER BY parent_cluster_id, member_count DESC
                """
            ).fetchall()
        ]
        noise = conn.execute(
            "SELECT COUNT(*) AS n FROM patent_cluster_members WHERE is_noise=1"
        ).fetchone()["n"]
        total = conn.execute("SELECT COUNT(*) AS n FROM patent_cluster_members").fetchone()["n"]

    by_parent: dict[str, list[dict[str, Any]]] = {}
    for s in subs:
        by_parent.setdefault(s["parent_cluster_id"], []).append(
            {
                "id": s["subcluster_id"],
                "title": s["title"],
                "member_count": s["member_count"],
            }
        )

    items = []
    for c in clusters:
        items.append(
            {
                "cluster_id": c["cluster_id"],
                "title": c["title"],
                "description": c.get("description") or "",
                "member_count": int(c["assigned"] or c["member_count"] or 0),
                "subclusters": by_parent.get(c["cluster_id"], []),
            }
        )

    report = {
        "patents_assigned": int(total),
        "noise": int(noise),
        "n_clusters": len(items),
        "n_subclusters": len(subs),
        "clusters": items,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def run_patent_cluster_pipeline(
    *,
    force_embeddings: bool = False,
    skip_enrich: bool = False,
    local_embeddings: bool = False,
    llm: LLMClient | None = None,
    settings: Settings | None = None,
    force_relabel: bool = False,
    skip_cluster: bool = False,
) -> dict[str, Any]:
    settings = settings or get_settings()
    client = llm or LLMClient(settings)
    out: dict[str, Any] = {}
    if not skip_cluster:
        try:
            out["embeddings"] = ensure_patent_embeddings(
                llm=client,
                settings=settings,
                force=force_embeddings,
                local=local_embeddings,
            )
        except Exception as exc:
            # OpenRouter free-tier 429 и т.п. — дожимаем локально, не бросаем весь пайплайн
            msg = str(exc)
            if local_embeddings or "429" in msg or "Rate limit" in msg or "Embedding failed" in msg:
                print(f"[patent-embed] API failed ({exc!r}); fallback to local TF-IDF+SVD", flush=True)
                out["embeddings"] = ensure_patent_embeddings(
                    llm=client, settings=settings, force=True, local=True
                )
            else:
                raise
        out["cluster"] = run_full_patent_cluster(settings=settings)
    if not skip_enrich:
        out["enrich"] = enrich_patent_clusters(llm=client, force=force_relabel)
    out["subcluster"] = run_patent_subclusters(llm=client, settings=settings)
    out["report"] = build_patent_cluster_report()
    return out


def _science_orgs_payload() -> list[dict[str, Any]]:
    """Вузы и НИИ из правообладателей/заявителей патентов (классификатор patent_orgs)."""
    from gartner.patent_orgs import build_unique_org_report

    with connect() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT patent_id, title, applicant, patentee FROM patents"
            ).fetchall()
        ]
    report = build_unique_org_report(rows)
    items = [
        {
            "name": item["canonical_name"],
            "org_type": item["org_type"],
            "patent_count": int(item["patent_count"] or 0),
        }
        for item in report.get("items") or []
        if item.get("org_type") in ("university", "nii") and int(item.get("patent_count") or 0) > 0
    ]
    items.sort(key=lambda row: (-row["patent_count"], row["name"].lower()))
    return items


def _load_audited_patents() -> dict[str, Any] | None:
    if not AUDITED_PORTAL_PATH.exists():
        return None
    try:
        return json.loads(AUDITED_PORTAL_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _load_flow_snapshot() -> dict[str, Any] | None:
    if not FLOW_SNAPSHOT_PATH.exists():
        return None
    try:
        payload = json.loads(FLOW_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    if not (payload.get("index") or payload.get("clusters")):
        return None
    return payload


def _load_details_snapshot() -> dict[str, Any] | None:
    if not DETAILS_SNAPSHOT_PATH.exists():
        return None
    try:
        payload = json.loads(DETAILS_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _patent_db_count() -> int:
    init_db()
    with connect() as conn:
        return int(conn.execute("SELECT COUNT(*) AS n FROM patents").fetchone()["n"] or 0)


def science_flow_payload(*, patents_per_cluster: int = 8) -> dict[str, Any]:
    """Payload для /api/flows/science: кластеры + индекс патентов для фильтров/drawer."""
    del patents_per_cluster  # превью берём из index на клиенте
    # Hosted demo: SQLite with patents is not shipped; serve prebuilt JSON snapshot.
    if _patent_db_count() == 0:
        snapshot = _load_flow_snapshot()
        if snapshot is not None:
            out = dict(snapshot)
            out["source"] = str(out.get("source") or "patent_clusters") + "_snapshot"
            return out

    init_db()
    from gartner.patent_orgs import extract_from_patent_row, load_alias_dictionary

    science_orgs = _science_orgs_payload()
    dictionary = load_alias_dictionary()
    audited = _load_audited_patents()
    audited_items = (audited or {}).get("items") or {}

    with connect() as conn:
        patent_rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT p.patent_id, p.identity, p.title, p.abstract, p.publication_date,
                       p.filing_date, p.ipc, p.patentee, p.applicant, p.inventor, p.source_url,
                       m.cluster_id, m.sub_cluster_id, m.is_noise,
                       c.title AS cluster_title,
                       s.title AS sub_cluster_title, s.local_id AS sub_local_id
                FROM patents p
                LEFT JOIN patent_cluster_members m ON m.patent_id = p.patent_id
                LEFT JOIN patent_clusters c ON c.cluster_id = m.cluster_id
                LEFT JOIN patent_subclusters s ON s.subcluster_id = m.sub_cluster_id
                ORDER BY replace(COALESCE(p.publication_date,''), '.', '-') DESC, p.patent_id DESC
                """
            ).fetchall()
        ]
        if not audited:
            total = conn.execute("SELECT COUNT(*) AS n FROM patents").fetchone()["n"]
            members_n = conn.execute("SELECT COUNT(*) AS n FROM patent_cluster_members").fetchone()["n"]
            noise = conn.execute(
                "SELECT COUNT(*) AS n FROM patent_cluster_members WHERE is_noise=1"
            ).fetchone()["n"]
            clustered = conn.execute(
                "SELECT COUNT(*) AS n FROM patent_cluster_members WHERE is_noise=0 AND cluster_id IS NOT NULL"
            ).fetchone()["n"]
            clusters = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT cluster_id, title, description, member_count
                    FROM patent_clusters
                    ORDER BY member_count DESC, cluster_id
                    """
                ).fetchall()
            ]
            subs = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT subcluster_id, parent_cluster_id, local_id, title, member_count
                    FROM patent_subclusters
                    ORDER BY parent_cluster_id, member_count DESC, local_id
                    """
                ).fetchall()
            ]
        else:
            clusters = []
            subs = []
            total = members_n = noise = clustered = 0

    if audited:
        # только прошедшие аудит патенты + темы из аудита
        filtered = []
        for row in patent_rows:
            meta = audited_items.get(str(row.get("patent_id") or ""))
            if not meta:
                continue
            row = dict(row)
            row["cluster_id"] = meta.get("cluster_id")
            row["cluster_title"] = meta.get("cluster_title")
            row["sub_cluster_id"] = meta.get("sub_cluster_id")
            row["sub_cluster_title"] = meta.get("sub_cluster_title")
            row["is_noise"] = int(meta.get("is_noise") or 0)
            row["sub_local_id"] = None
            filtered.append(row)
        patent_rows = filtered
        total = members_n = len(patent_rows)
        noise = sum(1 for r in patent_rows if r.get("is_noise"))
        clustered = total - noise
        cluster_meta = {
            str(c.get("id")): {
                "id": c.get("id"),
                "title": c.get("title"),
                "description": c.get("description") or "",
                "member_count": int(c.get("member_count") or 0),
                "subclusters": list(c.get("subclusters") or []),
            }
            for c in (audited.get("clusters") or [])
        }
    else:
        subs_by_parent: dict[str, list[dict[str, Any]]] = {}
        for s in subs:
            subs_by_parent.setdefault(s["parent_cluster_id"], []).append(
                {
                    "id": s["subcluster_id"],
                    "local_id": s["local_id"],
                    "title": s["title"],
                    "member_count": int(s["member_count"] or 0),
                }
            )
        cluster_meta = {
            c["cluster_id"]: {
                "id": c["cluster_id"],
                "title": c["title"],
                "description": c.get("description") or "",
                "member_count": int(c["member_count"] or 0),
                "subclusters": subs_by_parent.get(c["cluster_id"], []),
            }
            for c in clusters
        }

    org_counter: dict[str, int] = {}
    index: list[dict[str, Any]] = []
    for row in patent_rows:
        resolved = extract_from_patent_row(row, dictionary)
        orgs = [
            {
                "name": o["canonical_name"],
                "org_type": o["org_type"],
            }
            for o in resolved
            if o.get("org_type") != "person" and o.get("canonical_name")
        ]
        for org in orgs:
            org_counter[org["name"]] = org_counter.get(org["name"], 0) + 1
        date = str(row.get("publication_date") or "")
        # без abstract в индексе — страница иначе тянет мегабайты; реферат в /api/flows/science/patent/{id}
        index.append(
            {
                "patent_id": row["patent_id"],
                "identity": row.get("identity") or "",
                "title": (row.get("title") or "")[:180],
                "date": date,
                "date_norm": date.replace(".", "-")[:10],
                "patentee": (row.get("patentee") or row.get("applicant") or "")[:120],
                "link": row.get("source_url") or "",
                "cluster_id": row.get("cluster_id"),
                "cluster_title": row.get("cluster_title"),
                "sub_cluster_id": row.get("sub_cluster_id"),
                "sub_cluster_title": row.get("sub_cluster_title"),
                "sub_local_id": row.get("sub_local_id"),
                "is_noise": int(row.get("is_noise") or 0),
                "org_names": [o["name"] for o in orgs],
            }
        )

    all_orgs = [
        {"name": name, "patent_count": count}
        for name, count in sorted(org_counter.items(), key=lambda pair: (-pair[1], pair[0].lower()))
    ]

    by_month_counter: dict[str, int] = {}
    for item in index:
        month = (item.get("date_norm") or "")[:7]
        if len(month) == 7:
            by_month_counter[month] = by_month_counter.get(month, 0) + 1
    by_month = [
        {"month": month, "count": by_month_counter[month]}
        for month in sorted(by_month_counter, reverse=True)
    ]

    n_subclusters = (
        sum(len(c.get("subclusters") or []) for c in cluster_meta.values())
        if audited
        else len(subs)
    )
    return {
        "source": "patent_clusters_audited" if audited else "patent_clusters",
        "mode": "patents_only",
        "articles": 0,
        "patents": {
            "total": int(total),
            "members": int(members_n),
            "clustered": int(clustered),
            "noise": int(noise),
        },
        "n_clusters": len(cluster_meta),
        "n_subclusters": n_subclusters,
        "by_month": by_month,
        "clusters": list(cluster_meta.values()),
        "science_orgs": {
            "total": len(science_orgs),
            "items": science_orgs,
            "note": "Вузы и НИИ по правообладателям/заявителям патентов. Компании и физлица не входят.",
        },
        "filter_orgs": all_orgs,
        "index": index,
        "note": (
            "Патенты после Lab-аудита: только kept/reassigned."
            if audited
            else "Поток «Наука и патенты» = кластеры Роспатента (UMAP+HDBSCAN). Science-новости сюда не попадают."
        ),
    }


def science_patent_detail(patent_id: str) -> dict[str, Any] | None:
    """Карточка патента для правого drawer (реферат + мета)."""
    pid = str(patent_id or "").strip()
    if not pid:
        return None
    if _patent_db_count() == 0:
        snap = _load_details_snapshot() or {}
        item = snap.get(pid)
        return dict(item) if isinstance(item, dict) else None

    init_db()
    from gartner.patent_orgs import extract_from_patent_row, load_alias_dictionary

    audited = _load_audited_patents()
    audited_meta = None
    if audited:
        audited_meta = (audited.get("items") or {}).get(pid)
        if not audited_meta:
            return None
    with connect() as conn:
        row = conn.execute(
            """
            SELECT p.patent_id, p.identity, p.title, p.abstract, p.publication_date,
                   p.ipc, p.patentee, p.applicant, p.source_url,
                   m.cluster_id, m.sub_cluster_id,
                   c.title AS cluster_title,
                   s.title AS sub_cluster_title, s.local_id AS sub_local_id
            FROM patents p
            LEFT JOIN patent_cluster_members m ON m.patent_id = p.patent_id
            LEFT JOIN patent_clusters c ON c.cluster_id = m.cluster_id
            LEFT JOIN patent_subclusters s ON s.subcluster_id = m.sub_cluster_id
            WHERE p.patent_id=?
            """,
            (pid,),
        ).fetchone()
    if not row:
        return None
    row = dict(row)
    dictionary = load_alias_dictionary()
    orgs = [
        {"name": o["canonical_name"], "org_type": o["org_type"]}
        for o in extract_from_patent_row(row, dictionary)
        if o.get("org_type") != "person" and o.get("canonical_name")
    ]
    cluster_id = row.get("cluster_id")
    cluster_title = row.get("cluster_title")
    sub_cluster_id = row.get("sub_cluster_id")
    sub_cluster_title = row.get("sub_cluster_title")
    sub_local_id = row.get("sub_local_id")
    if audited_meta:
        cluster_id = audited_meta.get("cluster_id")
        cluster_title = audited_meta.get("cluster_title")
        sub_cluster_id = audited_meta.get("sub_cluster_id")
        sub_cluster_title = audited_meta.get("sub_cluster_title")
        sub_local_id = None
    return {
        "patent_id": row["patent_id"],
        "identity": row.get("identity") or "",
        "title": row.get("title") or "",
        "abstract": str(row.get("abstract") or "").strip(),
        "date": str(row.get("publication_date") or ""),
        "ipc": row.get("ipc") or "",
        "patentee": row.get("patentee") or row.get("applicant") or "",
        "link": row.get("source_url") or "",
        "cluster_id": cluster_id,
        "cluster_title": cluster_title,
        "sub_cluster_id": sub_cluster_id,
        "sub_cluster_title": sub_cluster_title,
        "sub_local_id": sub_local_id,
        "orgs": orgs,
    }
