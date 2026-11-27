"""Lab-обогащение потоков policy / investments для портала.

Источник — enrich_flow_lab.py: {flow}_enrich_lab.json (полный прогон) и/или
{flow}_enrich_lab_decisions.jsonl (частичный прогон). Здесь только чтение и
постобработка: синонимы компаний, дайджесты, макро без направлений.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from gartner.config import FLOW_TAGS_DIR

DIGEST_RE = re.compile(
    r"^(что произошло за день|главное за (день|неделю)|итоги (дня|недели)|дайджест)",
    re.IGNORECASE,
)

_LEGAL_RE = re.compile(r"^(?:пао|оао|зао|ао|ооо|нк|гк|ук|пао\s+нк|ао\s+нк)\s+", re.IGNORECASE)
_QUOTES_RE = re.compile(r"[«»\"“”„']")

# нормализованный ключ → каноническое имя
COMPANY_ALIASES: dict[str, str] = {
    "рэа минэнерго россии": "РЭА Минэнерго",
    "рэа минэнерго": "РЭА Минэнерго",
    "рэа": "РЭА Минэнерго",
    "российское энергетическое агентство минэнерго россии": "РЭА Минэнерго",
    "российское энергетическое агентство": "РЭА Минэнерго",
    "фгбу рэа минэнерго россии": "РЭА Минэнерго",
    "банк россии": "Банк России",
    "цб": "Банк России",
    "цб рф": "Банк России",
    "центробанк": "Банк России",
    "центральный банк россии": "Банк России",
    "центральный банк рф": "Банк России",
    "минэнерго": "Минэнерго России",
    "минэнерго россии": "Минэнерго России",
    "минэнерго рф": "Минэнерго России",
    "министерство энергетики россии": "Минэнерго России",
    "министерство энергетики рф": "Минэнерго России",
    "минфин": "Минфин России",
    "минфин россии": "Минфин России",
    "минфин рф": "Минфин России",
    "газпром": "Газпром",
    "газпром нефть": "Газпром нефть",
    "роснефть": "Роснефть",
    "лукойл": "ЛУКОЙЛ",
    "lukoil": "ЛУКОЙЛ",
    "новатэк": "НОВАТЭК",
    "novatek": "НОВАТЭК",
    "татнефть": "Татнефть",
    "сибур": "СИБУР",
    "транснефть": "Транснефть",
    "сургутнефтегаз": "Сургутнефтегаз",
    "saudi aramco": "Saudi Aramco",
    "aramco": "Saudi Aramco",
    "опек": "ОПЕК",
    "opec": "ОПЕК",
    "опек+": "ОПЕК+",
    "opec+": "ОПЕК+",
    "мосбиржа": "Мосбиржа",
    "московская биржа": "Мосбиржа",
    "спбиржа": "СПБ Биржа",
    "минфин сша": "Минфин США",
    "ofac": "OFAC",
    "евросоюз": "ЕС",
    "европейский союз": "ЕС",
    "еврокомиссия": "Еврокомиссия",
    "европейская комиссия": "Еврокомиссия",
    "nis": "NIS",
    "нис": "NIS",
}

DIRECTIONLESS_TYPES = frozenset({"macro"})


def _norm_key(name: str) -> str:
    s = _QUOTES_RE.sub("", str(name or "")).replace("ё", "е").replace("Ё", "Е")
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    prev = None
    while prev != s:
        prev = s
        s = _LEGAL_RE.sub("", s).strip()
    return s.lower()


def canonical_company(name: str) -> str:
    raw = re.sub(r"\s+", " ", _QUOTES_RE.sub("", str(name or ""))).strip()
    if not raw:
        return ""
    key = _norm_key(raw)
    if key in COMPANY_ALIASES:
        return COMPANY_ALIASES[key]
    stripped = raw
    prev = None
    while prev != stripped:
        prev = stripped
        stripped = _LEGAL_RE.sub("", stripped).strip()
    return stripped or raw


def _dedupe_names(names: list[str], limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for n in names:
        canon = canonical_company(n)
        key = canon.lower()
        if canon and key not in seen:
            seen.add(key)
            out.append(canon)
        if len(out) >= limit:
            break
    return out


def is_digest(title: str) -> bool:
    return bool(DIGEST_RE.search(str(title or "").strip()))


def postprocess(flow: str, enrich: dict[str, Any], *, title: str = "") -> dict[str, Any]:
    """Компактная и нормализованная запись для портала."""
    out: dict[str, Any] = {
        "directions": [str(d) for d in (enrich.get("directions") or []) if str(d).strip()][:3],
        "impact": str(enrich.get("impact") or "").strip()[:240],
        "countries": [str(c) for c in (enrich.get("countries") or []) if str(c).strip()][:3],
        "is_digest": is_digest(title),
    }
    if flow == "policy":
        etype = str(enrich.get("event_type") or "other")
        try:
            sev = int(enrich.get("severity") or 1)
        except (TypeError, ValueError):
            sev = 1
        out["event_type"] = etype
        out["severity"] = min(3, max(1, sev))
        out["companies"] = _dedupe_names(list(enrich.get("companies") or []), 5)
        if etype in DIRECTIONLESS_TYPES:
            out["directions"] = []
    else:
        out["deal_type"] = str(enrich.get("deal_type") or "other")
        out["is_startup"] = bool(enrich.get("is_startup"))
        participants: list[dict[str, str]] = []
        seen: set[str] = set()
        for p in enrich.get("participants") or []:
            if not isinstance(p, dict):
                continue
            canon = canonical_company(str(p.get("name") or ""))
            if not canon or canon.lower() in seen:
                continue
            seen.add(canon.lower())
            participants.append({"name": canon, "role": str(p.get("role") or "other")})
        out["participants"] = participants[:5]
        amount = enrich.get("amount")
        if isinstance(amount, dict) and amount.get("value"):
            out["amount"] = {
                "amount_mln": amount.get("amount_mln"),
                "currency": str(amount.get("currency") or "other"),
                "text": str(amount.get("text") or "")[:120],
            }
        else:
            out["amount"] = None
        if out["deal_type"] == "finance_market":
            out["directions"] = []
    return out


def _enrich_json_path(flow: str, base: Path) -> Path:
    return base / f"{flow}_enrich_lab.json"


def _enrich_log_path(flow: str, base: Path) -> Path:
    return base / f"{flow}_enrich_lab_decisions.jsonl"


def load_enrich_raw(flow: str, *, base: Path | None = None) -> dict[str, dict[str, Any]]:
    """article_id → сырые поля Lab. Лог (частичный прогон) дополняет/перекрывает json."""
    root = base or FLOW_TAGS_DIR
    found: dict[str, dict[str, Any]] = {}
    jpath = _enrich_json_path(flow, root)
    if jpath.exists():
        try:
            payload = json.loads(jpath.read_text(encoding="utf-8"))
            for aid, row in (payload.get("items") or {}).items():
                if isinstance(row, dict):
                    found[str(aid)] = row
        except (json.JSONDecodeError, OSError):
            pass
    lpath = _enrich_log_path(flow, root)
    if lpath.exists():
        try:
            with lpath.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if row.get("method") == "llm" and isinstance(row.get("enrich"), dict):
                        found[str(row.get("article_id") or "")] = row["enrich"]
        except OSError:
            pass
    found.pop("", None)
    return found


def load_enrich(flow: str, titles: dict[str, str] | None = None, *, base: Path | None = None) -> dict[str, dict[str, Any]]:
    titles = titles or {}
    return {
        aid: postprocess(flow, raw, title=titles.get(aid, ""))
        for aid, raw in load_enrich_raw(flow, base=base).items()
    }
