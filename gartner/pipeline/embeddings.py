"""Эмбеддинги событий: инкремент только для новых row_uid."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from gartner.config import CACHE_DIR, Settings, ensure_dirs, get_settings
from gartner.db import connect, init_db
from gartner.llm import LLMClient

EMBED_PATH = CACHE_DIR / "event_embeddings.npz"
MANIFEST_PATH = CACHE_DIR / "embedding_manifest.json"


def event_text(topic: str, summary: str) -> str:
    topic = (topic or "").strip()
    summary = (summary or "").strip()
    if topic and summary:
        return f"{topic}. {summary}"
    return topic or summary


def _hash_embed(text: str, dim: int = 64) -> np.ndarray:
    """Детерминированный псевдо-эмбеддинг для офлайн-режима."""
    rng = np.random.default_rng(abs(hash(text)) % (2**32))
    vec = rng.normal(size=dim).astype("float32")
    vec /= max(float(np.linalg.norm(vec)), 1e-8)
    return vec


def load_embeddings() -> tuple[np.ndarray, np.ndarray]:
    ensure_dirs()
    if not EMBED_PATH.exists():
        return np.zeros((0, 64), dtype="float32"), np.array([], dtype=str)
    payload = np.load(EMBED_PATH, allow_pickle=True)
    return payload["embeddings"].astype("float32"), payload["event_id"].astype(str)


def save_embeddings(embeddings: np.ndarray, event_ids: np.ndarray) -> None:
    ensure_dirs()
    np.savez_compressed(EMBED_PATH, embeddings=embeddings, event_id=event_ids)


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return vectors / norms


def _embed_texts(texts: list[str], client: LLMClient) -> np.ndarray:
    if client.enabled:
        vectors = np.asarray(client.embed(texts), dtype="float32")
        return _normalize(vectors)
    return np.vstack([_hash_embed(t) for t in texts]).astype("float32")


def _write_manifest(embeddings: np.ndarray, event_ids: np.ndarray, model: str) -> None:
    MANIFEST_PATH.write_text(
        json.dumps(
            {
                "rows": int(len(event_ids)),
                "dim": int(embeddings.shape[1]) if len(embeddings) else 0,
                "model": model,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def rebuild_all_embeddings(llm: LLMClient | None = None, settings: Settings | None = None) -> dict[str, int]:
    """Полный пересчёт эмбеддингов для всех событий (нужен при смене модели/размерности)."""
    init_db()
    settings = settings or get_settings()
    client = llm or LLMClient(settings)
    with connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT event_id, topic_label, ai_summary FROM events ORDER BY created_at ASC"
        ).fetchall()]
    if not rows:
        empty = np.zeros((0, 64), dtype="float32")
        save_embeddings(empty, np.array([], dtype=str))
        _write_manifest(empty, np.array([], dtype=str), "empty")
        return {"total": 0, "new": 0, "dim": 0, "rebuilt": 1}

    texts = [event_text(r["topic_label"], r["ai_summary"] or "") for r in rows]
    embeddings = _embed_texts(texts, client)
    event_ids = np.array([r["event_id"] for r in rows], dtype=str)
    save_embeddings(embeddings, event_ids)
    model = settings.embedding_model if client.enabled else "hash-fallback"
    _write_manifest(embeddings, event_ids, model)
    return {"total": int(len(event_ids)), "new": int(len(event_ids)), "dim": int(embeddings.shape[1]), "rebuilt": 1}


def ensure_embeddings(llm: LLMClient | None = None, settings: Settings | None = None) -> dict[str, int]:
    """Доэмбеддит только события без вектора. Не даёт hash-fallback затереть LLM-эмбеддинги."""
    init_db()
    settings = settings or get_settings()
    client = llm or LLMClient(settings)
    embeddings, event_ids = load_embeddings()
    known = set(event_ids.tolist()) if len(event_ids) else set()

    with connect() as conn:
        rows = conn.execute(
            "SELECT event_id, topic_label, ai_summary FROM events ORDER BY created_at ASC"
        ).fetchall()

    # устаревший hash-кэш при включённом LLM — пересобрать в размерности модели
    if len(embeddings) and client.enabled:
        model_name = "hash-fallback"
        if MANIFEST_PATH.exists():
            try:
                model_name = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")).get("model", "")
            except Exception:
                model_name = ""
        if model_name == "hash-fallback" or int(embeddings.shape[1]) < 256:
            return rebuild_all_embeddings(llm=client, settings=settings)

    missing = [dict(r) for r in rows if r["event_id"] not in known]
    if not missing:
        return {"total": len(rows), "new": 0, "dim": int(embeddings.shape[1]) if len(embeddings) else 0}

    texts = [event_text(r["topic_label"], r["ai_summary"] or "") for r in missing]
    vectors = _embed_texts(texts, client)
    new_ids = np.array([r["event_id"] for r in missing], dtype=str)

    if len(embeddings):
        if embeddings.shape[1] != vectors.shape[1]:
            if client.enabled:
                return rebuild_all_embeddings(llm=client, settings=settings)
            # Не затираем существующие high-dim векторы offline-hash'ем.
            raise RuntimeError(
                f"Размерность эмбеддингов не совпадает ({embeddings.shape[1]} vs {vectors.shape[1]}). "
                "Проверьте API_KEY в .env и перезапустите портал, затем «Обновить данные»."
            )
        embeddings = np.vstack([embeddings, vectors])
        event_ids = np.concatenate([event_ids, new_ids])
    else:
        embeddings = vectors
        event_ids = new_ids

    save_embeddings(embeddings, event_ids)
    model = settings.embedding_model if client.enabled else "hash-fallback"
    _write_manifest(embeddings, event_ids, model)
    return {"total": int(len(event_ids)), "new": len(missing), "dim": int(embeddings.shape[1])}
