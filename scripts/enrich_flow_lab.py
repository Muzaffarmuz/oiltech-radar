"""Lab-обогащение потоков policy / investments: структура поверх статей.

Policy:      тип события, тяжесть 1–3, направления (8 укрупнённых), «на что влияет»,
             компании, страны.
Investments: тип сделки, сумма + валюта (если названы), участники с ролями,
             направления, «на что влияет», стартап да/нет, страны.

Берёт статьи из текущего {flow}_clusters_report.json (уже после стрижек),
полный текст — из SQLite. Результат хранится отдельно по article_id и
не теряется при перекластеризации.

  # связь
  python scripts/enrich_flow_lab.py --ping

  # тест на срезе
  python scripts/enrich_flow_lab.py --flow policy --limit 30 --workers 8 --resume

  # полный прогон обоих потоков
  python scripts/enrich_flow_lab.py --flow both --workers 8 --resume

Артефакты:
  data/runs/flow_tags/{flow}_enrich_lab_decisions.jsonl   (лог, для --resume)
  data/runs/flow_tags/{flow}_enrich_lab.json              (article_id → поля)
  data/runs/flow_tags/{flow}_enrich_lab_report.json       (сводка)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from collections import Counter
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
from gartner.pipeline.flow_news_cluster import ALLOWED_FLOWS, report_path  # noqa: E402
from gartner.science_directions import COARSE_DIRECTIONS  # noqa: E402

POLICY_EVENT_TYPES: dict[str, str] = {
    "sanctions": "санкции, эмбарго, потолок цен, лицензии OFAC, вторичные санкции, санкционные списки",
    "regulation": "законы, постановления, запреты и квоты экспорта, пошлины, налоги, тарифы, "
    "техрегламенты, решения правительства / Минэнерго / ФАС / биржевые нормативы",
    "incident": "аварии, атаки на объекты, разливы, пожары, остановки НПЗ / терминалов / трубопроводов",
    "market": "цены на нефть, газ и топливо, спрос и предложение, ОПЕК+, объёмы добычи, "
    "экспорта и импорта, биржевая торговля топливом, дефицит",
    "macro": "ключевая ставка, инфляция, курс рубля, бюджет, денежно-кредитная политика, "
    "банковское и финансовое регулирование",
    "geopolitics": "международные переговоры, энергетическое сотрудничество, соглашения стран, "
    "конфликты и дипломатия без прямой санкции",
    "other": "ничего из перечисленного",
}

DEAL_TYPES: dict[str, str] = {
    "ma": "покупка / продажа доли или актива, слияние, поглощение, выход из актива",
    "round": "венчурный раунд, инвестиции в стартап, акселератор, венчурный фонд",
    "grant": "грант, субсидия, госпрограмма поддержки, льготный заём от государства",
    "agreement": "инвестиционное соглашение, СПИК, СЗПК, меморандум, соглашение о сотрудничестве с инвестициями",
    "ipo": "IPO, SPO, размещение акций или облигаций компанией",
    "capex": "капвложения, инвестпрограмма, строительство / модернизация объекта, проектное финансирование",
    "finance_market": "рынок капитала в целом: розничные инвесторы, ОФЗ, индекс, регулирование финрынка",
    "other": "ничего из перечисленного",
}

PARTICIPANT_ROLES = ("investor", "target", "partner", "state", "other")
CURRENCIES = ("RUB", "USD", "EUR", "CNY", "AED", "KZT", "other")
SCALE_TO_MLN = {"тыс": 0.001, "млн": 1.0, "млрд": 1000.0, "трлн": 1_000_000.0}

_DIRS_TEXT = "\n".join(f"- {d}" for d in COARSE_DIRECTIONS)


def _enum_text(mapping: dict[str, str]) -> str:
    return "\n".join(f"- {k}: {v}" for k, v in mapping.items())


POLICY_PROMPT = f"""
Ты аналитик OilTech Radar (нефтегаз / ТЭК). Разметь новость потока «Политика и рынок».
Опирайся только на текст. Не выдумывай факты, которых в тексте нет.

event_type — ровно один код:
{_enum_text(POLICY_EVENT_TYPES)}

severity — сила влияния на нефтегаз:
1 — фон, обсуждение, прогноз, мнение;
2 — конкретное решение или событие, влияющее на часть рынка или отдельные компании;
3 — крупное прямое изменение объёмов, цен или доступа (новый пакет санкций, запрет экспорта,
    остановка крупного НПЗ, решение ОПЕК+ по квотам).

directions — 0–3 направления из списка (точные строки), на которые влияет событие:
{_DIRS_TEXT}

impact — одна фраза до 20 слов: на что это влияет для нефтегазовой отрасли.
companies — до 5 названных в тексте компаний / организаций (как в тексте, без выдумок).
countries — до 3 стран, о которых новость (по-русски).

Верни ТОЛЬКО JSON:
{{"event_type":"regulation","severity":2,"directions":["Переработка и нефтехимия"],
"impact":"...","companies":["..."],"countries":["Россия"]}}
"""

INVEST_PROMPT = f"""
Ты аналитик OilTech Radar (нефтегаз / ТЭК). Разметь новость потока «Инвестиции и стартапы».
Опирайся только на текст. Не выдумывай суммы и участников.

deal_type — ровно один код:
{_enum_text(DEAL_TYPES)}

amount — сумма сделки / инвестиций, если она прямо названа в тексте, иначе null:
  value — число как в тексте (например 2.1), scale — одно из "тыс","млн","млрд","трлн",
  currency — одно из {", ".join(CURRENCIES)}, text — фрагмент текста с суммой.
participants — до 5 участников, названных в тексте: name и role
  (investor — кто вкладывает; target — куда / в кого; partner — сторона соглашения;
   state — государство / госорган / госфонд; other).
is_startup — true, если речь о стартапе / венчурной компании.
directions — 0–3 направления из списка (точные строки):
{_DIRS_TEXT}
impact — одна фраза до 20 слов: что это значит для нефтегазовой отрасли.
countries — до 3 стран (по-русски).

Верни ТОЛЬКО JSON:
{{"deal_type":"capex","amount":{{"value":2.1,"scale":"млрд","currency":"RUB","text":"2,1 млрд рублей"}},
"participants":[{{"name":"...","role":"investor"}}],"is_startup":false,
"directions":["Добыча и нефтесервис"],"impact":"...","countries":["Россия"]}}
"""


def make_client() -> LLMClient:
    return LLMClient(Settings(API_KEY=API_KEY, BASE_URL=BASE_URL, LLM_MODEL=MODEL_NAME))


def decisions_path(flow: str) -> Path:
    return FLOW_TAGS_DIR / f"{flow}_enrich_lab_decisions.jsonl"


def enrich_path(flow: str) -> Path:
    return FLOW_TAGS_DIR / f"{flow}_enrich_lab.json"


def summary_path(flow: str) -> Path:
    return FLOW_TAGS_DIR / f"{flow}_enrich_lab_report.json"


# ---------- нормализация ответа модели ----------


def _str_list(raw: Any, limit: int, max_len: int = 80) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for x in raw:
        s = re.sub(r"\s+", " ", str(x or "")).strip()[:max_len]
        key = s.lower()
        if s and key not in seen:
            seen.add(key)
            out.append(s)
        if len(out) >= limit:
            break
    return out


def _directions(raw: Any) -> list[str]:
    allowed = {d.lower(): d for d in COARSE_DIRECTIONS}
    out: list[str] = []
    for d in _str_list(raw, 6):
        hit = allowed.get(d.lower())
        if hit and hit not in out:
            out.append(hit)
    return out[:3]


def _enum(raw: Any, allowed: dict[str, str] | tuple[str, ...], default: str) -> str:
    val = str(raw or "").strip().lower()
    keys = allowed.keys() if isinstance(allowed, dict) else allowed
    lowered = {k.lower(): k for k in keys}
    return lowered.get(val, default)


def _impact(raw: Any) -> str:
    return re.sub(r"\s+", " ", str(raw or "")).strip()[:240]


def _to_float(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def normalize_policy(raw: dict[str, Any]) -> dict[str, Any]:
    sev_raw = raw.get("severity")
    try:
        sev = int(float(sev_raw))
    except (TypeError, ValueError):
        sev = 1
    return {
        "event_type": _enum(raw.get("event_type"), POLICY_EVENT_TYPES, "other"),
        "severity": min(3, max(1, sev)),
        "directions": _directions(raw.get("directions")),
        "impact": _impact(raw.get("impact")),
        "companies": _str_list(raw.get("companies"), 5),
        "countries": _str_list(raw.get("countries"), 3, 40),
    }


def _normalize_amount(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    value = _to_float(raw.get("value"))
    if value is None or value <= 0:
        return None
    scale = str(raw.get("scale") or "").strip().lower().rstrip(".")
    scale = next((k for k in SCALE_TO_MLN if scale.startswith(k)), "")
    currency = _enum(raw.get("currency"), CURRENCIES, "other")
    out: dict[str, Any] = {
        "value": value,
        "scale": scale or None,
        "currency": currency,
        "text": re.sub(r"\s+", " ", str(raw.get("text") or "")).strip()[:120],
    }
    out["amount_mln"] = round(value * SCALE_TO_MLN[scale], 3) if scale else None
    return out


def normalize_invest(raw: dict[str, Any]) -> dict[str, Any]:
    participants: list[dict[str, str]] = []
    for p in raw.get("participants") or []:
        if not isinstance(p, dict):
            continue
        name = re.sub(r"\s+", " ", str(p.get("name") or "")).strip()[:80]
        if not name or any(x["name"].lower() == name.lower() for x in participants):
            continue
        participants.append({"name": name, "role": _enum(p.get("role"), PARTICIPANT_ROLES, "other")})
        if len(participants) >= 5:
            break
    startup = raw.get("is_startup")
    return {
        "deal_type": _enum(raw.get("deal_type"), DEAL_TYPES, "other"),
        "amount": _normalize_amount(raw.get("amount")),
        "participants": participants,
        "is_startup": startup is True or str(startup).strip().lower() in {"true", "1", "да"},
        "directions": _directions(raw.get("directions")),
        "impact": _impact(raw.get("impact")),
        "countries": _str_list(raw.get("countries"), 3, 40),
    }


# ---------- загрузка ----------


def texts_from_db(links: list[str]) -> dict[str, str]:
    if not links:
        return {}
    init_db()
    out: dict[str, str] = {}
    with connect() as conn:
        for i in range(0, len(links), 400):
            part = links[i : i + 400]
            placeholders = ",".join("?" for _ in part)
            for row in conn.execute(
                f"SELECT link, text FROM articles WHERE link IN ({placeholders})", part
            ).fetchall():
                out[str(row["link"])] = str(row["text"] or "")
    return out


def load_candidates(flow: str, *, limit: int = 0) -> list[dict[str, Any]]:
    path = report_path(flow)
    if not path.exists():
        raise FileNotFoundError(f"нет отчёта: {path} — сначала cluster_flow_news_lab.py")
    report = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for item in report.get("index") or []:
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
                "cluster_title": str(item.get("cluster_title") or ""),
            }
        )
    if limit and limit > 0:
        rows = rows[: int(limit)]
    db_texts = texts_from_db([r["link"] for r in rows])
    for row in rows:
        blob = (db_texts.get(row["link"]) or "").strip() or row["abstract"]
        row["text"] = blob[:TEXT_LIMIT]
    return rows


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
            # ошибки не считаем готовыми — при --resume переспросим
            if aid and row.get("method") == "llm":
                found[aid] = row
    return found


def append_decision(path: Path, row: dict[str, Any], lock: threading.Lock) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------- LLM ----------


def llm_enrich(client: LLMClient, flow: str, article: dict[str, Any]) -> dict[str, Any]:
    base = {
        "article_id": article["article_id"],
        "link": article["link"],
        "title": article["title"],
        "source": article.get("source"),
        "datatime": article.get("datatime"),
    }
    prompt = POLICY_PROMPT if flow == "policy" else INVEST_PROMPT
    try:
        raw = client.json_call(
            prompt,
            {
                "title": article.get("title"),
                "source": article.get("source"),
                "datatime": article.get("datatime"),
                "text": article.get("text") or "",
            },
            max_retries=2,
        )
        fields = normalize_policy(raw) if flow == "policy" else normalize_invest(raw)
        return {**base, "enrich": fields, "method": "llm"}
    except Exception as exc:
        return {**base, "enrich": None, "method": "llm_error", "error": f"{type(exc).__name__}: {exc}"[:300]}


# ---------- сборка ----------


def write_enrich_file(flow: str, done: dict[str, dict[str, Any]], candidates: list[dict[str, Any]]) -> Path:
    items = {
        a["article_id"]: done[a["article_id"]]["enrich"]
        for a in candidates
        if a["article_id"] in done and done[a["article_id"]].get("enrich")
    }
    path = enrich_path(flow)
    path.write_text(
        json.dumps(
            {
                "flow": flow,
                "source": "enrich_flow_lab",
                "model": MODEL_NAME,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "n_candidates": len(candidates),
                "n_enriched": len(items),
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def summarize(flow: str, done: dict[str, dict[str, Any]], candidates: list[dict[str, Any]], errors: int) -> dict[str, Any]:
    enriched = [done[a["article_id"]]["enrich"] for a in candidates if done.get(a["article_id"], {}).get("enrich")]
    dirs = Counter(d for e in enriched for d in e.get("directions") or [])
    out: dict[str, Any] = {
        "flow": flow,
        "candidates": len(candidates),
        "enriched": len(enriched),
        "missing": len(candidates) - len(enriched),
        "errors_this_run": errors,
        "directions": dict(dirs.most_common()),
        "no_direction": sum(1 for e in enriched if not e.get("directions")),
        "countries": dict(Counter(c for e in enriched for c in e.get("countries") or []).most_common(15)),
    }
    if flow == "policy":
        out["event_type"] = dict(Counter(e["event_type"] for e in enriched).most_common())
        out["severity"] = dict(sorted(Counter(e["severity"] for e in enriched).items()))
        out["companies"] = dict(Counter(c for e in enriched for c in e.get("companies") or []).most_common(20))
    else:
        out["deal_type"] = dict(Counter(e["deal_type"] for e in enriched).most_common())
        amounts = [e["amount"] for e in enriched if e.get("amount")]
        out["with_amount"] = len(amounts)
        out["amount_by_currency_mln"] = {
            cur: round(sum(a["amount_mln"] for a in amounts if a["currency"] == cur and a.get("amount_mln")), 1)
            for cur in sorted({a["currency"] for a in amounts})
        }
        out["startups"] = sum(1 for e in enriched if e.get("is_startup"))
        out["participants"] = dict(
            Counter(p["name"] for e in enriched for p in e.get("participants") or []).most_common(20)
        )
    return out


def run_flow(flow: str, args: argparse.Namespace, client: LLMClient) -> dict[str, Any]:
    candidates = load_candidates(flow, limit=int(args.limit or 0))
    dpath = decisions_path(flow)
    if args.resume:
        done = load_decisions(dpath)
    else:
        dpath.parent.mkdir(parents=True, exist_ok=True)
        dpath.write_text("", encoding="utf-8")
        done = {}
    todo = [a for a in candidates if a["article_id"] not in done]
    print(
        f"[{flow}] candidates={len(candidates)} done={len(done)} todo={len(todo)} workers={args.workers}",
        flush=True,
    )

    lock = threading.Lock()
    t0 = time.time()
    ok = err = 0
    if todo:
        with ThreadPoolExecutor(max_workers=max(1, int(args.workers))) as pool:
            futs = [pool.submit(llm_enrich, client, flow, a) for a in todo]
            for i, fut in enumerate(as_completed(futs), start=1):
                row = fut.result()
                append_decision(dpath, row, lock)
                if row.get("method") == "llm":
                    done[row["article_id"]] = row
                    ok += 1
                else:
                    err += 1
                if i % 25 == 0 or i == len(futs):
                    print(f"  [{flow} {i}/{len(futs)}] ok={ok} err={err} {time.time()-t0:.0f}s", flush=True)

    epath = write_enrich_file(flow, done, candidates)
    stats = summarize(flow, done, candidates, err)
    spath = summary_path(flow)
    spath.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    if stats["missing"]:
        print(f"[{flow}] без обогащения: {stats['missing']} — перезапустите с --resume", flush=True)
    return {"flow": flow, "enrich": str(epath), "summary": str(spath), "stats": stats}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Lab LLM: обогащение policy / investments")
    p.add_argument("--flow", choices=[*ALLOWED_FLOWS, "both"], default="both")
    p.add_argument("--limit", type=int, default=0, help="Срез статей из текущего отчёта (0 = все)")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--resume", action="store_true", help="Продолжить с decisions.jsonl (ошибки переспрашиваются)")
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
    ok = True
    for flow in flows:
        result = run_flow(flow, args, client)
        ok = ok and result["stats"]["missing"] == 0
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
