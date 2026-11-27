"""FastAPI: CIO-портал, audit, refresh, scheduler."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from gartner.config import PORTAL_DIR, ROOT, get_settings
from gartner.db import get_state, init_db
from gartner.pipeline.run import PipelineOptions, get_pipeline_status, run_pipeline

STATIC_DIR = ROOT / "portal" / "static"
scheduler = BackgroundScheduler()
app = FastAPI(title="OilTech Radar 4", version="4.0.0")

HTML_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _html_page(filename: str) -> FileResponse:
    """Serve application shells without browser caching during prototype work."""
    return FileResponse(STATIC_DIR / filename, headers=HTML_HEADERS)


class UpdateModeBody(BaseModel):
    mode: str  # weekly | daily | manual


class RefreshBody(BaseModel):
    full_recluster: bool = False
    scrape: bool = True
    include_seed: bool = False


class CustomSourceBody(BaseModel):
    url: str
    require_oilgas: bool = True


class CustomSourceEnabledBody(BaseModel):
    enabled: bool


def _cron_for_mode(mode: str) -> str:
    if mode == "daily":
        return "0 9 * * *"
    if mode == "weekly":
        return "0 9 * * 1"
    return ""


def _load_portal() -> dict[str, Any]:
    path = PORTAL_DIR / "portal_data.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Нет данных портала. Запустите пайплайн: python -m gartner.pipeline.run --seed-only")
    return json.loads(path.read_text(encoding="utf-8"))


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    settings = get_settings()
    mode = settings.update_mode
    if mode in {"weekly", "daily"}:
        cron = settings.update_cron if mode == "weekly" else _cron_for_mode("daily")
        # parse cron "m h dom mon dow"
        parts = cron.split()
        if len(parts) == 5:
            minute, hour, day, month, dow = parts
            scheduler.add_job(
                lambda: run_pipeline(PipelineOptions(scrape=True)),
                "cron",
                id="radar_update",
                replace_existing=True,
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=dow,
            )
            if not scheduler.running:
                scheduler.start()
        if settings.scheduler_run_on_start:
            run_pipeline(PipelineOptions(scrape=True))


@app.on_event("shutdown")
def on_shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


@app.get("/")
def index() -> FileResponse:
    return _html_page("index.html")


@app.get("/flows/news/digital")
def digital_news() -> FileResponse:
    """Existing, operational digital news stream inside the wider concept."""
    return _html_page("news-it.html")


@app.get("/flows/science")
@app.get("/flows/investments")
@app.get("/flows/policy")
def concept_flow() -> FileResponse:
    """Concept screens for the three future analytical streams."""
    return _html_page("future-flow.html")


@app.get("/flows/foreign-companies")
def foreign_companies_flow() -> FileResponse:
    """Иностранные нефтегазовые компании · ИТ/автоматизация (кластеры Lab)."""
    return _html_page("foreign-companies.html")


@app.get("/api/portal/foreign-it")
@app.get("/api/flows/foreign-companies")
def api_foreign_it_portal() -> JSONResponse:
    from gartner.pipeline.foreign_it_cluster import foreign_it_portal_payload

    return JSONResponse(foreign_it_portal_payload())


@app.get("/api/flows/foreign-companies/news/{article_id}")
def api_foreign_it_article(article_id: str) -> JSONResponse:
    from gartner.pipeline.foreign_it_cluster import foreign_it_article_detail

    payload = foreign_it_article_detail(article_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Статья не найдена")
    return JSONResponse(payload)


def _flow_tag_payload(tag: str) -> dict[str, Any]:
    """Сначала Lab-кластеры (KMeans+имена), иначе плоский список из БД/sidecar."""
    from gartner.pipeline.flow_news_cluster import flow_cluster_payload

    clustered = flow_cluster_payload(tag)
    if clustered and (clustered.get("clusters") or clustered.get("items") or clustered.get("index")):
        return clustered

    from gartner.pipeline.tag_flows import flow_payload_for_tag

    payload = flow_payload_for_tag(tag)
    if payload.get("articles"):
        return payload

    # Fallback: экспериментальные JSON, пока статьи ещё не в articles
    paths = [
        ROOT / "data" / "runs" / "flow_tags" / "tagged.json",
        ROOT / "data" / "runs" / "flow_tags" / "tagged_radar.json",
    ]
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        file_payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(file_payload, list):
            continue
        for row in file_payload:
            tags = [str(item) for item in (row.get("flow_tags") or [])]
            link = str(row.get("link") or "").strip()
            if tag not in tags or not link or link in seen:
                continue
            seen.add(link)
            reasons = row.get("tag_reasons") or {}
            items.append(
                {
                    "title": str(row.get("title") or ""),
                    "date": str(row.get("datatime") or ""),
                    "source": str(row.get("source") or ""),
                    "link": link,
                    "reason": str(reasons.get(tag) or ""),
                    "tags": [item for item in tags if item != tag],
                }
            )

    items.sort(key=lambda item: (1 if item["date"] else 0, item["date"]), reverse=True)
    dated = [item for item in items if item["date"]]
    by_source: dict[str, int] = {}
    by_month: dict[str, int] = {}
    for item in items:
        source = item["source"] or "(без источника)"
        by_source[source] = by_source.get(source, 0) + 1
        if len(item["date"]) >= 7:
            month = item["date"][:7]
            by_month[month] = by_month.get(month, 0) + 1
    return {
        "articles": len(items),
        "year_2026": sum(1 for item in dated if item["date"].startswith("2026")),
        "sources": len(by_source),
        "with_digital": sum(1 for item in items if "digital" in item["tags"]),
        "with_news": sum(1 for item in items if "news" in item["tags"]),
        "without_cbr": sum(1 for item in items if item["source"] != "cbr.ru"),
        "undated": len(items) - len(dated),
        "by_source": [
            {"source": source, "count": count}
            for source, count in sorted(by_source.items(), key=lambda pair: (-pair[1], pair[0]))
        ],
        "by_month": [{"month": month, "count": by_month[month]} for month in sorted(by_month)],
        "items": items,
        "source": "sidecar",
    }


@app.get("/api/flows/science")
def api_science_flow(mode: str = "patents") -> JSONResponse:
    """Наука: mode=patents (Роспатент) или mode=news (новости вузов/НИИ/компаний)."""
    kind = (mode or "patents").strip().lower()
    if kind in {"news", "articles", "org_news"}:
        from gartner.pipeline.science_news_cluster import science_news_flow_payload

        return JSONResponse(science_news_flow_payload())
    from gartner.pipeline.patent_cluster import science_flow_payload

    return JSONResponse(science_flow_payload())


@app.get("/api/flows/science/patent/{patent_id}")
def api_science_patent(patent_id: str) -> JSONResponse:
    from gartner.pipeline.patent_cluster import science_patent_detail

    payload = science_patent_detail(patent_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Патент не найден")
    return JSONResponse(payload)


@app.get("/api/flows/science/news/{article_id}")
def api_science_news_article(article_id: str) -> JSONResponse:
    from gartner.pipeline.science_news_cluster import science_news_detail

    payload = science_news_detail(article_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Новость не найдена")
    return JSONResponse(payload)


@app.get("/api/flows/policy")
def api_policy_flow() -> JSONResponse:
    return JSONResponse(_flow_tag_payload("policy"))


@app.get("/api/flows/investments")
def api_investments_flow() -> JSONResponse:
    return JSONResponse(_flow_tag_payload("investments"))


@app.get("/api/flows/policy/news/{article_id}")
def api_policy_news_article(article_id: str) -> JSONResponse:
    from gartner.pipeline.flow_news_cluster import flow_article_detail

    payload = flow_article_detail("policy", article_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Статья не найдена")
    return JSONResponse(payload)


@app.get("/api/flows/investments/news/{article_id}")
def api_investments_news_article(article_id: str) -> JSONResponse:
    from gartner.pipeline.flow_news_cluster import flow_article_detail

    payload = flow_article_detail("investments", article_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Статья не найдена")
    return JSONResponse(payload)


@app.get("/audit")
def audit_page() -> FileResponse:
    return _html_page("audit.html")


@app.get("/parser-articles")
def parser_articles_page() -> FileResponse:
    return _html_page("parser_articles.html")


@app.get("/api/portal")
def api_portal() -> JSONResponse:
    return JSONResponse(_load_portal())


@app.get("/api/parser-articles")
def api_parser_articles() -> JSONResponse:
    from gartner.custom_sources.service import list_parser_articles

    return JSONResponse(list_parser_articles())


@app.get("/api/status")
def api_status() -> JSONResponse:
    settings = get_settings()
    return JSONResponse(
        {
            "pipeline": get_pipeline_status(),
            "update_mode": settings.update_mode,
            "update_cron": settings.update_cron,
            "llm_enabled": settings.llm_enabled,
            "last_success_at": get_state("last_success_at"),
        }
    )


@app.post("/api/refresh")
def api_refresh(body: RefreshBody | None = None) -> JSONResponse:
    body = body or RefreshBody()
    status = get_pipeline_status()
    if status.get("state") == "running":
        raise HTTPException(status_code=409, detail="Пайплайн уже выполняется")
    # run in background thread via pipeline lock
    import threading

    result_box: dict[str, Any] = {}

    def _job() -> None:
        result_box["result"] = run_pipeline(
            PipelineOptions(
                scrape=body.scrape,
                include_seed=body.include_seed,
                full_recluster=body.full_recluster,
            )
        )

    thread = threading.Thread(target=_job, daemon=True)
    thread.start()
    return JSONResponse({"message": "Обновление запущено", "accepted": True})


@app.post("/api/refresh/sync")
def api_refresh_sync(body: RefreshBody | None = None) -> JSONResponse:
    """Синхронный refresh (для CLI/демо)."""
    body = body or RefreshBody()
    result = run_pipeline(
        PipelineOptions(
            scrape=body.scrape,
            include_seed=body.include_seed,
            full_recluster=body.full_recluster,
        )
    )
    return JSONResponse(result)


@app.post("/api/update-mode")
def api_update_mode(body: UpdateModeBody) -> JSONResponse:
    if body.mode not in {"weekly", "daily", "manual"}:
        raise HTTPException(status_code=400, detail="mode must be weekly|daily|manual")
    # обновляем .env на диске — простое решение для прототипа
    env_path = ROOT / ".env"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    mapping = {"UPDATE_MODE": body.mode}
    if body.mode == "daily":
        mapping["UPDATE_CRON"] = "0 9 * * *"
        mapping["SCRAPE_DAYS"] = "1"
    elif body.mode == "weekly":
        mapping["UPDATE_CRON"] = "0 9 * * 1"
        mapping["SCRAPE_DAYS"] = "7"
    # rewrite keys
    keys_done = set()
    new_lines = []
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in mapping:
                new_lines.append(f"{k}={mapping[k]}")
                keys_done.add(k)
                continue
        new_lines.append(line)
    for k, v in mapping.items():
        if k not in keys_done:
            new_lines.append(f"{k}={v}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    # reschedule
    if scheduler.get_job("radar_update"):
        scheduler.remove_job("radar_update")
    if body.mode in {"weekly", "daily"}:
        cron = mapping.get("UPDATE_CRON", "0 9 * * 1")
        parts = cron.split()
        if len(parts) == 5:
            minute, hour, day, month, dow = parts
            if not scheduler.running:
                scheduler.start()
            scheduler.add_job(
                lambda: run_pipeline(PipelineOptions(scrape=True)),
                "cron",
                id="radar_update",
                replace_existing=True,
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=dow,
            )
    return JSONResponse({"ok": True, "mode": body.mode, "cron": mapping.get("UPDATE_CRON", "")})


@app.get("/api/custom-sources")
def api_list_custom_sources() -> JSONResponse:
    from gartner.custom_sources.service import list_custom_sources

    return JSONResponse({"items": list_custom_sources()})


@app.post("/api/custom-sources")
def api_add_custom_source(body: CustomSourceBody) -> JSONResponse:
    from gartner.custom_sources.service import add_custom_source
    from gartner.llm import LLMClient

    try:
        item = add_custom_source(
            body.url,
            llm=LLMClient(get_settings()),
            require_oilgas=body.require_oilgas,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Не удалось добавить источник: {exc}") from exc
    return JSONResponse({"ok": True, "item": item})


@app.delete("/api/custom-sources/{source_id}")
def api_delete_custom_source(source_id: str) -> JSONResponse:
    from gartner.custom_sources.service import delete_custom_source

    if not delete_custom_source(source_id):
        raise HTTPException(status_code=404, detail="Источник не найден")
    return JSONResponse({"ok": True})


@app.post("/api/custom-sources/{source_id}/enabled")
def api_enable_custom_source(source_id: str, body: CustomSourceEnabledBody) -> JSONResponse:
    from gartner.custom_sources.service import set_custom_source_enabled

    if not set_custom_source_enabled(source_id, body.enabled):
        raise HTTPException(status_code=404, detail="Источник не найден")
    return JSONResponse({"ok": True, "enabled": body.enabled})


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run("portal.app:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
