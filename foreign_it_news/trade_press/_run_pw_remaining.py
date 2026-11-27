"""Playwright только для необогащённых статей в out_trade/it_focus.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from foreign_it_news.scrape_trade_press import _headline_only  # noqa: E402
from foreign_it_news.trade_press.enrich_bodies import (  # noqa: E402
    _bad_body,
    enrich_playwright,
    log,
)


def main() -> int:
    out_dir = Path("foreign_it_news/out_trade")
    path = out_dir / "it_focus.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("articles") or []
    todo = [r for r in rows if not r.get("enriched")]
    log(f"playwright-only todo={len(todo)}")
    if not todo:
        log("nothing to do")
        return 0

    def save() -> None:
        data["n_enriched"] = sum(
            1 for r in rows if r.get("enriched") and not _bad_body(r.get("text") or "")
        )
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    ok, fail = enrich_playwright(todo, pause_s=2.0, save_cb=save)
    save()
    log(f"playwright ok={ok} fail={fail}")

    for name in ("all_articles.json", "wide_pool.json"):
        all_path = out_dir / name
        if not all_path.exists():
            continue
        all_data = json.loads(all_path.read_text(encoding="utf-8"))
        by_g = {
            r.get("resolved_from_google"): r
            for r in rows
            if r.get("enriched") and r.get("resolved_from_google")
        }
        by_t = {
            _headline_only(r.get("title") or "").lower(): r for r in rows if r.get("enriched")
        }
        n = 0
        for r in all_data.get("articles") or []:
            src = by_g.get(r.get("link")) or by_t.get(
                _headline_only(r.get("title") or "").lower()
            )
            if not src:
                continue
            r.update(
                {
                    "link": src.get("link"),
                    "text": src.get("text"),
                    "title": src.get("title") or r.get("title"),
                    "datatime": src.get("datatime") or r.get("datatime"),
                    "enriched": True,
                    "resolved_from_google": src.get("resolved_from_google"),
                    "resolved_link": src.get("resolved_link") or src.get("link"),
                }
            )
            n += 1
        all_path.write_text(json.dumps(all_data, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"patched {name}={n}")

    enriched = sum(1 for r in rows if r.get("enriched") and not _bad_body(r.get("text") or ""))
    pending = sum(1 for r in rows if not r.get("enriched"))
    log(f"DONE enriched={enriched}/{len(rows)} pending={pending}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
