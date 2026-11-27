"""Выгрузка всего содержимого SQLite в data/exports (персистентная копия)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from gartner.config import DATA_DIR, ensure_dirs
from gartner.db import connect, init_db, utc_now

EXPORT_DIR = DATA_DIR / "exports"


def export_all() -> dict[str, str]:
    init_db()
    ensure_dirs()
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().replace(":", "").replace("-", "")[:15]
    out_dir = EXPORT_DIR / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    tables = ["articles", "events", "clusters", "cluster_members", "cluster_forecasts", "snapshots"]
    paths: dict[str, str] = {}
    with connect() as conn:
        for table in tables:
            rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
            json_path = out_dir / f"{table}.json"
            json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            paths[table] = str(json_path)
            if rows:
                csv_path = out_dir / f"{table}.csv"
                with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
                    writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                    writer.writeheader()
                    writer.writerows(rows)
                paths[f"{table}_csv"] = str(csv_path)

    latest = EXPORT_DIR / "latest"
    if latest.exists():
        import shutil

        shutil.rmtree(latest)
    import shutil

    shutil.copytree(out_dir, latest)
    manifest = {"exported_at": utc_now(), "dir": str(out_dir), "files": paths}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (EXPORT_DIR / "latest_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"export_dir": str(out_dir), "latest": str(latest)}


if __name__ == "__main__":
    print(json.dumps(export_all(), ensure_ascii=False, indent=2))
