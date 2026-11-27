"""Продолжение после scrape: extract (без LLM) → cluster → portal по 3 доменам."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gartner.db import connect, init_db
from gartner.pipeline.build_portal import build_portal_payload
from gartner.pipeline.extract import extract_new_articles

LINK_FILTER = ["tadviser.ru", "controlengrussia.com", "itps.com"]


def log(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    init_db()

    with connect() as conn:
        for dom in LINK_FILTER:
            pending = conn.execute(
                "SELECT COUNT(*) n FROM articles WHERE processed=0 AND link LIKE ?",
                (f"%{dom}%",),
            ).fetchone()["n"]
            log(f"pending {dom}={pending}")

    # Без API: эвристический extract (кредитов нет)
    extract_report = extract_new_articles(
        limit=500,
        link_substrings=LINK_FILTER,
        allow_heuristic_fallback=True,
        use_llm=False,
    )
    log(f"EXTRACT {extract_report}")

    # Без кредитов OpenAI эмбеддинги/enrich недоступны — не дергаем API.
    emb_report = {"ok": False, "skipped": True, "reason": "no API credits; map points not updated"}
    cluster_report = {"ok": False, "skipped": True, "reason": "needs embeddings"}
    enrich_report = {"ok": False, "skipped": True, "reason": "needs LLM"}
    log(f"EMBED_SKIP {emb_report}")
    log(f"CLUSTER_SKIP {cluster_report}")
    log(f"ENRICH_SKIP {enrich_report}")

    portal = build_portal_payload()
    log(f"PORTAL kpis={portal.get('kpis')}")

    # сколько событий с новых доменов
    with connect() as conn:
        for dom in LINK_FILTER:
            n = conn.execute(
                "SELECT COUNT(*) n FROM events WHERE link LIKE ?",
                (f"%{dom}%",),
            ).fetchone()["n"]
            log(f"events {dom}={n}")

    out = {
        "extract": extract_report,
        "embeddings": emb_report,
        "cluster": cluster_report,
        "enrich": enrich_report,
        "portal_kpis": portal.get("kpis"),
    }
    path = ROOT / "data" / "runs" / "three_sources_finish.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"WROTE {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
