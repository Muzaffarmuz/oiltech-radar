"""Аудит кластеров через Lab LLM: нефтегаз → соответствие теме → перенос.

Работает по копии data/for_recluster (боевые файлы портала не трогает).

Шаги:
  taxonomy  — оставить/удалить кластер и подкластер
  fit       — документ про нефтегаз? лежит ли в своей теме?
  reassign  — чужие, но нефтегазовые документы перенести в живые темы
  all       — taxonomy → fit → reassign → итоговый jsonl

  # связь
  python scripts/audit_clusters_lab.py --ping

  # тест на срезе патентов
  python scripts/audit_clusters_lab.py --corpus patents --step taxonomy --limit 20 --workers 6
  python scripts/audit_clusters_lab.py --corpus patents --step fit --limit 40 --workers 8 --resume
  python scripts/audit_clusters_lab.py --corpus patents --step reassign --workers 8 --resume

  # полный прогон одного корпуса
  python scripts/audit_clusters_lab.py --corpus patents --step all --workers 8 --resume

Артефакты (в data/for_recluster/_audit/{corpus}/):
  taxonomy_decisions.jsonl
  fit_decisions.jsonl
  reassign_decisions.jsonl
  audited.jsonl
  report.json
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
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts._lab_credentials import lab_base_url, lab_api_key, lab_model, ensure_no_proxy
ensure_no_proxy()
BASE_URL = lab_base_url()
API_KEY = lab_api_key()
MODEL_NAME = lab_model("gpt-oss-120b")
TEXT_LIMIT = 1600


from gartner.config import Settings, ensure_dirs  # noqa: E402
from gartner.llm import LLMClient  # noqa: E402
from gartner.pipeline.cluster_audit import (  # noqa: E402
    FIT_MIN,
    apply_audit,
    as_bool,
    as_score,
    is_assigned,
    kept_theme_ids,
    load_descriptions,
    load_jsonl,
    needs_reassign,
    record_id,
    record_text,
    summarize,
    taxonomy_jobs,
    titles_from_jobs,
    write_jsonl,
)

CORPUS_ROOT = ROOT / "data" / "for_recluster"
AUDIT_ROOT = CORPUS_ROOT / "_audit"

CORPORA = {
    "patents": {
        "label": "патенты",
        "docs": CORPUS_ROOT / "science" / "patents" / "patents.jsonl",
        "report": CORPUS_ROOT / "science" / "patents" / "clusters_report.json",
        "id_field": "patent_id",
    },
    "science_news": {
        "label": "научные новости",
        "docs": CORPUS_ROOT / "science" / "news" / "articles.jsonl",
        "report": CORPUS_ROOT / "science" / "news" / "clusters_report.json",
        "id_field": "article_id",
    },
    "policy": {
        "label": "политика",
        "docs": CORPUS_ROOT / "policy" / "articles.jsonl",
        "report": CORPUS_ROOT / "policy" / "clusters_report.json",
        "id_field": "article_id",
    },
    "investments": {
        "label": "инвестиции",
        "docs": CORPUS_ROOT / "investments" / "articles.jsonl",
        "report": CORPUS_ROOT / "investments" / "clusters_report.json",
        "id_field": "article_id",
    },
}

TAXONOMY_PROMPT = """
Роль: ты строгий бинарный классификатор тем для ленты OilTech Radar
(нефтегаз и ТЭК). От твоего решения зависит, попадёт тема в радар или нет.

ПРАВИЛО ПО УМОЛЧАНИЮ: если связь с нефтегазом/ТЭК неочевидна — keep=false.
Оставляй тему только при явной или очевидной косвенной связи с отраслью.

KEEP = true, если тема про:
- разведку, добычу, бурение, освоение месторождений углеводородов;
- нефть, газ, СПГ, газовый конденсат, нефте- и газопереработку, НПЗ, нефтехимию;
- трубопроводы, транспортировку и хранение углеводородов;
- нефтесервис, оборудование и технологии для нефтегаза;
- рынок, цены, сделки, санкции, регулирование, налоги — если влияют на нефтегаз;
- энергопереход, декарбонизацию, CCS/H2 — в контуре нефтегаза/ТЭК;
- цифровизацию, ИИ, автоматизацию — если применяются в нефтегазе/ТЭК;
- кадры, образование, науку — если явно для нефтегазовой отрасли.

KEEP = false, если тема про:
- другие полезные ископаемые: уран, золото, серебро, медь, руды, выщелачивание и т.п.;
- общую геологию, горное дело, металлургию без углеводородов;
- уголь, электроэнергетику, ВИЭ — если нет прямой связи с нефтегазом
  (для OilTech Radar это соседние, но не целевые темы);
- быт, медицину, спорт, вуз/кафедру без связи с ТЭК;
- иную отрасль, если влияние на нефтегаз не указано явно.

Пограничные случаи:
- Нефть/газ упомянуты лишь как фон, а суть — другая отрасль → keep=false.
- Общая ESG/климатическая тема без привязки к нефтегазу → keep=false.
- Санкции/регулирование, где нефтегаз — один из секторов, но последствия
  для него описаны → keep=true.

Верни ТОЛЬКО валидный JSON, без markdown и комментариев:
{"keep": true|false, "reason": "короткая фраза на русском (до 12 слов)"}
"""

FIT_PROMPT = """
Роль: ты валидатор рубрикации OilTech Radar. Проверяешь, что документ
относится к нефтегазу/ТЭК и корректно лежит в указанной теме
(кластер + подкластер).

Шаг 1. oilgas — относится ли документ к нефтегазу/ТЭК
(напрямую или косвенно: рынок, регулирование, сделки, наука, кадры для отрасли).
- true: нефть, газ, СПГ, НПЗ, бурение, трубопроводы, нефтесервис, нефтехимия,
  энергопереход/цифровизация в контуре ТЭК.
- false: уран, золото, руды, металлургия, уголь/ВИЭ без связи с нефтегазом,
  быт, медицина, спорт, чужая отрасль.

Шаг 2. fits — соответствует ли документ заявленной теме.
Сравни смысл документа с названием и описанием кластера/подкластера.
- fits=true, если основная суть документа попадает в тему.
- fits=false, если тема пустая («без темы»), документ про другое,
  или совпадение только по отдельным словам.

Шаг 3. score ∈ [0, 1] — уверенность соответствия теме:
- 0.85–1.0 — точное попадание в подкластер;
- 0.60–0.84 — верный кластер, подкластер спорный;
- 0.30–0.59 — тематически рядом, но не в тему;
- 0.00–0.29 — не в тему.
Порог достаточного совпадения: score ≥ 0.6.
Если oilgas=false, то fits=false и score ≤ 0.2.

Верни ТОЛЬКО валидный JSON, без markdown и комментариев:
{"oilgas": true|false, "fits": true|false, "score": 0.0, "reason": "короткая фраза на русском (до 12 слов)"}
"""

REASSIGN_PROMPT = """
Роль: ты перераспределяешь документ по темам OilTech Radar.
Документ точно про нефтегаз/ТЭК, но лежит не в своей теме — подбери
наиболее подходящую живую тему.

Правила:
- cluster_id выбирай ТОЛЬКО из allowed_clusters, sub_cluster_id — ТОЛЬКО
  из allowed_subclusters выбранного кластера. Никаких id вне списков.
- Сначала определи кластер по основной теме документа, затем подкластер.
- Если подходящего подкластера нет или сомневаешься — sub_cluster_id="".
- Если ни один кластер не подходит уверенно (совпадение только по словам
  или тема документа размыта) — cluster_id="" и sub_cluster_id="".
- При равенстве вариантов предпочитай более общий/широкий кластер.
- Не придумывай новые темы и не выбирай «ближайшую из плохих».

Верни ТОЛЬКО валидный JSON, без markdown и комментариев:
{"cluster_id": "...", "sub_cluster_id": "", "reason": "короткая фраза на русском (до 12 слов)"}
"""


def make_client() -> LLMClient:
    return LLMClient(Settings(API_KEY=API_KEY, BASE_URL=BASE_URL, LLM_MODEL=MODEL_NAME))


def audit_dir(corpus: str) -> Path:
    return AUDIT_ROOT / corpus


def decisions_path(corpus: str, step: str) -> Path:
    return audit_dir(corpus) / f"{step}_decisions.jsonl"


def report_path(corpus: str) -> Path:
    return audit_dir(corpus) / "report.json"


def audited_path(corpus: str) -> Path:
    return audit_dir(corpus) / "audited.jsonl"


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
            key = str(row.get("id") or "")
            if key and row.get("method") == "llm":
                found[key] = row
    return found


def append_decision(path: Path, row: dict[str, Any], lock: threading.Lock) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def clear_decisions(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def run_pool(
    items: list[Any],
    workers: int,
    worker: Callable[[Any], dict[str, Any]],
    *,
    path: Path,
    label: str,
) -> dict[str, dict[str, Any]]:
    done = load_decisions(path)
    todo = [item for item in items if _item_key(item) not in done]
    print(f"[{label}] candidates={len(items)} done={len(done)} todo={len(todo)} workers={workers}", flush=True)
    if not todo:
        return done
    lock = threading.Lock()
    t0 = time.time()
    ok = err = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {pool.submit(worker, item): item for item in todo}
        for i, fut in enumerate(as_completed(futs), start=1):
            row = fut.result()
            append_decision(path, row, lock)
            if row.get("method") == "llm":
                done[str(row["id"])] = row
                ok += 1
            else:
                err += 1
            if i % 25 == 0 or i == len(futs):
                print(f"  [{label} {i}/{len(futs)}] ok={ok} err={err} {time.time()-t0:.0f}s", flush=True)
    return done


def _item_key(item: Any) -> str:
    if isinstance(item, dict) and "id" in item:
        return str(item["id"])
    if isinstance(item, dict):
        return record_id(item)
    return str(item)


def llm_taxonomy(client: LLMClient, job: dict[str, Any]) -> dict[str, Any]:
    base = {
        "id": job["id"],
        "kind": job["kind"],
        "title": job.get("title"),
        "parent_id": job.get("parent_id"),
        "parent_title": job.get("parent_title"),
        "member_count": job.get("member_count"),
    }
    try:
        raw = client.json_call(
            TAXONOMY_PROMPT,
            {
                "kind": job["kind"],
                "title": job.get("title"),
                "parent_title": job.get("parent_title"),
                "description": job.get("description") or "",
                "example_titles": job.get("titles") or [],
                "member_count": job.get("member_count"),
            },
            max_retries=2,
        )
        keep = as_bool(raw.get("keep"))
        return {
            **base,
            "keep": keep,
            "reason": str(raw.get("reason") or "").strip()[:240],
            "method": "llm",
        }
    except Exception as exc:
        # тему не выкидываем при сбое Lab — решим вручную / повторным --resume
        return {
            **base,
            "keep": True,
            "reason": f"llm_error_keep: {type(exc).__name__}: {exc}",
            "method": "llm_error_keep",
        }


def llm_fit(client: LLMClient, row: dict[str, Any]) -> dict[str, Any]:
    rid = record_id(row)
    cid = str(row.get("cluster_id") or "")
    sid = str(row.get("sub_cluster_id") or "")
    base = {
        "id": rid,
        "title": row.get("title"),
        "cluster_id": cid,
        "sub_cluster_id": sid,
    }
    try:
        raw = client.json_call(
            FIT_PROMPT,
            {
                "title": row.get("title"),
                "text": record_text(row, TEXT_LIMIT),
                "cluster_title": row.get("cluster_title") or ("без темы" if not cid else cid),
                "sub_cluster_title": row.get("sub_cluster_title") or "",
                "source": row.get("source") or row.get("patentee") or row.get("applicant") or "",
            },
            max_retries=2,
        )
        oilgas = as_bool(raw.get("oilgas"))
        fits = as_bool(raw.get("fits")) if oilgas else False
        score = as_score(raw.get("score"))
        if not cid:
            fits = False
            score = min(score, 0.2)
        return {
            **base,
            "oilgas": oilgas,
            "fits": fits,
            "score": score,
            "reason": str(raw.get("reason") or "").strip()[:240],
            "method": "llm",
        }
    except Exception as exc:
        # при ошибке не выкидываем документ и не считаем его «своим»
        return {
            **base,
            "oilgas": True,
            "fits": False,
            "score": 0.0,
            "reason": f"llm_error: {type(exc).__name__}: {exc}",
            "method": "llm_error",
        }


def llm_reassign(
    client: LLMClient,
    row: dict[str, Any],
    *,
    clusters: list[dict[str, str]],
    subs_by_parent: dict[str, list[dict[str, str]]],
) -> dict[str, Any]:
    rid = record_id(row)
    base = {
        "id": rid,
        "title": row.get("title"),
        "from_cluster_id": row.get("cluster_id"),
        "from_sub_cluster_id": row.get("sub_cluster_id"),
    }
    try:
        raw = client.json_call(
            REASSIGN_PROMPT,
            {
                "title": row.get("title"),
                "text": record_text(row, TEXT_LIMIT),
                "current_cluster": row.get("cluster_title") or "",
                "current_subcluster": row.get("sub_cluster_title") or "",
                "allowed_clusters": clusters,
                "allowed_subclusters": [
                    {"cluster_id": cid, "subclusters": subs}
                    for cid, subs in subs_by_parent.items()
                ],
            },
            max_retries=2,
        )
        return {
            **base,
            "cluster_id": str(raw.get("cluster_id") or "").strip(),
            "sub_cluster_id": str(raw.get("sub_cluster_id") or "").strip(),
            "reason": str(raw.get("reason") or "").strip()[:240],
            "method": "llm",
        }
    except Exception as exc:
        return {
            **base,
            "cluster_id": "",
            "sub_cluster_id": "",
            "reason": f"llm_error: {type(exc).__name__}: {exc}",
            "method": "llm_error",
        }


def load_corpus_rows(corpus: str, limit: int = 0) -> list[dict[str, Any]]:
    meta = CORPORA[corpus]
    rows = load_jsonl(meta["docs"])
    if limit and limit > 0:
        rows = rows[: int(limit)]
    return rows


def step_taxonomy(corpus: str, args: argparse.Namespace, client: LLMClient) -> dict[str, Any]:
    rows = load_corpus_rows(corpus, limit=0)
    descriptions = load_descriptions(CORPORA[corpus]["report"])
    jobs = taxonomy_jobs(rows, descriptions)
    if args.limit and args.limit > 0:
        jobs = jobs[: int(args.limit)]
    path = decisions_path(corpus, "taxonomy")
    if not args.resume:
        clear_decisions(path)
    done = run_pool(
        jobs,
        int(args.workers),
        lambda job: llm_taxonomy(client, job),
        path=path,
        label=f"{corpus}/taxonomy",
    )
    kept_c, kept_s = kept_theme_ids(done)
    stats = {
        "step": "taxonomy",
        "jobs": len(jobs),
        "decided": len(done),
        "keep_clusters": len(kept_c),
        "drop_clusters": sum(
            1 for r in done.values() if r.get("kind") == "cluster" and r.get("keep") is not True
        ),
        "keep_subclusters": len(kept_s),
        "drop_subclusters": sum(
            1 for r in done.values() if r.get("kind") == "subcluster" and r.get("keep") is not True
        ),
    }
    return {"corpus": corpus, "path": str(path), "stats": stats}


def step_fit(corpus: str, args: argparse.Namespace, client: LLMClient) -> dict[str, Any]:
    rows = load_corpus_rows(corpus, limit=int(args.limit or 0))
    path = decisions_path(corpus, "fit")
    if not args.resume:
        clear_decisions(path)
    done = run_pool(
        rows,
        int(args.workers),
        lambda row: llm_fit(client, row),
        path=path,
        label=f"{corpus}/fit",
    )
    stats = {
        "step": "fit",
        "docs": len(rows),
        "decided": len(done),
        "oilgas": sum(1 for r in done.values() if r.get("oilgas") is True),
        "not_oilgas": sum(1 for r in done.values() if r.get("oilgas") is not True),
        "fits": sum(1 for r in done.values() if r.get("fits") is True or as_score(r.get("score")) >= FIT_MIN),
        "misfits": sum(
            1
            for r in done.values()
            if r.get("oilgas") is True
            and not (r.get("fits") is True or as_score(r.get("score")) >= FIT_MIN)
        ),
    }
    return {"corpus": corpus, "path": str(path), "stats": stats}


def step_reassign(corpus: str, args: argparse.Namespace, client: LLMClient) -> dict[str, Any]:
    rows = load_corpus_rows(corpus, limit=0)
    taxonomy = load_decisions(decisions_path(corpus, "taxonomy"))
    fits = load_decisions(decisions_path(corpus, "fit"))
    if not taxonomy:
        raise SystemExit(f"[{corpus}] нет taxonomy_decisions.jsonl — сначала --step taxonomy")
    if not fits:
        raise SystemExit(f"[{corpus}] нет fit_decisions.jsonl — сначала --step fit")

    kept_clusters, kept_subs = kept_theme_ids(taxonomy)
    jobs_meta = taxonomy_jobs(rows, load_descriptions(CORPORA[corpus]["report"]))
    titles = titles_from_jobs(jobs_meta)
    clusters = [
        {"id": cid, "title": titles.get(cid, cid)}
        for cid in sorted(kept_clusters, key=lambda x: titles.get(x, x))
    ]
    subs_by_parent: dict[str, list[dict[str, str]]] = {}
    for sid in kept_subs:
        parent = str((taxonomy.get(sid) or {}).get("parent_id") or "")
        if parent not in kept_clusters:
            continue
        subs_by_parent.setdefault(parent, []).append(
            {"id": sid, "title": titles.get(sid, sid)}
        )

    candidates = [
        row
        for row in rows
        if needs_reassign(
            row,
            fits.get(record_id(row)) or {},
            kept_clusters=kept_clusters,
            kept_subs=kept_subs,
        )
    ]
    if args.limit and args.limit > 0:
        candidates = candidates[: int(args.limit)]

    path = decisions_path(corpus, "reassign")
    if not args.resume:
        clear_decisions(path)

    def _work(row: dict[str, Any]) -> dict[str, Any]:
        return llm_reassign(
            client,
            row,
            clusters=clusters,
            subs_by_parent=subs_by_parent,
        )

    done = run_pool(
        candidates,
        int(args.workers),
        _work,
        path=path,
        label=f"{corpus}/reassign",
    )
    stats = {
        "step": "reassign",
        "candidates": len(candidates),
        "decided": len(done),
        "moved": sum(1 for r in done.values() if r.get("cluster_id")),
        "unassigned": sum(1 for r in done.values() if not r.get("cluster_id")),
        "live_clusters": len(kept_clusters),
        "live_subclusters": len(kept_subs),
    }
    return {"corpus": corpus, "path": str(path), "stats": stats}


def step_apply(corpus: str) -> dict[str, Any]:
    rows = load_corpus_rows(corpus, limit=0)
    taxonomy = load_decisions(decisions_path(corpus, "taxonomy"))
    fits = load_decisions(decisions_path(corpus, "fit"))
    moves = load_decisions(decisions_path(corpus, "reassign"))
    if not taxonomy or not fits:
        raise SystemExit(f"[{corpus}] для сборки нужны taxonomy и fit")
    kept_clusters, kept_subs = kept_theme_ids(taxonomy)
    titles = titles_from_jobs(taxonomy_jobs(rows, load_descriptions(CORPORA[corpus]["report"])))
    # подтянуть имена из taxonomy decisions тоже
    for key, row in taxonomy.items():
        if row.get("title"):
            titles[key] = str(row["title"])
    audited = apply_audit(
        rows,
        fits,
        moves,
        kept_clusters=kept_clusters,
        kept_subs=kept_subs,
        titles=titles,
    )
    out = audited_path(corpus)
    write_jsonl(out, audited)
    stats = summarize(rows, audited)
    stats["live_clusters"] = len(kept_clusters)
    stats["live_subclusters"] = len(kept_subs)
    rpath = report_path(corpus)
    rpath.write_text(
        json.dumps(
            {
                "corpus": corpus,
                "label": CORPORA[corpus]["label"],
                "model": MODEL_NAME,
                "fit_min": FIT_MIN,
                "stats": stats,
                "paths": {
                    "taxonomy": str(decisions_path(corpus, "taxonomy")),
                    "fit": str(decisions_path(corpus, "fit")),
                    "reassign": str(decisions_path(corpus, "reassign")),
                    "audited": str(out),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"corpus": corpus, "audited": str(out), "report": str(rpath), "stats": stats}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Lab LLM: аудит кластеров for_recluster")
    p.add_argument(
        "--corpus",
        choices=[*CORPORA.keys(), "all"],
        default="patents",
        help="Какой набор из data/for_recluster брать",
    )
    p.add_argument(
        "--step",
        choices=["taxonomy", "fit", "reassign", "apply", "all"],
        default="taxonomy",
        help="taxonomy|fit|reassign|apply|all",
    )
    p.add_argument("--limit", type=int, default=0, help="Срез задач/документов (0 = все)")
    p.add_argument("--workers", type=int, default=6, help="Параллельных запросов к Lab")
    p.add_argument("--resume", action="store_true", help="Продолжить с decisions.jsonl")
    p.add_argument("--ping", action="store_true")
    return p.parse_args()


def run_corpus(corpus: str, args: argparse.Namespace, client: LLMClient) -> list[dict[str, Any]]:
    audit_dir(corpus).mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    step = args.step
    if step in {"taxonomy", "all"}:
        results.append(step_taxonomy(corpus, args, client))
    if step in {"fit", "all"}:
        results.append(step_fit(corpus, args, client))
    if step in {"reassign", "all"}:
        results.append(step_reassign(corpus, args, client))
    if step in {"apply", "all"}:
        results.append(step_apply(corpus))
    return results


def main() -> int:
    args = parse_args()
    ensure_dirs()
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
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

    corpora = list(CORPORA) if args.corpus == "all" else [args.corpus]
    for corpus in corpora:
        if not CORPORA[corpus]["docs"].exists():
            print(f"нет файла корпуса: {CORPORA[corpus]['docs']}", file=sys.stderr)
            return 1
        print(f"\n=== {corpus} / {CORPORA[corpus]['label']} ===", flush=True)
        for result in run_corpus(corpus, args, client):
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
