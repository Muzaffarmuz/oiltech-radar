"""SQLite-хранилище: articles, events, clusters, snapshots."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from gartner.config import DB_PATH, ensure_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    article_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    datatime TEXT,
    source TEXT,
    link TEXT UNIQUE NOT NULL,
    scraped_at TEXT NOT NULL,
    processed INTEGER NOT NULL DEFAULT 0,
    flow_tags_json TEXT,
    tag_reasons_json TEXT,
    flow_tagged_at TEXT,
    science_directions_json TEXT,
    science_dir_tagged_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    article_id TEXT NOT NULL,
    topic_label TEXT NOT NULL,
    ai_summary TEXT,
    company TEXT,
    company_normalized TEXT,
    category TEXT,
    segment_text TEXT,
    datatime TEXT,
    source TEXT,
    link TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(article_id) REFERENCES articles(article_id)
);

CREATE TABLE IF NOT EXISTS clusters (
    cluster_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    stage TEXT,
    segment_focus TEXT,
    innovation_score REAL,
    execution_score REAL,
    centroid_json TEXT,
    title_embedding_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cluster_members (
    event_id TEXT PRIMARY KEY,
    cluster_id TEXT,
    probability REAL,
    is_noise INTEGER NOT NULL DEFAULT 0,
    umap_x REAL,
    umap_y REAL,
    assigned_at TEXT NOT NULL,
    sub_cluster_id TEXT,
    sub_probability REAL,
    FOREIGN KEY(event_id) REFERENCES events(event_id),
    FOREIGN KEY(cluster_id) REFERENCES clusters(cluster_id)
);

CREATE TABLE IF NOT EXISTS subclusters (
    subcluster_id TEXT PRIMARY KEY,
    parent_cluster_id TEXT NOT NULL,
    local_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    member_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(parent_cluster_id) REFERENCES clusters(cluster_id)
);

CREATE TABLE IF NOT EXISTS cluster_forecasts (
    cluster_id TEXT PRIMARY KEY,
    direction TEXT,
    confidence REAL,
    narrative TEXT,
    action TEXT,
    monthly_multipliers_json TEXT,
    provider TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(cluster_id) REFERENCES clusters(cluster_id)
);

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    diff_json TEXT,
    manifest_json TEXT
);

CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS custom_sources (
    source_id TEXT PRIMARY KEY,
    domain TEXT NOT NULL UNIQUE,
    start_url TEXT NOT NULL,
    list_url TEXT,
    rules_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    last_error TEXT,
    last_probe_json TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS patents (
    patent_id TEXT PRIMARY KEY,
    identity TEXT NOT NULL,
    title TEXT,
    abstract TEXT,
    publication_date TEXT,
    filing_date TEXT,
    application_number TEXT,
    ipc TEXT,
    applicant TEXT,
    inventor TEXT,
    patentee TEXT,
    source_url TEXT,
    directions_json TEXT,
    imported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS article_patent_links (
    article_id TEXT NOT NULL,
    patent_id TEXT NOT NULL,
    match_type TEXT NOT NULL DEFAULT 'number_in_text',
    created_at TEXT NOT NULL,
    PRIMARY KEY (article_id, patent_id),
    FOREIGN KEY(article_id) REFERENCES articles(article_id),
    FOREIGN KEY(patent_id) REFERENCES patents(patent_id)
);

CREATE TABLE IF NOT EXISTS patent_clusters (
    cluster_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    member_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS patent_cluster_members (
    patent_id TEXT PRIMARY KEY,
    cluster_id TEXT,
    probability REAL,
    is_noise INTEGER NOT NULL DEFAULT 0,
    umap_x REAL,
    umap_y REAL,
    assigned_at TEXT NOT NULL,
    sub_cluster_id TEXT,
    sub_probability REAL,
    FOREIGN KEY(patent_id) REFERENCES patents(patent_id),
    FOREIGN KEY(cluster_id) REFERENCES patent_clusters(cluster_id)
);

CREATE TABLE IF NOT EXISTS patent_subclusters (
    subcluster_id TEXT PRIMARY KEY,
    parent_cluster_id TEXT NOT NULL,
    local_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    member_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(parent_cluster_id) REFERENCES patent_clusters(cluster_id)
);

CREATE INDEX IF NOT EXISTS idx_articles_processed ON articles(processed);
CREATE INDEX IF NOT EXISTS idx_events_company ON events(company_normalized);
CREATE INDEX IF NOT EXISTS idx_members_cluster ON cluster_members(cluster_id);
CREATE INDEX IF NOT EXISTS idx_subclusters_parent ON subclusters(parent_cluster_id);
CREATE INDEX IF NOT EXISTS idx_custom_sources_enabled ON custom_sources(enabled);
CREATE INDEX IF NOT EXISTS idx_patents_pub_date ON patents(publication_date);
CREATE INDEX IF NOT EXISTS idx_article_patent_patent ON article_patent_links(patent_id);
CREATE INDEX IF NOT EXISTS idx_patent_members_cluster ON patent_cluster_members(cluster_id);
CREATE INDEX IF NOT EXISTS idx_patent_sub_parent ON patent_subclusters(parent_cluster_id);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    ensure_dirs()
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        # миграции для уже существующих БД
        _ensure_column(conn, "cluster_members", "sub_cluster_id", "sub_cluster_id TEXT")
        _ensure_column(conn, "cluster_members", "sub_probability", "sub_probability REAL")
        _ensure_column(conn, "articles", "flow_tags_json", "flow_tags_json TEXT")
        _ensure_column(conn, "articles", "tag_reasons_json", "tag_reasons_json TEXT")
        _ensure_column(conn, "articles", "flow_tagged_at", "flow_tagged_at TEXT")
        _ensure_column(conn, "articles", "science_directions_json", "science_directions_json TEXT")
        _ensure_column(conn, "articles", "science_dir_tagged_at", "science_dir_tagged_at TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_members_sub ON cluster_members(sub_cluster_id)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_flow_tagged ON articles(flow_tagged_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_patent_members_sub ON patent_cluster_members(sub_cluster_id)"
        )


def clear_subclusters(db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute("UPDATE cluster_members SET sub_cluster_id=NULL, sub_probability=NULL")
        conn.execute("DELETE FROM subclusters")


def clear_patent_subclusters(db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute("UPDATE patent_cluster_members SET sub_cluster_id=NULL, sub_probability=NULL")
        conn.execute("DELETE FROM patent_subclusters")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def set_state(key: str, value: str, db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO run_state(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def get_state(key: str, default: str = "", db_path: Path | None = None) -> str:
    with connect(db_path) as conn:
        row = conn.execute("SELECT value FROM run_state WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def cache_get(cache_key: str, db_path: Path | None = None) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT payload_json FROM llm_cache WHERE cache_key=?", (cache_key,)).fetchone()
    if not row:
        return None
    return json.loads(row["payload_json"])


def cache_set(cache_key: str, kind: str, payload: dict[str, Any], db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO llm_cache(cache_key, kind, payload_json, created_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET payload_json=excluded.payload_json, created_at=excluded.created_at
            """,
            (cache_key, kind, json.dumps(payload, ensure_ascii=False), utc_now()),
        )
