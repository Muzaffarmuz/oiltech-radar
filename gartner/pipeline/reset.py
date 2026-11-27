"""Сброс БД и удаление синтетических данных (seed/legacy)."""

from __future__ import annotations

import shutil
from pathlib import Path

from gartner.config import CACHE_DIR, DATA_DIR, DB_PATH, PORTAL_DIR, RAW_DIR, ensure_dirs
from gartner.db import connect, init_db


def reset_all(*, keep_raw: bool = False) -> dict[str, str]:
    ensure_dirs()
    if DB_PATH.exists():
        DB_PATH.unlink()
    if CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    portal_json = PORTAL_DIR / "portal_data.json"
    if portal_json.exists():
        portal_json.unlink()
    if not keep_raw and RAW_DIR.exists():
        for path in RAW_DIR.iterdir():
            if path.is_file():
                path.unlink()
    init_db()
    return {"db": str(DB_PATH), "status": "empty"}


def purge_synthetic_rows() -> dict[str, int]:
    """Удалить из БД seed/legacy/example ссылки, если они уже попали."""
    init_db()
    deleted = {"articles": 0, "events": 0, "members": 0, "clusters": 0}
    with connect() as conn:
        fake_articles = conn.execute(
            """
            SELECT article_id, link FROM articles
            WHERE link LIKE '%/seed/%'
               OR link LIKE '%/legacy/%'
               OR link LIKE 'legacy://%'
               OR link LIKE '%example.com%'
            """
        ).fetchall()
        for row in fake_articles:
            aids = row["article_id"]
            events = conn.execute("SELECT event_id FROM events WHERE article_id=?", (aids,)).fetchall()
            for ev in events:
                conn.execute("DELETE FROM cluster_members WHERE event_id=?", (ev["event_id"],))
                deleted["members"] += 1
                conn.execute("DELETE FROM events WHERE event_id=?", (ev["event_id"],))
                deleted["events"] += 1
            conn.execute("DELETE FROM articles WHERE article_id=?", (aids,))
            deleted["articles"] += 1
        # legacy clusters without remaining members
        legacy = conn.execute("SELECT cluster_id FROM clusters WHERE cluster_id LIKE 'legacy_%'").fetchall()
        for row in legacy:
            n = conn.execute(
                "SELECT COUNT(*) AS n FROM cluster_members WHERE cluster_id=?",
                (row["cluster_id"],),
            ).fetchone()["n"]
            if n == 0:
                conn.execute("DELETE FROM subclusters WHERE parent_cluster_id=?", (row["cluster_id"],))
                conn.execute("DELETE FROM cluster_forecasts WHERE cluster_id=?", (row["cluster_id"],))
                conn.execute("DELETE FROM clusters WHERE cluster_id=?", (row["cluster_id"],))
                deleted["clusters"] += 1
    return deleted


if __name__ == "__main__":
    import json

    print(json.dumps(reset_all(), ensure_ascii=False, indent=2))
