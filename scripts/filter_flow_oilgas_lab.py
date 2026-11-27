"""Нефтегазовая стрижка потоков policy/investments через Lab LLM.

Берёт уже ужатый keyword-фильтром clusters_report и спрашивает Lab:
оставить ли новость (прямо про нефтегаз ИЛИ косвенно влияет на отрасль).

  # связь
  python scripts/filter_flow_oilgas_lab.py --ping

  # policy (основной кейс: ~2.2k статей после keyword-стрижки)
  python scripts/filter_flow_oilgas_lab.py --flow policy --resume --apply-report

  # тест на срезе
  python scripts/filter_flow_oilgas_lab.py --flow policy --limit 40 --resume --apply-report

  # investments
  python scripts/filter_flow_oilgas_lab.py --flow investments --resume --apply-report

  # оба
  python scripts/filter_flow_oilgas_lab.py --flow both --resume --apply-report

Артефакты:
  data/runs/flow_tags/{flow}_oilgas_lab_decisions.jsonl
  data/runs/flow_tags/{flow}_oilgas_lab_keep.json
  data/runs/flow_tags/{flow}_oilgas_lab_report.json
  + обновлённый {flow}_clusters_report.json при --apply-report
  + бэкап {flow}_clusters_report.pre_oilgas_lab.json

После стрижки лучше перекластеризовать:
  python scripts/cluster_flow_news_lab.py --flow policy --relevant-only --interfax-per-day 2 --use-oilgas-lab-keep
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts._lab_credentials import lab_base_url, lab_api_key, lab_model, ensure_no_proxy
ensure_no_proxy()
BASE_URL = lab_base_url()
API_KEY = lab_api_key()
MODEL_NAME = "qwen3-32b"
TEXT_LIMIT = 3500


from gartner.config import FLOW_TAGS_DIR, Settings, ensure_dirs  # noqa: E402
from gartner.db import connect, init_db  # noqa: E402
from gartner.llm import LLMClient  # noqa: E402
from gartner.pipeline.flow_news_cluster import (  # noqa: E402
    ALLOWED_FLOWS,
    oilgas_lab_keep_path,
    report_path,
    slim_report_keep_ids,
)

PROMPT = """
Ты фильтруешь новости для OilTech Radar (нефтегаз / ТЭК).

ОСТАВЬ новость (keep=true), если она:
1) напрямую о нефтегазе / нефти / газе / СПГ / НПЗ / трубопроводах / нефтегазовых компаниях
   и проектах; ИЛИ
2) косвенно может повлиять на индустрию нефтегаза через рынок, законы, регулирование,
   санкции, сделки, налоги, тарифы, ставку ЦБ, валюту, экспорт/импорт, цены, спрос,
   объёмы добычи/переработки, логистику, инфраструктуру, риски, аварии, квоты, пошлины.

ОТБРОСЬ (keep=false), если тема в целом не влияет на нефтегаз даже косвенно
(спорт, культура, бытовая политика без экономического эффекта, общие новости без
связи с энергией/рынком/регулятором ТЭК, чисто военные сводки без энергетического
контекста и т.п.).

Верни ТОЛЬКО JSON:
{"keep": true, "reason": "короткая фраза на русском"}
"""


def make_client() -> LLMClient:
    return LLMClient(Settings(API_KEY=API_KEY, BASE_URL=BASE_URL, LLM_MODEL=MODEL_NAME))


def decisions_path(flow: str) -> Path:
    return FLOW_TAGS_DIR / f"{flow}_oilgas_lab_decisions.jsonl"


def summary_path(flow: str) -> Path:
    return FLOW_TAGS_DIR / f"{flow}_oilgas_lab_report.json"


def load_decisions(path: Path) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return found
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            aid = str(row.get("article_id") or "")
            if aid:
                found[aid] = row
    return found


def append_decision(path: Path, row: dict[str, Any], lock: threading.Lock) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def texts_from_db(links: list[str]) -> dict[str, str]:
    """link → полный text из SQLite (если есть)."""
    if not links:
        return {}
    init_db()
    out: dict[str, str] = {}
    chunk = 400
    with connect() as conn:
        for i in range(0, len(links), chunk):
            part = links[i : i + chunk]
            placeholders = ",".join("?" for _ in part)
            rows = conn.execute(
                f"SELECT link, text FROM articles WHERE link IN ({placeholders})",
                part,
            ).fetchall()
            for row in rows:
                out[str(row["link"])] = str(row["text"] or "")
    return out


def load_candidates(flow: str, *, limit: int = 0) -> list[dict[str, Any]]:
    path = report_path(flow)
    if not path.exists():
        raise FileNotFoundError(f"нет отчёта: {path}")
    report = json.loads(path.read_text(encoding="utf-8"))
    index = list(report.get("index") or [])
    rows: list[dict[str, Any]] = []
    for item in index:
        aid = str(item.get("article_id") or item.get("patent_id") or "")
        link = str(item.get("link") or "")
        if not aid or not link:
            continue
        rows.append(
            {
                "article_id": aid,
                "title": str(item.get("title") or ""),
                "abstract": str(item.get("abstract") or ""),
                "datatime": str(item.get("datatime") or item.get("date_norm") or item.get("date") or "")[:10],
                "source": str(item.get("source") or ""),
                "link": link,
            }
        )
    if limit and limit > 0:
        rows = rows[: int(limit)]
    db_texts = texts_from_db([r["link"] for r in rows])
    for row in rows:
        full = (db_texts.get(row["link"]) or "").strip()
        blob = full or row["abstract"]
        if len(blob) > TEXT_LIMIT:
            blob = blob[:TEXT_LIMIT]
        row["text"] = blob
    return rows


def parse_keep(raw: dict[str, Any]) -> tuple[bool, str]:
    keep_raw = raw.get("keep")
    if isinstance(keep_raw, bool):
        keep = keep_raw
    elif isinstance(keep_raw, (int, float)):
        keep = bool(keep_raw)
    elif isinstance(keep_raw, str):
        keep = keep_raw.strip().lower() in {"1", "true", "yes", "y", "да", "keep"}
    else:
        raise ValueError("keep missing")
    reason = str(raw.get("reason") or "").strip()[:240]
    return keep, reason


def llm_decide(client: LLMClient, article: dict[str, Any]) -> dict[str, Any]:
    base = {
        "article_id": article["article_id"],
        "link": article["link"],
        "title": article["title"],
        "source": article.get("source"),
        "datatime": article.get("datatime"),
    }
    try:
        raw = client.json_call(
            PROMPT,
            {
                "title": article.get("title"),
                "source": article.get("source"),
                "datatime": article.get("datatime"),
                "text": article.get("text") or "",
            },
            max_retries=2,
        )
        keep, reason = parse_keep(raw)
        return {**base, "keep": keep, "reason": reason, "method": "llm"}
    except Exception as exc:
        # уже прошли keyword-фильтр — при сбое Lab не выкидываем
        return {
            **base,
            "keep": True,
            "reason": f"llm_error_keep: {type(exc).__name__}: {exc}",
            "method": "llm_error_keep",
        }


def write_keep_file(flow: str, decisions: dict[str, dict[str, Any]], candidates: list[dict[str, Any]]) -> Path:
    keep_ids = [
        str(a["article_id"])
        for a in candidates
        if decisions.get(a["article_id"], {}).get("keep") is True
    ]
    path = oilgas_lab_keep_path(flow)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "flow": flow,
                "source": "filter_flow_oilgas_lab",
                "n_candidates": len(candidates),
                "n_keep": len(keep_ids),
                "keep_ids": keep_ids,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def summarize(decisions: dict[str, dict[str, Any]], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    keep = drop = err = 0
    by_source_keep: dict[str, int] = {}
    by_source_drop: dict[str, int] = {}
    for a in candidates:
        row = decisions.get(a["article_id"]) or {}
        src = str(a.get("source") or "?")
        if row.get("method") == "llm_error_keep":
            err += 1
        if row.get("keep") is True:
            keep += 1
            by_source_keep[src] = by_source_keep.get(src, 0) + 1
        else:
            drop += 1
            by_source_drop[src] = by_source_drop.get(src, 0) + 1
    return {
        "candidates": len(candidates),
        "keep": keep,
        "drop": drop,
        "llm_error_keep": err,
        "by_source_keep": dict(sorted(by_source_keep.items(), key=lambda p: (-p[1], p[0]))),
        "by_source_drop": dict(sorted(by_source_drop.items(), key=lambda p: (-p[1], p[0]))),
    }


def run_flow(flow: str, args: argparse.Namespace, client: LLMClient) -> dict[str, Any]:
    candidates = load_candidates(flow, limit=int(args.limit or 0))
    dpath = decisions_path(flow)
    done = load_decisions(dpath) if args.resume else {}
    if not args.resume and dpath.exists():
        # без --resume начинаем чистый лог
        dpath.write_text("", encoding="utf-8")
        done = {}
    todo = [a for a in candidates if a["article_id"] not in done]
    print(
        f"[{flow}] candidates={len(candidates)} done={len(done)} todo={len(todo)} "
        f"workers={args.workers}",
        flush=True,
    )

    lock = threading.Lock()
    t0 = time.time()
    ok = err = 0
    if todo:
        with ThreadPoolExecutor(max_workers=max(1, int(args.workers))) as pool:
            futs = {pool.submit(llm_decide, client, a): a for a in todo}
            for i, fut in enumerate(as_completed(futs), start=1):
                row = fut.result()
                append_decision(dpath, row, lock)
                done[row["article_id"]] = row
                if row.get("method") == "llm":
                    ok += 1
                else:
                    err += 1
                if i % 25 == 0 or i == len(futs):
                    print(
                        f"  [{flow} {i}/{len(futs)}] ok={ok} err={err} {time.time()-t0:.0f}s",
                        flush=True,
                    )

    # если resume и в decisions есть лишние id — для keep берём только candidates
    keep_path = write_keep_file(flow, done, candidates)
    stats = summarize(done, candidates)
    spath = summary_path(flow)
    spath.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    applied = None
    if args.apply_report:
        keep_ids = set(json.loads(keep_path.read_text(encoding="utf-8"))["keep_ids"])
        applied = slim_report_keep_ids(
            flow,
            keep_ids,
            filter_meta={
                "oilgas_lab": True,
                "input": stats["candidates"],
                "keep": stats["keep"],
                "drop": stats["drop"],
                "llm_error_keep": stats["llm_error_keep"],
            },
            note=(
                f"Поток «{flow}»: Lab oilgas-стрижка {stats['candidates']}→{stats['keep']} "
                f"(отброшено {stats['drop']}). Имена кластеров сохранены; "
                f"перекластеризуйте: cluster_flow_news_lab.py --use-oilgas-lab-keep"
            ),
        )

    return {
        "flow": flow,
        "decisions": str(dpath),
        "keep": str(keep_path),
        "summary": str(spath),
        "stats": stats,
        "apply_report": applied,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Lab LLM: нефтегазовая стрижка policy/investments")
    p.add_argument("--flow", choices=[*ALLOWED_FLOWS, "both"], default="policy")
    p.add_argument("--limit", type=int, default=0, help="Срез статей из текущего отчёта (0=все)")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--resume", action="store_true", help="Продолжить с decisions.jsonl")
    p.add_argument(
        "--apply-report",
        action="store_true",
        help="Ужать {flow}_clusters_report.json до keep_ids",
    )
    p.add_argument("--ping", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    ensure_dirs()
    FLOW_TAGS_DIR.mkdir(parents=True, exist_ok=True)
    client = make_client()
    if not client.enabled:
        print("LLM disabled", file=sys.stderr)
        return 2
    if args.ping:
        try:
            print("Lab OK:", client.json_call('Верни {"ok": true}', {"x": 1}, max_retries=1))
            return 0
        except Exception as exc:
            print("Lab FAIL:", type(exc).__name__, exc, file=sys.stderr)
            return 1

    flows = list(ALLOWED_FLOWS) if args.flow == "both" else [args.flow]
    results = []
    for flow in flows:
        results.append(run_flow(flow, args, client))
        print(json.dumps(results[-1], ensure_ascii=False, indent=2), flush=True)

    print(
        "\nДальше (перекластеризация с учётом Lab-keep):\n"
        "  python scripts/cluster_flow_news_lab.py --flow policy "
        "--relevant-only --interfax-per-day 2 --use-oilgas-lab-keep\n",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
