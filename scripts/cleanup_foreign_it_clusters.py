"""Одноразово / повторно: почистить foreign_it clusters_report + portal + it_focus."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gartner.pipeline.foreign_it_cluster import (  # noqa: E402
    REPORT_PATH,
    is_junk_article,
    save_report_and_portal,
)


def scrub_it_focus() -> dict:
    path = ROOT / "foreign_it_news" / "out_trade" / "it_focus.json"
    if not path.exists():
        return {"status": "missing", "path": str(path)}
    backup = path.with_suffix(".json.bak_pre_cleanup")
    if not backup.exists():
        shutil.copy2(path, backup)
    raw = json.loads(path.read_text(encoding="utf-8"))
    articles = list(raw.get("articles") or [])
    kept = []
    dropped = 0
    for row in articles:
        title = str(row.get("title") or "")
        text = str(row.get("text") or row.get("summary") or "")
        link = str(row.get("link") or "")
        if is_junk_article(title, text, link=link):
            dropped += 1
            continue
        kept.append(row)
    raw["articles"] = kept
    raw["n_articles"] = len(kept)
    raw["cleanup"] = {"dropped_junk": dropped, "kept": len(kept)}
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok", "kept": len(kept), "dropped": dropped, "backup": str(backup)}


def main() -> None:
    if not REPORT_PATH.exists():
        raise SystemExit(f"no report: {REPORT_PATH}")
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    # backup once
    bak = REPORT_PATH.with_suffix(".json.bak_pre_cleanup")
    if not bak.exists():
        shutil.copy2(REPORT_PATH, bak)
        print(f"backup report → {bak}")
    cleaned = save_report_and_portal(report)
    focus = scrub_it_focus()
    print("cleanup:", cleaned.get("cleanup"))
    print("clusters:", [(c["id"], c["member_count"], c["title"]) for c in cleaned["clusters"]])
    print("it_focus:", focus)


if __name__ == "__main__":
    main()
