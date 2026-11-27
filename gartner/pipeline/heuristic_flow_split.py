"""Эвристическая разметка articles → потоки investments / policy.

Оставшиеся концепт-потоки UI (science уже на патентах/новостях вузов).
Пять ручных источников: cbr, prav.tatarstan, rosenergo, interfax, neftegaz.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from gartner.db import connect, init_db, utc_now
from gartner.flow_tags import normalize_flow_tags

DEFAULT_SOURCES = (
    "cbr.ru",
    "prav.tatarstan.ru",
    "rosenergo.gov.ru",
    "interfax.ru",
    "neftegaz.ru",
)

# мягкий prior по источнику (добавка к счёту)
SOURCE_PRIOR: dict[str, dict[str, int]] = {
    "cbr.ru": {"policy": 2, "investments": 0},
    "prav.tatarstan.ru": {"policy": 2, "investments": 0},
    "rosenergo.gov.ru": {"policy": 2, "investments": 0},
    "interfax.ru": {"policy": 1, "investments": 0},
    "neftegaz.ru": {"policy": 0, "investments": 1},
}

POLICY_PATTERNS: tuple[str, ...] = (
    r"санкц",
    r"указ\b",
    r"закон\b",
    r"законопроект",
    r"постановлен",
    r"распоряжен",
    r"регулир",
    r"регулятор",
    r"лицензи",
    r"квот[аыуе]",
    r"пошлин",
    r"эмбарго",
    r"запрет",
    r"ограничен",
    r"ключевая ставка",
    r"ставк[аиуе].{0,12}цб",
    r"центральн\w* банк",
    r"\bцб\b",
    r"банк россии",
    r"инфляц",
    r"бюджет",
    r"госзакуп",
    r"минэнерго",
    r"росэнерго",
    r"правительств",
    r"президент",
    r"госдум",
    r"совет федерации",
    r"тариф",
    r"налог",
    r"акциз",
    r"валютн",
    r"курс рубл",
    r"экспорт",
    r"импорт",
    r"оп[еэ]к",
    r"urals",
    r"потолок цен",
    r"авария",
    r"разлив",
    r"\bчс\b",
    r"рынок нефти",
    r"рынок газа",
    r"ценов\w+ потол",
    r"внешнеполити",
    r"международн\w+ договор",
)

INVEST_PATTERNS: tuple[str, ...] = (
    r"инвестиц",
    r"инвестор",
    r"капвложен",
    r"капиталовложен",
    r"стартап",
    r"венчур",
    r"раунд\b",
    r"серия [a-cа-с]\b",
    r"сделк[аиуе]",
    r"m&a",
    r"поглощен",
    r"слияни",
    r"покупк\w+ дол",
    r"пакет акций",
    r"\bipo\b",
    r"размещени\w+ акций",
    r"грант",
    r"проектн\w+ финансир",
    r"привлек\w+.{0,20}средств",
    r"совместн\w+ предприяти",
    r"\bсп\b",
    r"строительств\w+ завода",
    r"ввод.{0,15}мощност",
    r"миллиард\w*.{0,30}инвест",
    r"млрд.{0,20}инвест",
    r"финансирован\w+ проект",
    r"фонд прям",
    r"private equity",
    r"акционерн\w+ соглашен",
)

_POLICY_RE = [re.compile(p, re.I) for p in POLICY_PATTERNS]
_INVEST_RE = [re.compile(p, re.I) for p in INVEST_PATTERNS]


def _norm_source(source: str) -> str:
    s = (source or "").strip().lower()
    if s.startswith("www."):
        s = s[4:]
    return s


def score_text(title: str, text: str) -> tuple[int, int, list[str], list[str]]:
    blob = f"{title or ''}\n{(text or '')[:4000]}".lower().replace("ё", "е")
    pol_hits: list[str] = []
    inv_hits: list[str] = []
    for rx in _POLICY_RE:
        if rx.search(blob):
            pol_hits.append(rx.pattern)
    for rx in _INVEST_RE:
        if rx.search(blob):
            inv_hits.append(rx.pattern)
    return len(pol_hits), len(inv_hits), pol_hits[:6], inv_hits[:6]


def classify_article(
    *,
    title: str,
    text: str,
    source: str,
) -> dict[str, Any]:
    """Вернуть flow_tags ∈ {investments, policy} (+ reasons). Всегда ≥1 метка."""
    src = _norm_source(source)
    pol, inv, pol_hits, inv_hits = score_text(title, text)
    prior = SOURCE_PRIOR.get(src, {"policy": 1, "investments": 0})
    pol_s = pol + int(prior.get("policy") or 0)
    inv_s = inv + int(prior.get("investments") or 0)

    tags: list[str] = []
    reasons: dict[str, str] = {}

    # сильные совпадения — можно обе метки
    if inv >= 2 and pol >= 2:
        tags = ["investments", "policy"]
    elif inv_s > pol_s and inv >= 1:
        tags = ["investments"]
        if pol >= 2:
            tags.append("policy")
    elif pol_s > inv_s and pol >= 1:
        tags = ["policy"]
        if inv >= 2:
            tags.append("investments")
    elif inv >= 1 and pol >= 1:
        # ничья по тексту — обе
        tags = ["investments", "policy"] if inv == pol else (
            ["investments"] if inv > pol else ["policy"]
        )
    elif inv >= 1:
        tags = ["investments"]
    elif pol >= 1:
        tags = ["policy"]
    else:
        # нет ключей — prior источника (чтобы сайт был виден в потоке)
        if inv_s >= pol_s and prior.get("investments"):
            tags = ["investments"]
        else:
            tags = ["policy"]

    tags = normalize_flow_tags(tags)
    if "policy" in tags:
        if pol_hits:
            reasons["policy"] = "эвристика: " + ", ".join(pol_hits[:3])
        else:
            reasons["policy"] = f"эвристика: prior источника {src or '(пусто)'}"
    if "investments" in tags:
        if inv_hits:
            reasons["investments"] = "эвристика: " + ", ".join(inv_hits[:3])
        else:
            reasons["investments"] = f"эвристика: prior источника {src or '(пусто)'}"

    return {
        "flow_tags": tags,
        "tag_reasons": reasons,
        "scores": {"policy": pol, "investments": inv, "policy_score": pol_s, "investments_score": inv_s},
        "method": "heuristic",
    }


def load_source_articles(
    sources: tuple[str, ...] | list[str] = DEFAULT_SOURCES,
    *,
    only_untagged: bool = False,
    limit: int = 0,
) -> list[dict[str, Any]]:
    init_db()
    wanted = {_norm_source(s) for s in sources}
    rows_out: list[dict[str, Any]] = []
    with connect() as conn:
        db_rows = conn.execute(
            """
            SELECT article_id, title, text, datatime, source, link, flow_tags_json, tag_reasons_json
            FROM articles
            WHERE link IS NOT NULL AND link != ''
            ORDER BY datatime DESC
            """
        ).fetchall()
    for row in db_rows:
        src = _norm_source(str(row["source"] or ""))
        if src not in wanted:
            continue
        try:
            existing = json.loads(row["flow_tags_json"] or "[]")
        except json.JSONDecodeError:
            existing = []
        if not isinstance(existing, list):
            existing = []
        if only_untagged and existing:
            continue
        rows_out.append(
            {
                "article_id": row["article_id"],
                "title": str(row["title"] or ""),
                "text": str(row["text"] or ""),
                "datatime": str(row["datatime"] or ""),
                "source": str(row["source"] or ""),
                "link": str(row["link"] or ""),
                "existing_tags": [str(t) for t in existing],
            }
        )
        if limit and len(rows_out) >= limit:
            break
    return rows_out


def merge_tags(existing: list[str], added: list[str]) -> list[str]:
    return normalize_flow_tags([*existing, *added])


def tag_articles(articles: list[dict[str, Any]], *, merge_existing: bool = True) -> list[dict[str, Any]]:
    tagged: list[dict[str, Any]] = []
    for art in articles:
        decision = classify_article(title=art["title"], text=art["text"], source=art["source"])
        existing = art.get("existing_tags") or []
        if merge_existing and existing:
            tags = merge_tags(list(existing), list(decision["flow_tags"]))
            reasons = dict(decision["tag_reasons"])
            # сохраняем только reasons для новых/целевых меток; старые не трогаем в sidecar
        else:
            tags = list(decision["flow_tags"])
            reasons = dict(decision["tag_reasons"])
        tagged.append(
            {
                "title": art["title"],
                "text": art["text"][:500],
                "datatime": art["datatime"],
                "source": art["source"],
                "link": art["link"],
                "article_id": art.get("article_id"),
                "flow_tags": tags,
                "tag_reasons": reasons,
                "heuristic_tags": decision["flow_tags"],
                "scores": decision["scores"],
                "method": "heuristic",
            }
        )
    return tagged


def apply_tags_to_db(
    tagged: list[dict[str, Any]],
    *,
    merge_existing: bool = True,
) -> dict[str, int]:
    """Записать flow_tags в articles (merge с уже стоящими метками)."""
    init_db()
    updated = 0
    missing = 0
    now = utc_now()
    with connect() as conn:
        for row in tagged:
            link = str(row.get("link") or "").strip()
            if not link:
                continue
            db = conn.execute(
                "SELECT article_id, flow_tags_json, tag_reasons_json FROM articles WHERE link=?",
                (link,),
            ).fetchone()
            if not db:
                missing += 1
                continue
            try:
                old_tags = json.loads(db["flow_tags_json"] or "[]")
            except json.JSONDecodeError:
                old_tags = []
            if not isinstance(old_tags, list):
                old_tags = []
            new_tags = [str(t) for t in (row.get("flow_tags") or [])]
            if merge_existing:
                final = merge_tags([str(t) for t in old_tags], new_tags)
            else:
                final = normalize_flow_tags(new_tags)
            try:
                old_reasons = json.loads(db["tag_reasons_json"] or "{}")
            except json.JSONDecodeError:
                old_reasons = {}
            if not isinstance(old_reasons, dict):
                old_reasons = {}
            reasons = {str(k): str(v) for k, v in (row.get("tag_reasons") or {}).items()}
            merged_reasons = {**{str(k): str(v) for k, v in old_reasons.items()}, **reasons}
            merged_reasons = {k: v for k, v in merged_reasons.items() if k in final}
            conn.execute(
                """
                UPDATE articles
                SET flow_tags_json=?, tag_reasons_json=?, flow_tagged_at=?
                WHERE article_id=?
                """,
                (
                    json.dumps(final, ensure_ascii=False),
                    json.dumps(merged_reasons, ensure_ascii=False),
                    now,
                    db["article_id"],
                ),
            )
            updated += 1
    return {"updated": updated, "missing_in_db": missing, "rows": len(tagged)}


def summarize(tagged: list[dict[str, Any]]) -> dict[str, Any]:
    by_tag: Counter[str] = Counter()
    by_source: dict[str, Counter[str]] = {}
    both = 0
    for row in tagged:
        tags = row.get("flow_tags") or []
        src = row.get("source") or "?"
        by_source.setdefault(src, Counter())
        if set(tags) >= {"investments", "policy"} or (
            "investments" in tags and "policy" in tags
        ):
            both += 1
        for t in tags:
            if t in ("investments", "policy"):
                by_tag[t] += 1
                by_source[src][t] += 1
    return {
        "articles": len(tagged),
        "by_tag": dict(by_tag),
        "both_streams": both,
        "by_source": {s: dict(c) for s, c in sorted(by_source.items())},
    }
