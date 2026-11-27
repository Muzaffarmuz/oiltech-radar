"""CRUD пользовательских источников + scrape в data/raw."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from gartner.config import RAW_DIR, get_settings
from gartner.custom_sources.discover import repair_rules
from gartner.custom_sources.engine import run_rules_engine, write_articles_raw
from gartner.custom_sources.firecrawl import firecrawl_enabled, firecrawl_fallback
from gartner.custom_sources.llm_gates import LlmBudget
from gartner.custom_sources.pipeline import discover_source, scrape_discovered, scrape_profile
from gartner.custom_sources.sample_sites import SAMPLE_DOMAINS, norm_host
from gartner.custom_sources.rules import domain_from_url, normalize_start_url, rules_to_dict, validate_rules_dict
from gartner.db import connect, init_db, utc_now
from gartner.llm import LLMClient


def _source_id_from_url(url: str) -> str:
    domain = domain_from_url(url)
    digest = hashlib.sha1(domain.encode("utf-8")).hexdigest()[:10]
    safe = "".join(ch if ch.isalnum() else "_" for ch in domain)[:40]
    return f"custom_{safe}_{digest}"


def add_custom_source(
    start_url: str,
    llm: LLMClient | None = None,
    *,
    require_oilgas: bool = True,
    max_articles_probe: int = 8,
) -> dict[str, Any]:
    init_db()
    url = normalize_start_url(start_url)
    domain = domain_from_url(url)
    source_id = _source_id_from_url(url)
    budget = LlmBudget()

    with connect() as conn:
        existing = conn.execute(
            "SELECT source_id, domain FROM custom_sources WHERE domain=? OR source_id=?",
            (domain, source_id),
        ).fetchone()
        if existing:
            raise ValueError(f"Источник уже добавлен: {existing['domain']}")

    discovered = discover_source(url, llm=llm, budget=budget)
    theme = discovered.get("theme") or {}
    if require_oilgas and not theme.get("accepted"):
        if theme.get("theme") == "unknown":
            raise RuntimeError(
                "Не удалось загрузить сайт, тематику проверить нельзя. "
                f"{theme.get('reason') or ''}"
            )
        raise RuntimeError(
            "Сайт отклонён по тематике (нет нефтегаза). "
            f"{theme.get('reason') or theme}"
        )

    articles, stats = scrape_discovered(discovered, max_articles=max_articles_probe, llm=llm, budget=budget)
    if not articles:
        raise RuntimeError(
            "Не удалось извлечь статьи с сайта (краул нашёл мало пригодных страниц)."
        )

    list_url = (discovered.get("hubs") or [{}])[0].get("url") or url
    probe = {
        "probe_ok": True,
        "method": "crawl_trafilatura",
        "articles": len(articles),
        "links_found": stats.get("links_found"),
        "pages_fetched": stats.get("pages_fetched") or discovered.get("pages_fetched"),
        "list_url": list_url,
        "theme": theme,
        "hubs": [h.get("url") for h in (discovered.get("hubs") or [])[:8]],
        "protection": discovered.get("protection"),
        "browser": stats.get("browser"),
        "llm_stats": stats.get("llm_stats") or discovered.get("llm_stats"),
    }
    now = utc_now()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO custom_sources(
              source_id, domain, start_url, list_url, rules_json, status,
              last_error, last_probe_json, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, 1, ?, ?)
            """,
            (
                source_id,
                domain,
                url,
                list_url,
                json.dumps(discovered, ensure_ascii=False),
                "ready",
                json.dumps(probe, ensure_ascii=False),
                now,
                now,
            ),
        )
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    write_articles_raw(articles, RAW_DIR / source_id)
    return {
        "source_id": source_id,
        "domain": domain,
        "start_url": url,
        "list_url": list_url,
        "status": "ready",
        "probe": probe,
        "enabled": True,
        "engine": "crawl_trafilatura",
    }


def list_custom_sources() -> list[dict[str, Any]]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT source_id, domain, start_url, list_url, status, last_error,
                   enabled, created_at, updated_at, last_probe_json
            FROM custom_sources
            ORDER BY created_at DESC
            """
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["enabled"] = bool(item.get("enabled"))
        try:
            item["probe"] = json.loads(item.pop("last_probe_json") or "{}")
        except json.JSONDecodeError:
            item["probe"] = {}
        out.append(item)
    return out


def delete_custom_source(source_id: str) -> bool:
    init_db()
    with connect() as conn:
        cur = conn.execute("DELETE FROM custom_sources WHERE source_id=?", (source_id,))
        return cur.rowcount > 0


def set_custom_source_enabled(source_id: str, enabled: bool) -> bool:
    init_db()
    with connect() as conn:
        cur = conn.execute(
            "UPDATE custom_sources SET enabled=?, updated_at=? WHERE source_id=?",
            (1 if enabled else 0, utc_now(), source_id),
        )
        return cur.rowcount > 0


def scrape_all_custom_sources(llm: LLMClient | None = None) -> dict[str, Any]:
    """Прогон всех enabled источников → data/raw/custom_*.json."""
    init_db()
    client = llm or LLMClient(get_settings())
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM custom_sources WHERE enabled=1 ORDER BY created_at ASC"
        ).fetchall()

    for row in rows:
        source_id = row["source_id"]
        try:
            payload = json.loads(row["rules_json"] or "{}")
        except json.JSONDecodeError as exc:
            _mark_source(source_id, status="error", error=f"bad rules: {exc}")
            results.append({"source_id": source_id, "ok": False, "error": str(exc)})
            continue

        if payload.get("engine") == "crawl_trafilatura" or payload.get("version") == 2:
            budget = LlmBudget()
            articles, stats = scrape_profile(payload, max_articles=40, llm=client, budget=budget)
            if not articles:
                _mark_source(source_id, status="error", error="статьи не извлеклись")
                results.append({"source_id": source_id, "ok": False, "error": "статьи не извлеклись", **stats})
                continue
            path = write_articles_raw(articles, RAW_DIR / source_id)
            _mark_source(source_id, status="ready", error=None)
            results.append(
                {
                    "source_id": source_id,
                    "ok": True,
                    "path": str(path),
                    "count": len(articles),
                    "links_found": stats.get("links_found"),
                    "engine": "crawl_trafilatura",
                }
            )
            continue

        try:
            rules = validate_rules_dict(payload)
        except Exception as exc:
            _mark_source(source_id, status="error", error=f"bad rules: {exc}")
            results.append({"source_id": source_id, "ok": False, "error": str(exc)})
            continue

        engine = run_rules_engine(rules, max_articles=60)
        if not engine.ok and client.enabled:
            try:
                fixed = repair_rules(rules, engine.error or "fail", client)
                engine2 = run_rules_engine(fixed, max_articles=60)
                if engine2.ok:
                    rules = fixed
                    engine = engine2
                    with connect() as conn:
                        conn.execute(
                            """
                            UPDATE custom_sources
                            SET rules_json=?, list_url=?, updated_at=?
                            WHERE source_id=?
                            """,
                            (
                                json.dumps(rules_to_dict(rules), ensure_ascii=False),
                                rules.list_url,
                                utc_now(),
                                source_id,
                            ),
                        )
            except Exception:
                pass

        if not engine.ok and firecrawl_enabled():
            with firecrawl_fallback():
                engine_fb = run_rules_engine(rules, max_articles=60)
            if engine_fb.ok:
                engine = engine_fb

        if not engine.ok:
            _mark_source(source_id, status="error", error=engine.error or "scrape failed")
            results.append(
                {
                    "source_id": source_id,
                    "ok": False,
                    "error": engine.error,
                    "links_found": engine.links_found,
                }
            )
            continue

        out_prefix = RAW_DIR / source_id
        path = write_articles_raw(engine.articles, out_prefix)
        _mark_source(source_id, status="ready", error=None)
        results.append(
            {
                "source_id": source_id,
                "ok": True,
                "path": str(path),
                "count": len(engine.articles),
                "links_found": engine.links_found,
            }
        )

    ok_n = sum(1 for r in results if r.get("ok"))
    return {"ok_sources": ok_n, "total": len(results), "results": results}


def _mark_source(source_id: str, *, status: str, error: str | None) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE custom_sources
            SET status=?, last_error=?, updated_at=?
            WHERE source_id=?
            """,
            (status, error, utc_now(), source_id),
        )


def parser_source_domains() -> set[str]:
    domains = {norm_host(d) for d in SAMPLE_DOMAINS}
    init_db()
    with connect() as conn:
        rows = conn.execute("SELECT domain, rules_json FROM custom_sources").fetchall()
    for row in rows:
        try:
            payload = json.loads(row["rules_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        if payload.get("engine") == "crawl_trafilatura" or payload.get("version") == 2:
            domains.add(norm_host(row["domain"]))
    return {d for d in domains if d}


def article_from_parser(source: str, link: str, domains: set[str] | None = None) -> bool:
    domains = domains or parser_source_domains()
    host = norm_host(source)
    if host in domains:
        return True
    blob = (link or "").lower()
    return any(d in blob for d in domains)


def _chunked(values: list[str], size: int = 400) -> list[list[str]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


def delete_articles_for_domains(
    domains: list[str] | tuple[str, ...] | set[str],
    *,
    remove_raw: bool = True,
) -> dict[str, int]:
    """Удаляет статьи (и связанные события) указанных доменов из БД и raw JSON."""
    wanted = {norm_host(d) for d in domains if norm_host(d)}
    init_db()
    article_ids: list[str] = []
    event_ids: list[str] = []
    source_ids: list[str] = []
    with connect() as conn:
        for row in conn.execute("SELECT article_id, source, link FROM articles").fetchall():
            if article_from_parser(row["source"] or "", row["link"] or "", wanted):
                article_ids.append(row["article_id"])
        for row in conn.execute("SELECT event_id, article_id, source, link FROM events").fetchall():
            if row["article_id"] in set(article_ids) or article_from_parser(row["source"] or "", row["link"] or "", wanted):
                event_ids.append(row["event_id"])
        for row in conn.execute("SELECT source_id, domain FROM custom_sources").fetchall():
            if norm_host(row["domain"]) in wanted:
                source_ids.append(row["source_id"])
        for chunk in _chunked(event_ids):
            marks = ",".join("?" * len(chunk))
            conn.execute(f"DELETE FROM cluster_members WHERE event_id IN ({marks})", chunk)
            conn.execute(f"DELETE FROM events WHERE event_id IN ({marks})", chunk)
        for chunk in _chunked(article_ids):
            marks = ",".join("?" * len(chunk))
            conn.execute(f"DELETE FROM articles WHERE article_id IN ({marks})", chunk)
    removed_raw = 0
    if remove_raw:
        for sid in source_ids:
            for suffix in (".json", ".csv"):
                path = RAW_DIR / f"{sid}{suffix}"
                if path.exists():
                    path.unlink()
                    removed_raw += 1
    return {
        "articles": len(article_ids),
        "events": len(event_ids),
        "raw_files": removed_raw,
        "sources": len(source_ids),
    }


def list_parser_articles(limit: int = 400) -> dict[str, Any]:
    domains = parser_source_domains()
    init_db()
    items: list[dict[str, Any]] = []
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT title, text, datatime, source, link, scraped_at
            FROM articles
            ORDER BY scraped_at DESC, datatime DESC
            """
        ).fetchall()
    for row in rows:
        if not article_from_parser(row["source"] or "", row["link"] or "", domains):
            continue
        text = row["text"] or ""
        items.append(
            {
                "title": row["title"],
                "datatime": row["datatime"] or "",
                "source": row["source"] or "",
                "link": row["link"],
                "preview": " ".join(text.split())[:420],
                "scraped_at": row["scraped_at"] or "",
            }
        )
        if len(items) >= limit:
            break
    counts = Counter(norm_host(i["source"]) or i["source"] for i in items)
    by_source = [{"source": name, "count": n} for name, n in counts.most_common()]
    return {
        "count": len(items),
        "domains": sorted(domains),
        "by_source": by_source,
        "items": items,
    }
