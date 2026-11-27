"""Классификация научных предприятий из патентов через Lab LLM.

Текущий контур (эвристика):
  gartner/patent_orgs.py + scripts/extract_patent_orgs.py / rebuild_patent_orgs.py
  — словари алиасов + regex-маркеры (университет/НИИ/…) → org_type.

Этот скрипт:
  1) собирает уникальные строки правообладателей/заявителей из SQLite patents;
  2) спрашивает Lab LLM: university | nii | company | person | foreign | other
     + короткое каноническое имя;
  3) пишет список научных (university/nii) в data/exports/org_sites_prompt/.

Запуск (из корня репозитория):

  # проверка связи + dry-run на 20 именах
  python scripts/classify_science_orgs_lab.py --limit 20

  # полный прогон (можно прервать и продолжить)
  python scripts/classify_science_orgs_lab.py --workers 4
  python scripts/classify_science_orgs_lab.py --resume --workers 4

  # только неясные для эвристики (unknown/company без маркеров вуза)
  python scripts/classify_science_orgs_lab.py --uncertain-only --workers 4

  # после прогона: science_enterprises_lab.json (+ txt/tsv)
  # --apply дополнительно перезапишет science_enterprises.txt|.tsv
  #   (как у rebuild_patent_orgs.py), не трогая эвристический unique_orgs.json
  python scripts/classify_science_orgs_lab.py --resume --apply

Lab (как в filter_science_org_news_lab.py):
  http://d.dgx:54000/v1 · qwen3-32b · <LAB_API_KEY>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts._lab_credentials import lab_base_url, lab_api_key, lab_model, ensure_no_proxy
ensure_no_proxy()
# --- Lab LLM ---
BASE_URL = lab_base_url()
API_KEY = lab_api_key()
MODEL_NAME = "qwen3-32b"
# ---------------


from gartner.config import Settings  # noqa: E402
from gartner.db import connect, init_db  # noqa: E402
from gartner.llm import LLMClient  # noqa: E402
from gartner.patent_orgs import (  # noqa: E402
    classify_org,
    org_merge_key,
    split_assignees,
)

OUT_DIR = ROOT / "data" / "exports" / "org_sites_prompt"
DECISIONS_PATH = OUT_DIR / "science_orgs_lab_decisions.jsonl"
REPORT_PATH = OUT_DIR / "science_enterprises_lab.json"
TXT_PATH = OUT_DIR / "science_enterprises_lab.txt"
TSV_PATH = OUT_DIR / "science_enterprises_lab.tsv"
APPLY_TXT = OUT_DIR / "science_enterprises.txt"
APPLY_TSV = OUT_DIR / "science_enterprises.tsv"

CLASSIFY_PROMPT = """
Ты — эксперт по классификации организаций-правообладателей и заявителей
патентов РФ (Роспатент). Твоя задача: по названию организации определить,
относится ли она к НАУКЕ (вуз / НИИ / академический центр) или это
компания / физлицо / иностранное юрлицо / иное.

================================================================
ФОРМАТ ОТВЕТА
================================================================
Верни ТОЛЬКО валидный JSON (без markdown, без комментариев, без текста до/после):
{
  "org_type": "university" | "nii" | "company" | "person" | "foreign" | "other",
  "canonical_name": "<короткое узнаваемое имя по-русски, 2–8 слов>",
  "is_science": true | false,
  "confidence": "high" | "medium" | "low",
  "reason": "<до 120 символов, кратко: почему такой тип>"
}

Правила полей:
- is_science = true ТОЛЬКО для org_type = university или nii. Во всех
  остальных случаях — false.
- confidence: high — явный признак (ВО, НИИ, РАН, известный бренд);
  medium — косвенные признаки; low — догадка/неоднозначно.
- canonical_name: короткое узнаваемое имя, 2–8 слов.
  * Убирай юр.форму и хвосты: ООО, АО, ПАО, ФГБОУ ВО, ФГУП, ФГБУН,
    «им. …», «(г. …)», кавычки.
  * Сохраняй узнаваемый бренд и аббревиатуру, если она общеупотребима
    (МФТИ, КубГТУ, ВНИИнефть, ИПНГ РАН).
  * Город оставляй только если он часть узнаваемого имени
    («Санкт-Петербургский горный университет»).
  * Не выдумывай и не достраивай имя: если в строке только юр.форма
    или мусор — canonical_name = "" и org_type = "other".

================================================================
org_type — определения и приоритет
================================================================
university — вуз / образовательная организация: университет, академия,
  политех, высшая школа, институт как вуз (РГУ нефти и газа,
  Горный университет, МФТИ, КубГТУ).
nii — научно-исследовательская организация: НИИ, НТЦ, НИЦ, РАН / СО РАН /
  отраслевые НИИ и проектные институты (ВНИИнефть, ВНИИГАЗ, ИПНГ РАН,
  ТатНИПИнефть). Сюда же — исследовательские центры госкорпораций,
  если это именно НИИ/НТЦ, а не добывающая «дочка».
company — коммерческая организация без статуса вуза/НИИ: ООО/АО/ПАО/НПП/
  НПО, нефтегазовые операторы и сервис (Татнефть, Роснефть,
  Шлюмберже, Halliburton).
person — физлицо (ФИО).
foreign — иностранная организация (не РФ): компания, университет, институт.
  Российские вузы/НИИ — НЕ foreign, даже с иностранным названием бренда.
other — невозможно определить: мусор, заглушка, «не указано»,
  только юр.форма без имени.

Пограничные случаи:
- «НПП / НПО / научно-производственное предприятие» → company, если нет
  явного статуса НИИ/института/РАН.
- Кафедра / факультет / лаборатория вуза → university (канон — вуз целиком,
  если угадывается; иначе other).
- Филиал / институт при вузе → university (канон — головной вуз, если ясно).
- Институт в составе РАН / СО РАН / РАО → nii.
- Иностранный университет → foreign (не university), is_science = false.
- Аббревиатура неоднозначна (например, «ИПИ») → confidence = low.

================================================================
ПРИМЕРЫ
================================================================
«ФГБОУ ВО "Санкт-Петербургский горный университет"»
→ university, «Санкт-Петербургский горный университет», true, high

«ООО "ВНИИнефть-сервис"»
→ company, «ВНИИнефть-сервис», false, medium

«ИПНГ РАН»
→ nii, «ИПНГ РАН», true, high

«ПАО "Татнефть" им. В.Д. Шашина»
→ company, «Татнефть», false, high

«Иванов Иван Иванович»
→ person, «Иванов Иван Иванович», false, high

«Schlumberger Technology B.V.»
→ foreign, «Schlumberger», false, high

«ООО»
→ other, "", false, high

================================================================
САМОПРОВЕРКА ПЕРЕД ОТВЕТОМ
================================================================
1. JSON валиден, без markdown.
2. is_science согласован с org_type.
3. canonical_name не содержит юр.формы и не выдуман.
4. Если данных мало — confidence = low или org_type = other.
"""


def make_lab_settings() -> Settings:
    return Settings(
        API_KEY=API_KEY,
        BASE_URL=BASE_URL,
        LLM_MODEL=MODEL_NAME,
    )


def load_patent_org_candidates(*, uncertain_only: bool) -> list[dict[str, Any]]:
    """Уникальные сырые имена из patentee/applicant + счётчики патентов."""
    init_db()
    raw_to_patents: dict[str, set[str]] = defaultdict(set)
    raw_examples: dict[str, str] = {}
    with connect() as conn:
        rows = conn.execute(
            "SELECT patent_id, applicant, patentee FROM patents"
        ).fetchall()
    for row in rows:
        pid = str(row["patent_id"])
        for field in ("patentee", "applicant"):
            for part in split_assignees(row[field]):
                key = part.strip()
                if len(key) < 3:
                    continue
                fold = org_merge_key(key) or key.lower()
                raw_to_patents[fold].add(pid)
                raw_examples.setdefault(fold, key)

    items: list[dict[str, Any]] = []
    for fold, patents in raw_to_patents.items():
        raw = raw_examples[fold]
        heur = classify_org(raw)
        # --uncertain-only: пропускаем уже уверенные эвристикой university/nii/person
        if uncertain_only and heur in ("university", "nii", "person", "redacted"):
            continue
        items.append(
            {
                "merge_key": fold,
                "raw_name": raw,
                "heuristic_type": heur,
                "patent_count": len(patents),
            }
        )
    items.sort(key=lambda x: (-x["patent_count"], x["raw_name"].lower()))
    return items


def load_decisions(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = str(row.get("merge_key") or "")
            if key:
                out[key] = row
    return out


def append_decision(path: Path, row: dict[str, Any], lock: threading.Lock) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)


def llm_classify(client: LLMClient, item: dict[str, Any]) -> dict[str, Any]:
    raw = item["raw_name"]
    try:
        named = client.json_call(
            CLASSIFY_PROMPT,
            {
                "raw_name": raw[:500],
                "heuristic_type": item.get("heuristic_type"),
                "patent_count": item.get("patent_count"),
            },
            max_retries=2,
        )
        org_type = str(named.get("org_type") or "other").strip().lower()
        if org_type not in {"university", "nii", "company", "person", "foreign", "other"}:
            org_type = "other"
        canonical = str(named.get("canonical_name") or "").strip() or raw
        canonical = re.sub(r"\s+", " ", canonical)
        is_science = org_type in ("university", "nii")
        if "is_science" in named:
            is_science = bool(named.get("is_science")) and org_type in ("university", "nii")
        return {
            "merge_key": item["merge_key"],
            "raw_name": raw,
            "heuristic_type": item.get("heuristic_type"),
            "patent_count": int(item.get("patent_count") or 0),
            "org_type": org_type,
            "canonical_name": canonical,
            "is_science": is_science,
            "confidence": str(named.get("confidence") or "medium"),
            "reason": str(named.get("reason") or "")[:200],
            "method": "llm",
        }
    except Exception as exc:
        # fallback: эвристика
        heur = str(item.get("heuristic_type") or classify_org(raw))
        return {
            "merge_key": item["merge_key"],
            "raw_name": raw,
            "heuristic_type": heur,
            "patent_count": int(item.get("patent_count") or 0),
            "org_type": heur if heur in {"university", "nii", "company", "person", "foreign"} else "other",
            "canonical_name": raw,
            "is_science": heur in ("university", "nii"),
            "confidence": "low",
            "reason": f"llm_error_fallback_heuristic: {type(exc).__name__}: {exc}",
            "method": "llm_error",
        }


def aggregate_science(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Склеить научные по canonical_name (casefold)."""
    buckets: dict[str, dict[str, Any]] = {}
    for row in decisions:
        if not row.get("is_science"):
            continue
        if row.get("org_type") not in ("university", "nii"):
            continue
        name = str(row.get("canonical_name") or "").strip()
        if not name:
            continue
        key = org_merge_key(name) or name.casefold()
        bucket = buckets.get(key)
        if not bucket:
            bucket = {
                "canonical_name": name,
                "org_type": row["org_type"],
                "patent_count": 0,
                "confidence": row.get("confidence"),
                "raw_examples": [],
                "reasons": [],
            }
            buckets[key] = bucket
        bucket["patent_count"] += int(row.get("patent_count") or 0)
        if row.get("org_type") == "university":
            bucket["org_type"] = "university"
        raw = str(row.get("raw_name") or "")
        if raw and raw not in bucket["raw_examples"] and len(bucket["raw_examples"]) < 5:
            bucket["raw_examples"].append(raw)
        reason = str(row.get("reason") or "")
        if reason and reason not in bucket["reasons"] and len(bucket["reasons"]) < 3:
            bucket["reasons"].append(reason)
        # предпочитаем более короткое «красивое» имя
        if len(name) < len(bucket["canonical_name"]) and not name.isupper():
            bucket["canonical_name"] = name
    items = sorted(buckets.values(), key=lambda x: (-x["patent_count"], x["canonical_name"].lower()))
    return items


def write_outputs(science: list[dict[str, Any]], decisions: list[dict[str, Any]], apply: bool) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    by_type = Counter(d.get("org_type") for d in decisions)
    report = {
        "source": "classify_science_orgs_lab.py",
        "lab": {"base_url": BASE_URL, "model": MODEL_NAME},
        "decisions_total": len(decisions),
        "science_total": len(science),
        "by_type": dict(by_type),
        "items": science,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"{row['canonical_name']} ({row['patent_count']}, {row['org_type']})" for row in science]
    TXT_PATH.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    tsv = ["canonical_name\torg_type\tpatent_count\tconfidence"]
    for row in science:
        tsv.append(
            f"{row['canonical_name']}\t{row['org_type']}\t{row['patent_count']}\t{row.get('confidence') or ''}"
        )
    TSV_PATH.write_text("\n".join(tsv) + "\n", encoding="utf-8")

    if apply:
        APPLY_TXT.write_text(TXT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        APPLY_TSV.write_text(TSV_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"apply -> {APPLY_TXT}")
        print(f"apply -> {APPLY_TSV}")

    print(f"report -> {REPORT_PATH}")
    print(f"txt    -> {TXT_PATH}")
    print(f"tsv    -> {TSV_PATH}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Lab LLM: научные предприятия из патентов")
    p.add_argument("--limit", type=int, default=0, help="Только первые N кандидатов (для теста)")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--resume", action="store_true", help="Не переспрашивать уже решённые merge_key")
    p.add_argument(
        "--uncertain-only",
        action="store_true",
        help="Пропустить эвристически явные university/nii/person/redacted",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Скопировать science_enterprises_lab.* → science_enterprises.txt|.tsv",
    )
    p.add_argument("--decisions", type=Path, default=DECISIONS_PATH)
    p.add_argument("--ping", action="store_true", help="Только проверить Lab и выйти")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    settings = make_lab_settings()
    client = LLMClient(settings)
    if not client.enabled:
        print("LLM disabled: проверьте API_KEY/BASE_URL", file=sys.stderr)
        return 2

    if args.ping:
        try:
            probe = client.json_call(
                'Верни JSON {"ok": true, "echo": "<слово>"}',
                {"word": "ping"},
                max_retries=1,
            )
            print("Lab OK:", probe)
            return 0
        except Exception as exc:
            print("Lab FAIL:", type(exc).__name__, exc, file=sys.stderr)
            return 1

    candidates = load_patent_org_candidates(uncertain_only=args.uncertain_only)
    if args.limit and args.limit > 0:
        candidates = candidates[: args.limit]
    print(f"кандидатов: {len(candidates)} (uncertain_only={args.uncertain_only})")

    done = load_decisions(args.decisions) if args.resume else {}
    if not args.resume and args.decisions.exists():
        # новый прогон без --resume: не затираем файл молча — пишем в тот же с append только для новых
        # если пользователь хочет с нуля: удалите decisions вручную
        print(f"внимание: {args.decisions} уже есть; для продолжения укажите --resume")
        print("          для полного пересчёта удалите файл decisions и запустите снова")

    todo = [c for c in candidates if c["merge_key"] not in done]
    print(f"уже решено: {len(done)} · к запросу: {len(todo)} · workers={args.workers}")

    lock = threading.Lock()
    ok = 0
    err = 0
    t0 = time.time()

    def work(item: dict[str, Any]) -> dict[str, Any]:
        return llm_classify(client, item)

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(work, item): item for item in todo}
        for i, fut in enumerate(as_completed(futures), start=1):
            row = fut.result()
            append_decision(args.decisions, row, lock)
            done[row["merge_key"]] = row
            if row.get("method") == "llm_error":
                err += 1
            else:
                ok += 1
            if i % 25 == 0 or i == len(futures):
                elapsed = time.time() - t0
                print(f"  [{i}/{len(futures)}] ok={ok} err={err} {elapsed:.0f}s")

    decisions = list(done.values())
    # если resume — подтянуть только ключи из текущего candidate set
    cand_keys = {c["merge_key"] for c in candidates}
    decisions = [d for d in decisions if d.get("merge_key") in cand_keys]
    science = aggregate_science(decisions)
    write_outputs(science, decisions, apply=args.apply)

    print(
        json.dumps(
            {
                "candidates": len(candidates),
                "decisions": len(decisions),
                "science": len(science),
                "by_type": dict(Counter(d.get("org_type") for d in decisions)),
                "top_science": [
                    {"name": s["canonical_name"], "n": s["patent_count"], "type": s["org_type"]}
                    for s in science[:12]
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
