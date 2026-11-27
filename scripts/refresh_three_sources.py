"""Догрузка 3 новых источников (до N статей) → merge → extract → cluster → portal.

Scrape без LLM. Extract только по этим доменам (не трогает хвост manual_sources).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gartner.config import RAW_DIR, get_settings
from gartner.custom_sources.engine import write_articles_raw
from gartner.custom_sources.pipeline import discover_source, scrape_discovered, scrape_profile
from gartner.custom_sources.service import _source_id_from_url
from gartner.db import connect, init_db
from gartner.llm import LLMClient
from gartner.pipeline.build_portal import build_portal_payload
from gartner.pipeline.cluster import assign_new_events
from gartner.pipeline.embeddings import ensure_embeddings
from gartner.pipeline.enrich import enrich_clusters
from gartner.pipeline.extract import extract_new_articles
from gartner.pipeline.merge import merge_and_upsert

TARGETS = [
    {
        "domain": "tadviser.ru",
        "url": (
            "https://www.tadviser.ru/index.php?"
            "title=%D0%9A%D0%B0%D1%82%D0%B5%D0%B3%D0%BE%D1%80%D0%B8%D1%8F:"
            "%D0%9D%D0%B5%D1%84%D1%82%D1%8F%D0%BD%D0%B0%D1%8F_%D0%BF%D1%80%D0%BE%D0%BC%D1%8B%D1%88%D0%BB%D0%B5%D0%BD%D0%BD%D0%BE%D1%81%D1%82%D1%8C"
            "&ptype=news"
        ),
    },
    {"domain": "controlengrussia.com", "url": "https://controlengrussia.com/type/news/"},
    {"domain": "itps.com", "url": "https://itps.com/press/news/"},
]

PER_SOURCE = 150
LINK_FILTER = ["tadviser.ru", "controlengrussia.com", "itps.com"]


def log(msg: str) -> None:
    print(msg, flush=True)


def scrape_targets() -> dict:
    report: dict = {"sources": []}
    for item in TARGETS:
        log(f"SCRAPE {item['domain']} max={PER_SOURCE}")
        out_id = _source_id_from_url(item["url"])
        payload = None
        with connect() as conn:
            row = conn.execute(
                "SELECT source_id, rules_json FROM custom_sources WHERE domain=?",
                (item["domain"],),
            ).fetchone()
            if row:
                out_id = row["source_id"]
                try:
                    payload = json.loads(row["rules_json"] or "{}")
                except json.JSONDecodeError:
                    payload = None
        if payload and (payload.get("hubs") is not None or payload.get("start_url")):
            articles, stats = scrape_profile(
                payload,
                max_articles=PER_SOURCE,
                llm=None,
                max_hub_pages=25,
            )
        else:
            discovered = discover_source(item["url"], llm=None)
            articles, stats = scrape_discovered(
                discovered,
                max_articles=PER_SOURCE,
                llm=None,
                max_hub_pages=25,
            )
        path = write_articles_raw(articles, RAW_DIR / out_id)
        entry = {
            "domain": item["domain"],
            "source_id": out_id,
            "articles": len(articles),
            "links_found": stats.get("links_found"),
            "path": str(path),
        }
        report["sources"].append(entry)
        log(f"  -> {entry}")
    return report


def main() -> int:
    init_db()
    get_settings.cache_clear()
    settings = get_settings()
    client = LLMClient(settings)
    log(f"LLM enabled={client.enabled} model={settings.llm_model}")

    scrape_report = scrape_targets()
    log(f"MERGE {merge_and_upsert()}")

    # сколько статей этих доменов в БД и сколько ещё не processed
    with connect() as conn:
        for dom in LINK_FILTER:
            total = conn.execute(
                "SELECT COUNT(*) n FROM articles WHERE link LIKE ?",
                (f"%{dom}%",),
            ).fetchone()["n"]
            pending = conn.execute(
                "SELECT COUNT(*) n FROM articles WHERE processed=0 AND link LIKE ?",
                (f"%{dom}%",),
            ).fetchone()["n"]
            log(f"DB {dom}: total={total} pending={pending}")

    extract_report = extract_new_articles(
        llm=client,
        limit=PER_SOURCE * len(LINK_FILTER),
        link_substrings=LINK_FILTER,
        allow_heuristic_fallback=True,
    )
    log(f"EXTRACT {extract_report}")

    emb_report: dict
    try:
        emb_report = ensure_embeddings(llm=client, settings=settings)
        log(f"EMBED {emb_report}")
    except Exception as exc:  # noqa: BLE001
        emb_report = {"ok": False, "error": str(exc)[:400]}
        log(f"EMBED_FAIL {emb_report}")

    cluster_report: dict
    try:
        if emb_report.get("ok") is False:
            raise RuntimeError(emb_report.get("error") or "embeddings failed")
        cluster_report = assign_new_events(settings)
        log(f"CLUSTER {cluster_report}")
    except Exception as exc:  # noqa: BLE001
        cluster_report = {"ok": False, "error": str(exc)[:400]}
        log(f"CLUSTER_SKIP {cluster_report}")

    enrich_report: dict
    try:
        enrich_report = enrich_clusters(llm=client)
        log(f"ENRICH {enrich_report}")
    except Exception as exc:  # noqa: BLE001
        enrich_report = {"ok": False, "error": str(exc)[:400]}
        log(f"ENRICH_SKIP {enrich_report}")

    portal = build_portal_payload()
    log(
        f"PORTAL topics={portal['kpis']['topics']} events={portal['kpis']['events']} "
        f"articles={portal['kpis'].get('articles')}"
    )

    out = {
        "scrape": scrape_report,
        "extract": extract_report,
        "embeddings": emb_report,
        "cluster": cluster_report,
        "enrich": enrich_report,
        "portal_kpis": portal.get("kpis"),
    }
    out_path = ROOT / "data" / "runs" / "three_sources_refresh.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"WROTE {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
