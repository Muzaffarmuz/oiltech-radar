"""Переименование подкластеров policy/investments через Lab LLM.

Когда Lab не справилась с именем при кластеризации, подкластер получает
эвристическое имя из частых слов («России рублей году», «Произошло день
воскресенье»). Скрипт заново называет подкластеры: один запрос на родительскую
тему, все её подкластеры сразу — так имена не повторяют друг друга.

  # посмотреть, что предложит Lab, без записи
  python scripts/rename_flow_subclusters_lab.py --flow both --dry-run

  # применить
  python scripts/rename_flow_subclusters_lab.py --flow both --workers 6

Запускать ПОСЛЕ перекластеризации: она перезаписывает отчёт и имена.
Бэкап: data/runs/flow_tags/{flow}_clusters_report.pre_subrename.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
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


from gartner.config import Settings, ensure_dirs  # noqa: E402
from gartner.llm import LLMClient  # noqa: E402
from gartner.pipeline.flow_news_cluster import ALLOWED_FLOWS, report_path  # noqa: E402
from gartner.pipeline.subcluster import compress_label  # noqa: E402

FLOW_SCOPE = {
    "policy": "политика, рынок и регулирование, влияющие на нефтегаз",
    "investments": "инвестиции, сделки и стартапы в ТЭК",
}

PROMPT = """Ты строишь иерархическую таксономию тем ({scope}).
Дана родительская тема и несколько её подтем; у каждой подтемы — заголовки новостей.
Назови КАЖДУЮ подтему: 2–5 слов, на русском, как рубрику аналитического отчёта.

ПРАВИЛА:
- конкретный аспект родительской темы, а не её повтор;
- имена подтем внутри одной темы НЕ должны совпадать или быть синонимами;
- без дат, дней недели, названий СМИ, без обрывков вроде «России рублей году»;
- если подтема — ежедневные сводки новостей, назови её «Ежедневные сводки»;
- имена людей допустимы только если подтема целиком про их решения.

Верни ТОЛЬКО JSON: {{"names": {{"<id подтемы>": "имя", ...}}}}
"""


def make_client() -> LLMClient:
    return LLMClient(Settings(API_KEY=API_KEY, BASE_URL=BASE_URL, LLM_MODEL=MODEL_NAME))


def collect_jobs(report: dict[str, Any]) -> list[dict[str, Any]]:
    titles_by_sub: dict[str, list[str]] = {}
    for item in report.get("index") or []:
        sid = str(item.get("sub_cluster_id") or "")
        if sid:
            titles_by_sub.setdefault(sid, []).append(str(item.get("title") or "")[:180])
    jobs = []
    for cluster in report.get("clusters") or []:
        subs = list(cluster.get("subclusters") or [])
        if not subs:
            continue
        jobs.append(
            {
                "cluster_id": cluster.get("id"),
                "parent_title": cluster.get("title") or "",
                "subclusters": [
                    {
                        "id": s["id"],
                        "old": s.get("title") or "",
                        "titles": titles_by_sub.get(str(s["id"]), [])[:12],
                    }
                    for s in subs
                ],
            }
        )
    return jobs


def name_job(client: LLMClient, flow: str, job: dict[str, Any]) -> dict[str, str]:
    payload = {
        "parent_title": job["parent_title"],
        "subclusters": [{"id": s["id"], "titles": s["titles"]} for s in job["subclusters"]],
    }
    raw = client.json_call(PROMPT.format(scope=FLOW_SCOPE[flow]), payload, max_retries=2)
    names = raw.get("names") if isinstance(raw.get("names"), dict) else raw
    out: dict[str, str] = {}
    used: set[str] = set()
    for s in job["subclusters"]:
        name = compress_label(str((names or {}).get(s["id"]) or "").strip())
        if name and name.lower() not in used:
            out[s["id"]] = name
            used.add(name.lower())
    return out


def run_flow(flow: str, args: argparse.Namespace, client: LLMClient) -> dict[str, Any]:
    path = report_path(flow)
    if not path.exists():
        raise FileNotFoundError(f"нет отчёта: {path}")
    report = json.loads(path.read_text(encoding="utf-8"))
    jobs = collect_jobs(report)
    print(f"[{flow}] тем с подкластерами: {len(jobs)}", flush=True)

    renames: dict[str, str] = {}
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, int(args.workers))) as pool:
        futs = {pool.submit(name_job, client, flow, job): job for job in jobs}
        for fut in as_completed(futs):
            job = futs[fut]
            try:
                got = fut.result()
            except Exception as exc:
                failed.append(str(job["cluster_id"]))
                print(f"  [{flow}] {job['cluster_id']} ошибка Lab: {exc}", flush=True)
                continue
            for s in job["subclusters"]:
                new = got.get(s["id"])
                if new:
                    renames[s["id"]] = new
                    print(f"  {s['id']}: {s['old']!r} → {new!r}", flush=True)

    if args.dry_run or not renames:
        return {"flow": flow, "renamed": len(renames), "failed": failed, "applied": False}

    backup = path.with_name(f"{flow}_clusters_report.pre_subrename.json")
    if not backup.exists():
        shutil.copyfile(path, backup)
    for cluster in report.get("clusters") or []:
        for s in cluster.get("subclusters") or []:
            if s["id"] in renames:
                s["title"] = renames[s["id"]]
    for item in report.get("index") or []:
        sid = str(item.get("sub_cluster_id") or "")
        if sid in renames:
            item["sub_cluster_title"] = renames[sid]
    report["subclusters_renamed_lab"] = True
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"flow": flow, "renamed": len(renames), "failed": failed, "applied": True, "backup": str(backup)}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Lab LLM: имена подкластеров policy/investments")
    p.add_argument("--flow", choices=[*ALLOWED_FLOWS, "both"], default="both")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--dry-run", action="store_true", help="Только показать новые имена")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    ensure_dirs()
    client = make_client()
    if not client.enabled:
        print("LLM disabled", file=sys.stderr)
        return 2
    flows = list(ALLOWED_FLOWS) if args.flow == "both" else [args.flow]
    for flow in flows:
        print(json.dumps(run_flow(flow, args, client), ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
