"""LLM-извлечение технологических событий (инкремент + Midstream)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from gartner.company import normalize_company, normalize_text
from gartner.config import get_settings
from gartner.db import cache_get, cache_set, connect, init_db, utc_now
from gartner.llm import LLMClient

TASK_CONTEXT = """Общий контекст задачи:
эти данные будут далее кластеризоваться по тематикам, чтобы моделировать и прогнозировать намечающиеся тренды в российском нефтегазе в срезе конкретных IT-, AI- и цифровых технологий.
Конечный пользователь результатов — топ-менеджмент российской нефтегазовой компании.
Единица результата: одна строка = одна конкретная технология или один конкретный прикладной технологический контур.
Нас интересуют только технологии на стыке:
- ИИ, ML, LLM, компьютерного зрения, видеоаналитики;
- цифровых двойников, цифровых скважин, цифрового моделирования;
- роботизации, автономного управления, безлюдного производства;
- промышленного ПО, платформ данных, систем поддержки принятия решений;
- предиктивной аналитики, интеллектуального мониторинга, оптимизации и управления.
Не считаются целевыми: оборудование/кабели/датчики без «умного» слоя; поставки; общие лозунги «цифровизация/ИИ» без конкретики.
"""

FILTER_PROMPT = TASK_CONTEXT + """
Ты анализируешь русскоязычные новости нефтегаза.
1) Фильтрация: оставь текст только если он про российский нефтегаз И содержит конкретную целевую технологию.
2) Экстракция: одна item = одна технология. Верни ТОЛЬКО JSON:
{
  "is_relevant": true,
  "irrelevant_reason": "",
  "items": [
    {
      "topic_label": "конкретная технология + задача",
      "segment_text": "фрагмент только по этой технологии",
      "verbatim_excerpt": "5-8 слов дословно",
      "contains_multiple_news": false
    }
  ]
}
Ничего не придумывай.
"""

META_PROMPT = TASK_CONTEXT + """
Извлеки метаданные по одному технологическому событию. Верни ТОЛЬКО JSON:
{
  "category": "Upstream",
  "company": "",
  "ai_summary": "2-4 предложения"
}
Правила category: строго одно из Upstream | Midstream | Downstream.
- Upstream: разведка, геология, бурение, добыча, промысел.
- Midstream: трубопроводы, транспорт углеводородов, логистика сырья, НПС, резервуарные парки транспорта.
- Downstream: переработка, НПЗ, нефтехимия, сбыт, АЗС.
company: только российская нефтегазовая компания-заказчик/оператор. Не вендор, не вуз, не СМИ. Иначе "".
ai_summary: сначала технология и задача, затем контекст внедрения/упоминания.
Ничего не придумывай.
"""

CATEGORY_SET = {"Upstream", "Midstream", "Downstream"}


def _stable_hash(parts: list[str]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8", errors="ignore"))
        digest.update(b"\0")
    return digest.hexdigest()


def event_id_for(link: str, topic_label: str) -> str:
    return hashlib.sha1(f"{link}|{topic_label}".encode("utf-8", errors="ignore")).hexdigest()[:16]


def truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    split_at = max(cut.rfind("\n\n"), cut.rfind(". "))
    if split_at < max_chars * 0.6:
        split_at = max_chars
    return cut[:split_at].strip()


def heuristic_extract(title: str, text: str) -> dict[str, Any]:
    """Fallback без LLM: грубая эвристика для демо/офлайн."""
    blob = f"{title}\n{text}".lower()
    keywords = [
        ("цифров", "цифровой двойник"),
        ("llm", "LLM-ассистент"),
        ("машинн", "машинное обучение"),
        ("робот", "роботизация"),
        ("предиктив", "предиктивная аналитика"),
        ("видеоаналит", "видеоаналитика"),
        ("платформ", "платформа данных"),
        ("автоном", "автономное управление"),
        ("бурен", "автоматизация бурения"),
    ]
    hits = [label for key, label in keywords if key in blob]
    if not hits:
        return {"is_relevant": False, "irrelevant_reason": "no tech keywords", "items": []}
    category = "Upstream"
    if any(x in blob for x in ("трубопровод", "транспорт", "логист", "нпс")):
        category = "Midstream"
    elif any(x in blob for x in ("нпз", "перераб", "нефтехим", "азс")):
        category = "Downstream"
    items = []
    for label in hits[:3]:
        items.append(
            {
                "topic_label": label,
                "segment_text": text[:600],
                "verbatim_excerpt": title[:80],
                "contains_multiple_news": len(hits) > 1,
                "_category": category,
            }
        )
    return {"is_relevant": True, "irrelevant_reason": "", "items": items}


def heuristic_meta(topic_label: str, text: str, title: str) -> dict[str, Any]:
    blob = f"{title}\n{text}".lower()
    category = "Upstream"
    if any(x in blob for x in ("трубопровод", "транспорт", "логист")):
        category = "Midstream"
    elif any(x in blob for x in ("нпз", "перераб", "нефтехим")):
        category = "Downstream"
    company = ""
    for name in ("газпром нефть", "газпром", "татнефть", "роснефть", "лукойл", "сибур", "зарубежнефть", "новатэк"):
        if name in blob:
            company = name
            break
    return {
        "category": category,
        "company": company,
        "ai_summary": f"{topic_label}: по открытым источникам фиксируется упоминание технологии в контексте «{title[:120]}».",
    }


def _normalize_category(value: str) -> str:
    raw = normalize_text(value)
    lower = raw.lower()
    if "mid" in lower or "логист" in lower or "трубопров" in lower:
        return "Midstream"
    if "down" in lower or "перераб" in lower:
        return "Downstream"
    if "up" in lower or "бурен" in lower or "добыч" in lower:
        return "Upstream"
    return raw if raw in CATEGORY_SET else "Upstream"


def extract_new_articles(
    llm: LLMClient | None = None,
    limit: int | None = None,
    *,
    link_substrings: list[str] | None = None,
    allow_heuristic_fallback: bool = True,
    use_llm: bool = True,
) -> dict[str, int]:
    """Обрабатывает только articles.processed=0.

    link_substrings — если задан, берём статьи, у которых link содержит хотя бы одну подстроку
    (например домены новых источников).
    use_llm=False — только эвристика, без обращений к API.
    """
    init_db()
    settings = get_settings()
    client: LLMClient | None = (llm or LLMClient(settings)) if use_llm else None
    with connect() as conn:
        params: list[Any] = []
        query = "SELECT * FROM articles WHERE processed=0"
        if link_substrings:
            clauses = " OR ".join(["link LIKE ?" for _ in link_substrings])
            query += f" AND ({clauses})"
            params.extend(f"%{s}%" for s in link_substrings)
        query += " ORDER BY datatime DESC, scraped_at DESC"
        if limit:
            query += f" LIMIT {int(limit)}"
        articles = [dict(r) for r in conn.execute(query, params).fetchall()]

    kept = 0
    removed = 0
    errors = 0
    heuristic_used = 0

    for article in articles:
        try:
            cache_key = _stable_hash(
                [article["title"], article["text"], article["datatime"] or "", article["link"]]
            )
            cached = cache_get(cache_key)
            if cached is None:
                if client is not None and client.enabled:
                    try:
                        cached = client.json_call(
                            FILTER_PROMPT,
                            {
                                "title": article["title"],
                                "datatime": article["datatime"],
                                "source": article["source"],
                                "link": article["link"],
                                "text": truncate_text(article["text"], 18000),
                            },
                        )
                    except Exception:
                        if not allow_heuristic_fallback:
                            raise
                        cached = heuristic_extract(article["title"], article["text"])
                        heuristic_used += 1
                else:
                    cached = heuristic_extract(article["title"], article["text"])
                    heuristic_used += 1
                cache_set(cache_key, "filter", cached)

            if not cached.get("is_relevant") or not cached.get("items"):
                removed += 1
                with connect() as conn:
                    conn.execute("UPDATE articles SET processed=1 WHERE article_id=?", (article["article_id"],))
                continue

            for item in cached["items"]:
                topic = normalize_text(item.get("topic_label")) or "технология"
                segment = normalize_text(item.get("segment_text")) or article["text"][:800]
                meta_key = _stable_hash([article["title"], topic, segment[:500]])
                meta = cache_get(meta_key)
                if meta is None:
                    if client is not None and client.enabled:
                        try:
                            meta = client.json_call(
                                META_PROMPT,
                                {
                                    "title": article["title"],
                                    "topic_label": topic,
                                    "text": truncate_text(segment, 10000),
                                },
                            )
                        except Exception:
                            if not allow_heuristic_fallback:
                                raise
                            meta = heuristic_meta(topic, segment, article["title"])
                            heuristic_used += 1
                    else:
                        meta = heuristic_meta(topic, segment, article["title"])
                        heuristic_used += 1
                    if item.get("_category"):
                        meta["category"] = item["_category"]
                    cache_set(meta_key, "meta", meta)

                category = _normalize_category(str(meta.get("category", "Upstream")))
                company = normalize_text(meta.get("company"))
                company_norm = normalize_company(company)
                summary = normalize_text(meta.get("ai_summary"))
                eid = event_id_for(article["link"], topic)
                now = utc_now()
                with connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO events(
                            event_id, article_id, topic_label, ai_summary, company, company_normalized,
                            category, segment_text, datatime, source, link, created_at
                        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(event_id) DO UPDATE SET
                            ai_summary=excluded.ai_summary,
                            company=excluded.company,
                            company_normalized=excluded.company_normalized,
                            category=excluded.category
                        """,
                        (
                            eid,
                            article["article_id"],
                            topic,
                            summary,
                            company,
                            company_norm,
                            category,
                            segment,
                            article["datatime"],
                            article["source"],
                            article["link"],
                            now,
                        ),
                    )
                kept += 1

            with connect() as conn:
                conn.execute("UPDATE articles SET processed=1 WHERE article_id=?", (article["article_id"],))
        except Exception:  # noqa: BLE001
            errors += 1
            # карантин: не помечаем processed, чтобы повторить позже; но чтобы не зациклиться на демо —
            # помечаем и пишем в removed-лог
            with connect() as conn:
                conn.execute("UPDATE articles SET processed=1 WHERE article_id=?", (article["article_id"],))

    return {
        "articles": len(articles),
        "events_upserted": kept,
        "removed": removed,
        "errors": errors,
        "heuristic_used": heuristic_used,
    }
