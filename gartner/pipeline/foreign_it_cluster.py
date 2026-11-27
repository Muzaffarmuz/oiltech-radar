"""Перевод + кластеризация иностранных ИТ/автоматизация-новостей нефтегазовых компаний.

Вход: foreign_it_news/out_trade/it_focus.json (+ опционально out_adapters).
Выход:
  data/runs/foreign_it/articles_translated.jsonl
  data/runs/foreign_it/clusters_report.json   — как science/flow отчёты
  data/runs/foreign_it/portal_data.json       — форма как у ИТ-потока (clusters[].events)

Не трогает radar.db и portal_data.json основного ИТ-потока.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from gartner.config import CACHE_DIR, ROOT, RUNS_DIR, Settings, ensure_dirs, get_settings
from gartner.llm import LLMClient
from gartner.pipeline.science_news_cluster import (
    _fallback_kmeans,
    _heuristic_name,
    _local_tfidf_embeddings,
    _normalize,
    _svd_xy,
    article_text,
)
from gartner.pipeline.subcluster import compress_label

DEFAULT_INPUTS = [
    # витрина с реальными телами (+ опционально adapters через --input)
    ROOT / "foreign_it_news" / "out_trade" / "it_focus.json",
    ROOT / "foreign_it_news" / "out_adapters" / "all_articles.json",
]

RUN_DIR = RUNS_DIR / "foreign_it"
TRANSLATED_JSONL = RUN_DIR / "articles_translated.jsonl"
TRANSLATE_CACHE = RUN_DIR / "translate_cache.json"
REPORT_PATH = RUN_DIR / "clusters_report.json"
PORTAL_PATH = RUN_DIR / "portal_data.json"
EMBED_PATH = CACHE_DIR / "foreign_it_embeddings.npz"
MANIFEST_PATH = CACHE_DIR / "foreign_it_embedding_manifest.json"

DEFAULT_N_CLUSTERS = 12
DEFAULT_MAX_SUBCLUSTERS = 4

TRANSLATE_PROMPT = """Ты — переводчик отраслевых новостей нефтегаза (ИТ и автоматизация).
Переведи заголовок и краткий текст с английского на русский.
Сохрани смысл и имена компаний/продуктов. Без воды и комментариев.
Верни ТОЛЬКО JSON:
{"title_ru":"...","text_ru":"..."}
"""

TRANSLATE_BATCH_PROMPT = """Ты — переводчик отраслевых новостей нефтегаза (ИТ и автоматизация).
Переведи каждую новость с английского на русский.
Сохрани смысл и имена компаний/продуктов. Без воды.
Верни ТОЛЬКО JSON:
{"items":[{"id":"...","title_ru":"...","text_ru":"..."}]}
id должен совпадать с входным.
"""

CLUSTER_PROMPT = """Ты — старший аналитик ИТ и автоматизации в нефтегазе (иностранные нефтегазовые компании).
Не используй англицизм majors — пиши «компании».
Сформулируй ОДНУ высокоуровневую тему (3–7 слов) НА РУССКОМ по группе близких новостей.
Без названий СМИ и дат. Фокус: ИИ, цифровые двойники, автоматизация, облако, кибербезопасность, роботы, SCADA, data.
Термин: всегда пиши «ИИ», не «искусственный интеллект» и не английское «AI».
Верни ТОЛЬКО JSON: {"name":"...","description":"1-2 предложения","confidence":0.0}
"""

SUB_PROMPT = """Ты строишь иерархическую таксономию тем «ИТ и автоматизация» нефтегаза (зарубежные компании).
Верни ТОЛЬКО JSON: {"cluster_name":"...","confidence":0.0}
ПРАВИЛА: 2–5 слов, НА РУССКОМ; всегда «ИИ» (не «искусственный интеллект», не «AI»);
без пустышек (цифровизация, инновации); конкретный аспект родительской темы.
"""

_CYR = re.compile(r"[А-Яа-яЁё]")


def article_id_from_link(link: str) -> str:
    return hashlib.sha1((link or "").encode("utf-8")).hexdigest()[:16]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cyr_ratio(text: str) -> float:
    if not text:
        return 0.0
    return len(_CYR.findall(text)) / max(len(text), 1)


def _looks_russian(title: str, text: str = "") -> bool:
    return _cyr_ratio(f"{title} {text[:200]}") >= 0.25


def _load_articles_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        items = raw.get("articles") or raw.get("items") or []
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    out: list[dict[str, Any]] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        link = str(row.get("link") or "").strip()
        title = str(row.get("title") or "").strip()
        if not link or not title:
            continue
        text = str(row.get("text") or "").strip()
        out.append(
            {
                "article_id": article_id_from_link(link),
                "title": title[:400],
                "text": text,
                "datatime": str(row.get("datatime") or "")[:10],
                "source": str(row.get("source") or row.get("feed_name") or ""),
                "link": link,
                "company": str(row.get("company") or "").strip(),
                "company_id": str(row.get("company_id") or "").strip(),
                "feed_id": str(row.get("feed_id") or ""),
                "pool": str(row.get("pool") or ""),
                "it_gate": str(row.get("it_gate") or ""),
            }
        )
    return out


def has_real_body(title: str, text: str) -> bool:
    """True, если text — не копия заголовка (мин. объём + не near-dup)."""
    from difflib import SequenceMatcher

    t, b = (title or "").strip(), (text or "").strip()
    if len(b) < 220:
        return False
    na, nb = _norm_for_dup(t), _norm_for_dup(b)
    if not na or not nb:
        return False
    if na == nb:
        return False
    if len(nb) <= len(na) + 50 and (na in nb or nb in na):
        return False
    if len(nb) < len(na) * 1.8 and (
        _token_jaccard(na, nb) >= 0.85 or _stem_jaccard(na, nb) >= 0.85
    ):
        return False
    if len(nb) < len(na) * 1.5 and SequenceMatcher(None, na, nb).ratio() >= 0.9:
        return False
    return True


def load_raw_articles(paths: list[Path] | None = None) -> list[dict[str, Any]]:
    paths = paths or [p for p in DEFAULT_INPUTS if p.exists()]
    by_id: dict[str, dict[str, Any]] = {}
    dropped_no_body = 0
    for path in paths:
        rows = _load_articles_file(path)
        print(f"[foreign-it] load {path}: {len(rows)}", flush=True)
        for row in rows:
            if is_junk_article(
                row.get("title") or "",
                row.get("text") or "",
                link=row.get("link") or "",
            ):
                dropped_no_body += 1
                continue
            if not has_real_body(row.get("title") or "", row.get("text") or ""):
                dropped_no_body += 1
                continue
            prev = by_id.get(row["article_id"])
            if prev is None:
                by_id[row["article_id"]] = row
                continue
            # предпочитаем более длинный текст
            if len(row.get("text") or "") > len(prev.get("text") or ""):
                by_id[row["article_id"]] = row
    rows = list(by_id.values())
    print(
        f"[foreign-it] unique articles={len(rows)} dropped_no_body={dropped_no_body}",
        flush=True,
    )
    return rows


def _load_translate_cache() -> dict[str, dict[str, str]]:
    if not TRANSLATE_CACHE.exists():
        return {}
    try:
        raw = json.loads(TRANSLATE_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(raw, dict) and isinstance(raw.get("items"), dict):
        return {str(k): v for k, v in raw["items"].items() if isinstance(v, dict)}
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items() if isinstance(v, dict) and "title_ru" in v}
    return {}


def _save_translate_cache(cache: dict[str, dict[str, str]]) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    TRANSLATE_CACHE.write_text(
        json.dumps(
            {"updated_at": _utc_now(), "n": len(cache), "items": cache},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _translate_one(client: LLMClient, row: dict[str, Any]) -> dict[str, str]:
    named = client.json_call(
        TRANSLATE_PROMPT,
        {
            "title": row.get("title") or "",
            "text": (row.get("text") or "")[:900],
            "company": row.get("company") or "",
        },
        max_retries=2,
    )
    title_ru = str(named.get("title_ru") or "").strip()
    text_ru = str(named.get("text_ru") or "").strip()
    if not title_ru:
        raise ValueError("empty title_ru")
    return {"title_ru": title_ru[:400], "text_ru": text_ru[:1200]}


def _translate_batch(
    client: LLMClient, batch: list[dict[str, Any]]
) -> dict[str, dict[str, str]]:
    payload = {
        "items": [
            {
                "id": r["article_id"],
                "title": r.get("title") or "",
                "text": (r.get("text") or "")[:700],
                "company": r.get("company") or "",
            }
            for r in batch
        ]
    }
    named = client.json_call(TRANSLATE_BATCH_PROMPT, payload, max_retries=2)
    items = named.get("items") or []
    out: dict[str, dict[str, str]] = {}
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        aid = str(item.get("id") or "").strip()
        title_ru = str(item.get("title_ru") or "").strip()
        text_ru = str(item.get("text_ru") or "").strip()
        if aid and title_ru:
            out[aid] = {"title_ru": title_ru[:400], "text_ru": text_ru[:1200]}
    return out


def translate_articles(
    rows: list[dict[str, Any]],
    llm: LLMClient,
    *,
    batch_size: int = 5,
    limit: int = 0,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Перевод Lab LLM с кэшем. Пишет articles_translated.jsonl."""
    ensure_dirs()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    cache = {} if force else _load_translate_cache()
    work = rows[:limit] if limit and limit > 0 else rows
    pending = [r for r in work if force or r["article_id"] not in cache]
    # уже по-русски — без Lab
    for r in list(pending):
        if _looks_russian(r.get("title") or "", r.get("text") or ""):
            cache[r["article_id"]] = {
                "title_ru": (r.get("title") or "")[:400],
                "text_ru": (r.get("text") or "")[:1200],
            }
            pending = [x for x in pending if x["article_id"] != r["article_id"]]

    print(
        f"[foreign-it] translate: total={len(work)} cached={len(work) - len(pending)} "
        f"pending={len(pending)} batch={batch_size}",
        flush=True,
    )
    if not llm.enabled and pending:
        raise RuntimeError("LLM disabled — нужен Lab для перевода")

    done = 0
    i = 0
    while i < len(pending):
        chunk = pending[i : i + max(1, batch_size)]
        i += len(chunk)
        try:
            if len(chunk) == 1:
                cache[chunk[0]["article_id"]] = _translate_one(llm, chunk[0])
                done += 1
            else:
                got = _translate_batch(llm, chunk)
                for r in chunk:
                    if r["article_id"] in got:
                        cache[r["article_id"]] = got[r["article_id"]]
                        done += 1
                    else:
                        # fallback по одной
                        try:
                            cache[r["article_id"]] = _translate_one(llm, r)
                            done += 1
                        except Exception as exc:
                            print(
                                f"[foreign-it] translate fail {r['article_id']}: {exc}",
                                flush=True,
                            )
                            cache[r["article_id"]] = {
                                "title_ru": (r.get("title") or "")[:400],
                                "text_ru": (r.get("text") or "")[:1200],
                            }
            if done % 10 == 0 or done == len(pending):
                _save_translate_cache(cache)
                print(f"[foreign-it] translate progress {done}/{len(pending)}", flush=True)
            time.sleep(0.15)
        except Exception as exc:
            print(f"[foreign-it] batch fail → one-by-one: {exc}", flush=True)
            for r in chunk:
                try:
                    cache[r["article_id"]] = _translate_one(llm, r)
                except Exception as exc2:
                    print(f"[foreign-it] translate fail {r['article_id']}: {exc2}", flush=True)
                    cache[r["article_id"]] = {
                        "title_ru": (r.get("title") or "")[:400],
                        "text_ru": (r.get("text") or "")[:1200],
                    }
                done += 1
            _save_translate_cache(cache)

    _save_translate_cache(cache)

    out: list[dict[str, Any]] = []
    for r in work:
        tr = cache.get(r["article_id"]) or {
            "title_ru": (r.get("title") or "")[:400],
            "text_ru": (r.get("text") or "")[:1200],
        }
        out.append(
            {
                **r,
                "title_en": r.get("title") or "",
                "text_en": r.get("text") or "",
                "title": tr.get("title_ru") or r.get("title") or "",
                "text": tr.get("text_ru") or r.get("text") or "",
                "title_ru": tr.get("title_ru") or "",
                "text_ru": tr.get("text_ru") or "",
            }
        )

    with TRANSLATED_JSONL.open("w", encoding="utf-8") as fh:
        for row in out:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[foreign-it] wrote {TRANSLATED_JSONL} n={len(out)}", flush=True)
    return out


def load_translated(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or TRANSLATED_JSONL
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("article_id") and row.get("title"):
                rows.append(row)
    return rows


def ensure_embeddings(
    rows: list[dict[str, Any]],
    *,
    force: bool = False,
    local: bool = True,
    llm: LLMClient | None = None,
) -> dict[str, Any]:
    ensure_dirs()
    if len(rows) < 3:
        return {"status": "skip", "reason": "not_enough_articles", "n": len(rows)}

    if EMBED_PATH.exists() and MANIFEST_PATH.exists() and not force:
        try:
            man = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            if int(man.get("n") or 0) == len(rows):
                return {"status": "cached", "n": len(rows), "model": man.get("model")}
        except Exception:
            pass

    client = llm or LLMClient()
    model = "tfidf-svd-256"
    if local or not client.enabled:
        emb, ids = _local_tfidf_embeddings(rows)
        model = f"tfidf-svd-{emb.shape[1]}"
    else:
        try:
            texts = [article_text(r.get("title") or "", r.get("text") or "") or " " for r in rows]
            ids = np.array([r["article_id"] for r in rows], dtype=str)
            vectors = np.asarray(client.embed(texts, batch_size=16), dtype="float32")
            emb = _normalize(vectors)
            model = get_settings().embedding_model
        except Exception as exc:
            print(f"[foreign-it] API embed fail → TF-IDF: {exc!r}", flush=True)
            emb, ids = _local_tfidf_embeddings(rows)
            model = f"tfidf-svd-{emb.shape[1]}"

    np.savez_compressed(EMBED_PATH, embeddings=emb, article_id=ids)
    MANIFEST_PATH.write_text(
        json.dumps(
            {"n": int(len(ids)), "dim": int(emb.shape[1]), "model": model},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"status": "ok", "n": int(len(ids)), "dim": int(emb.shape[1]), "model": model}


def load_embeddings() -> tuple[np.ndarray, np.ndarray]:
    if not EMBED_PATH.exists():
        return np.zeros((0, 64), dtype="float32"), np.array([], dtype=str)
    payload = np.load(EMBED_PATH, allow_pickle=True)
    return payload["embeddings"].astype("float32"), payload["article_id"].astype(str)


def _month_slope(months: list[str], counts: list[int]) -> float:
    if len(months) < 2:
        return 0.0
    xs = list(range(len(counts)))
    vals = [float(v) for v in counts]
    mx = sum(xs) / len(xs)
    my = sum(vals) / len(vals)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom <= 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, vals)) / denom


STAGE_LABELS = {
    "breakthrough": "Прорывные",
    "emerging": "Зарождающиеся",
    "mature": "Зрелые",
    "fading": "Угасающие",
}

# Портал foreign IT: не показываем события старше этой даты
PORTAL_MIN_DATE = "2025-01-01"

_BAD_SOURCE_HOST_RE = re.compile(
    r"^(?:\d{1,3}\.){3}\d{1,3}$|news\.google\.|consent\.google|googleapis|gstatic",
    re.IGNORECASE,
)

_AI_FULL_RE = re.compile(r"искусственн\w*\s+интеллект\w*", re.IGNORECASE)
_AI_EN_RE = re.compile(r"\bAIs?\b")


def normalize_ai_term(text: str) -> str:
    """Единый термин в названиях тем: всегда «ИИ»."""
    if not text:
        return text
    out = _AI_FULL_RE.sub("ИИ", text)
    out = _AI_EN_RE.sub("ИИ", out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    # «ИИ‑» / «ИИ-» уже ок; почистить «ИИ ИИ»
    out = re.sub(r"\bИИ\s+ИИ\b", "ИИ", out)
    return out


def _host_from_url(url: str) -> str:
    from urllib.parse import urlparse, unquote

    raw = (url or "").strip()
    if not raw.startswith("http"):
        return ""
    try:
        host = (urlparse(raw).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""
    host = unquote(host)
    if not host or _BAD_SOURCE_HOST_RE.search(host):
        return ""
    if "%" in host or " " in host:
        return ""
    return host


def normalize_source_label(source: str, link: str = "") -> str:
    """Читаемое имя источника: без %20, IP-мусора; иначе домен из link."""
    from urllib.parse import unquote

    raw = unquote(str(source or "")).replace("+", " ").strip()
    raw = re.sub(r"\s+", " ", raw)
    host = _host_from_url(link)

    # мусор вроде 0.0.0.10 / URL-encoded slug без смысла
    looks_ip = bool(re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", raw))
    looks_encoded_junk = ("%" in str(source or "")) and (" " not in raw or len(raw) < 4)
    if looks_ip or looks_encoded_junk or not raw:
        return host or raw

    # если source уже похож на домен — нормализуем
    if "." in raw and " " not in raw and len(raw) < 80:
        candidate = raw.lower().removeprefix("www.")
        if not _BAD_SOURCE_HOST_RE.search(candidate):
            return candidate

    # человекочитаемое имя (World Oil, Yahoo Finance…)
    if len(raw) >= 2 and not looks_ip:
        return raw
    return host or raw


_SOURCE_TAIL_RE = re.compile(
    r"[\s\u2010-\u2015\-–—|:]*\(?\s*"
    r"(?:rigzone|yahoo\s*finance|aerotime|world\s*oil|offshore\s*energy|"
    r"hart\s*energy|reuters|bloomberg|oilfield\s*technology|ships\s*monthly|"
    r"brazil\s*energy\s*insight|the\s*business\s*journals|abb|exxonmobil|"
    r"shell|bp|chevron|aramco|equinor|eni|petrobras|conocophillips|"
    r"totalenergies|adnoc|occidental|oxy)"
    r"\s*\)?\s*$",
    re.IGNORECASE,
)


def _norm_for_dup(text: str) -> str:
    """Нормализация для сравнения title≈summary (без хвостов СМИ/пунктуации)."""
    s = (text or "").casefold().replace("ё", "е")
    s = _SOURCE_TAIL_RE.sub("", s)
    # ещё один проход: « - Source» / « — Source» в конце
    s = re.sub(r"[\s\u2010-\u2015\-–—|:]+[a-z0-9 .%&]{2,40}$", "", s)
    s = re.sub(r"[^\wа-я]+", " ", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip()


def _token_jaccard(a: str, b: str) -> float:
    ta = {t for t in a.split() if len(t) > 1}
    tb = {t for t in b.split() if len(t) > 1}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _stem_jaccard(a: str, b: str) -> float:
    """Сравнение по основам слов (морфология: тестирования/тестировании)."""

    def stems(s: str) -> set[str]:
        out: set[str] = set()
        for t in s.split():
            if len(t) <= 1:
                continue
            out.add(t if len(t) <= 4 else t[:5])
        return out

    ta, tb = stems(a), stems(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def is_near_duplicate_text(a: str, b: str, *, threshold: float = 0.78) -> bool:
    from difflib import SequenceMatcher

    na, nb = _norm_for_dup(a), _norm_for_dup(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if na in nb or nb in na:
        return True
    if _token_jaccard(na, nb) >= threshold:
        return True
    if _stem_jaccard(na, nb) >= threshold:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= 0.88


# --- post-cluster cleanup (captcha/оффтоп/дубли тем) ---

_JUNK_TITLE_RE = re.compile(
    r"(?:"
    r"подтвердите[, ]*что вы человек|"
    r"просим прощения за прерывание|"
    r"извините за прерывание|"
    r"just a moment|attention required|enable javascript|"
    r"checking your browser|cf-browser|access denied|"
    r"^403\b|ошибка запрос не может|"
    r"^www\.[a-z0-9.-]+\.[a-z]{2,}/?$|"
    r"^[a-z0-9.-]+\.(?:com|net|org|ai|io)/?$"
    r")",
    re.IGNORECASE,
)

_SPORTS_OFFTOPIC_RE = re.compile(
    r"(?:\bcricket\b|крикет|\bipl\b|формул[еа][\s\u2010-\u2015\-–—‑]*1|formula[\s\u2010-\u2015\-–—‑]*1|"
    r"aston\s*martin\s*aramco|мотоцикл)",
    re.IGNORECASE,
)

_PHYSICAL_ATTACK_RE = re.compile(
    r"(?:атак[ауие].*(?:танкер|месторожд|нпз|завод)|"
    r"(?:tanker|refinery|field).*(?:attack|drone|strike)|"
    r"дрон(?:-|\s)?(?:атак|удар)|drone\s*(?:attack|strike)|"
    r"закрыть нефтеперерабатывающ)",
    re.IGNORECASE,
)

_IT_SIGNAL_RE = re.compile(
    r"(?:\bии\b|\bai\b|цифр|автоматиз|кибер|робот|облак|scada|data\s*center|"
    r"дата-?центр|software|платформ|цифров)",
    re.IGNORECASE,
)

# Перекрытие тем после KMeans: мелкие «синонимы» → в крупный кластер.
CLUSTER_MERGE_MAP: dict[str, str] = {
    "fi0": "fi2",
    "fi7": "fi2",
    "fi9": "fi1",
}

CLUSTER_TITLE_OVERRIDES: dict[str, str] = {
    "fi2": "ИИ и автоматизация у нефтегазовых компаний",
    "fi1": "ИИ в разведке и цифровой трансформации",
}


def is_junk_article(
    title: str,
    abstract: str = "",
    *,
    link: str = "",
) -> bool:
    """Captcha/403/домен-заголовок, спорт без ИТ, физ. атаки без цифрового контекста."""
    t = (title or "").strip()
    a = (abstract or "").strip()
    blob = f"{t}\n{a[:800]}"
    if not t:
        return True
    if _JUNK_TITLE_RE.search(t):
        return True
    # домен вместо заголовка
    if re.fullmatch(r"(?:https?://)?(?:www\.)?[a-z0-9.-]+\.[a-z]{2,}(?:/)?", t, re.I):
        return True
    if len(t) < 12 and "." in t and " " not in t:
        return True
    # сильный mojibake
    if t.count("�") >= 2 or "Ð" in t[:40] and "Ñ" in t[:80]:
        return True
    # спорт / F1 / кликбейт — по заголовку, даже если в тексте мелькнул «ИИ»
    if _SPORTS_OFFTOPIC_RE.search(t):
        return True
    if re.search(r"dark\s*mode\s*ads", blob, re.I):
        return True
    if _PHYSICAL_ATTACK_RE.search(blob) and not _IT_SIGNAL_RE.search(blob):
        return True
    # «проверка фактов» / картинка ИИ — не отраслевая автоматизация
    if re.search(r"проверк[аеи].*факт|изображение[, ]*созданн.*ии", blob, re.I):
        return True
    _ = link  # reserved for future host-based rules
    return False


def _article_keep_score(item: dict[str, Any]) -> tuple[int, str]:
    """Больше = лучше при дедупе: длиннее abstract, новее дата."""
    abs_len = len(str(item.get("abstract") or ""))
    date = str(item.get("date_norm") or item.get("date") or "")[:10]
    return (abs_len, date)


def _title_stems(title: str) -> set[str]:
    s = _norm_for_dup(title)
    out: set[str] = set()
    for t in s.split():
        if len(t) <= 2:
            continue
        out.add(t if len(t) <= 4 else t[:5])
    return out


_ORG_TOKEN_RE = re.compile(
    r"\b(?:equinor|aramco|adnoc|shell|bp|chevron|exxon|petrobras|eni|"
    r"totalenergies|conocophillips|occidental|oxy|saudi|"
    r"halliburton|slb|abb|oceaneering|emerson)\b",
    re.IGNORECASE,
)

# Уникальные сюжеты, которые СМИ перепечатывают под разными заголовками
_STORY_ANCHOR_RE = re.compile(
    r"\b(?:humain|sauai|prospect\s*hopper|oceaneering|"
    r"sanity\s*pipeline|twin1|geck\w*\s*robotics|raptor|"
    r"fpso|altahin\w*|альтахин\w*)\b",
    re.IGNORECASE,
)


def _story_anchors(text: str) -> set[str]:
    return {
        re.sub(r"\s+", "", m.group(0).casefold())
        for m in _STORY_ANCHOR_RE.finditer(text or "")
    }


def _same_numbered_story(a: str, b: str) -> bool:
    """Один сюжет: якорь-сделка / компания+число / близкие основы."""
    na, nb = _norm_for_dup(a), _norm_for_dup(b)
    anchors = _story_anchors(a) & _story_anchors(b)
    if anchors:
        return True
    nums_a = set(re.findall(r"\d{2,}", na))
    nums_b = set(re.findall(r"\d{2,}", nb))
    if nums_a and nums_b and (nums_a & nums_b):
        orgs_a = {m.group(0).casefold() for m in _ORG_TOKEN_RE.finditer(na)}
        orgs_b = {m.group(0).casefold() for m in _ORG_TOKEN_RE.finditer(nb)}
        if orgs_a and orgs_b and (orgs_a & orgs_b):
            return True
    sa, sb = _title_stems(a), _title_stems(b)
    if not sa or not sb:
        return False
    return len(sa & sb) / len(sa | sb) >= 0.42


def dedupe_index_near_duplicates(
    index: list[dict[str, Any]],
    *,
    threshold: float = 0.76,
) -> tuple[list[dict[str, Any]], int]:
    """Оставляет одну статью на near-dup заголовок (предпочитает длиннее/новее)."""
    kept: list[dict[str, Any]] = []
    dropped = 0
    for item in sorted(index, key=_article_keep_score, reverse=True):
        title = str(item.get("title") or "")
        cid = str(item.get("cluster_id") or "")
        dup = False
        for prev in kept:
            pt = str(prev.get("title") or "")
            same_cluster = str(prev.get("cluster_id") or "") == cid
            # якоря сюжета (HUMAIN, Oceaneering…) — и между кластерами
            if _story_anchors(title) & _story_anchors(pt):
                dup = True
                break
            if not same_cluster:
                continue
            if is_near_duplicate_text(title, pt, threshold=threshold):
                dup = True
                break
            if _same_numbered_story(title, pt):
                dup = True
                break
        if dup:
            dropped += 1
            continue
        kept.append(item)
    return kept, dropped


def cleanup_clusters_report(report: dict[str, Any]) -> dict[str, Any]:
    """Убрать мусор, слить синонимичные темы, дедупнуть заголовки, пересчитать счётчики."""
    index = list(report.get("index") or [])
    before = len(index)

    clean: list[dict[str, Any]] = []
    junk_n = 0
    for item in index:
        if is_junk_article(
            str(item.get("title") or ""),
            str(item.get("abstract") or ""),
            link=str(item.get("link") or ""),
        ):
            junk_n += 1
            continue
        clean.append(item)

    # merge overlapping themes
    merged_n = 0
    for item in clean:
        cid = str(item.get("cluster_id") or "")
        target = CLUSTER_MERGE_MAP.get(cid)
        if not target or target == cid:
            continue
        item["cluster_id"] = target
        item["cluster_title"] = CLUSTER_TITLE_OVERRIDES.get(
            target, str(item.get("cluster_title") or target)
        )
        # подкластер родителя-синонима больше не валиден
        item["sub_cluster_id"] = None
        item["sub_cluster_title"] = None
        item["sub_local_id"] = None
        merged_n += 1

    clean, dedupe_n = dedupe_index_near_duplicates(clean)

    # meta clusters
    meta_by_id = {str(c.get("id")): dict(c) for c in (report.get("clusters") or []) if c.get("id")}
    for src, dst in CLUSTER_MERGE_MAP.items():
        if src in meta_by_id and dst in meta_by_id:
            # переносим description если у цели пусто
            if not (meta_by_id[dst].get("description") or "").strip():
                meta_by_id[dst]["description"] = meta_by_id[src].get("description") or ""
            del meta_by_id[src]
        elif src in meta_by_id and dst not in meta_by_id:
            meta_by_id[dst] = meta_by_id.pop(src)
            meta_by_id[dst]["id"] = dst

    for cid, title in CLUSTER_TITLE_OVERRIDES.items():
        if cid in meta_by_id:
            meta_by_id[cid]["title"] = title

    counts = Counter(str(i.get("cluster_id") or "") for i in clean if i.get("cluster_id"))
    sub_counts: Counter[str] = Counter()
    for i in clean:
        sid = i.get("sub_cluster_id")
        if sid:
            sub_counts[str(sid)] += 1

    clusters_out: list[dict[str, Any]] = []
    for cid, n in counts.most_common():
        meta = meta_by_id.get(cid) or {
            "id": cid,
            "title": CLUSTER_TITLE_OVERRIDES.get(cid, cid),
            "description": "",
            "subclusters": [],
        }
        meta["id"] = cid
        meta["member_count"] = int(n)
        if cid in CLUSTER_TITLE_OVERRIDES:
            meta["title"] = CLUSTER_TITLE_OVERRIDES[cid]
        # пересчитать подкластеры; выкинуть пустые
        new_subs = []
        for s in meta.get("subclusters") or []:
            sid = str(s.get("id") or "")
            sc = int(sub_counts.get(sid, 0))
            if sc <= 0:
                continue
            s = dict(s)
            s["member_count"] = sc
            new_subs.append(s)
        meta["subclusters"] = new_subs
        clusters_out.append(meta)

    # sync cluster_title on index
    title_by_id = {c["id"]: c.get("title") or c["id"] for c in clusters_out}
    for item in clean:
        cid = str(item.get("cluster_id") or "")
        if cid in title_by_id:
            item["cluster_title"] = title_by_id[cid]

    by_month_counter: Counter[str] = Counter()
    by_company: Counter[str] = Counter()
    by_source: Counter[str] = Counter()
    for item in clean:
        month = (item.get("date_norm") or "")[:7]
        if len(month) == 7:
            by_month_counter[month] += 1
        if item.get("company"):
            by_company[str(item["company"])] += 1
        src = normalize_source_label(
            str(item.get("source") or ""), str(item.get("link") or "")
        )
        if src:
            item["source"] = src
            by_source[src] += 1

    clean.sort(
        key=lambda item: (1 if item.get("date_norm") else 0, item.get("date_norm") or ""),
        reverse=True,
    )

    report = dict(report)
    report["index"] = clean
    report["clusters"] = clusters_out
    report["n_articles"] = len(clean)
    report["articles"] = len(clean)
    report["n_clusters"] = len(clusters_out)
    report["n_subclusters"] = sum(len(c.get("subclusters") or []) for c in clusters_out)
    report["noise"] = int(sum(1 for i in clean if i.get("is_noise")))
    report["by_month"] = [
        {"month": m, "count": by_month_counter[m]}
        for m in sorted(by_month_counter, reverse=True)
    ]
    report["by_company"] = [
        {"name": n, "count": c} for n, c in by_company.most_common(20)
    ]
    report["by_source"] = [
        {"name": n, "count": c} for n, c in by_source.most_common(20)
    ]
    report["cleanup"] = {
        "before": before,
        "after": len(clean),
        "junk_removed": junk_n,
        "merged_members": merged_n,
        "deduped": dedupe_n,
        "merge_map": dict(CLUSTER_MERGE_MAP),
    }
    report["generated_at"] = _utc_now()
    note = str(report.get("note") or "")
    tag = " cleanup: junk/merge/dedupe."
    if tag.strip() not in note:
        report["note"] = (note + tag).strip()
    print(
        f"[foreign-it] cleanup: {before}→{len(clean)} "
        f"junk={junk_n} merge={merged_n} dedupe={dedupe_n} "
        f"clusters={len(clusters_out)}",
        flush=True,
    )
    return report


def save_report_and_portal(report: dict[str, Any]) -> dict[str, Any]:
    """Записать clusters_report + portal_data (с cleanup)."""
    report = cleanup_clusters_report(report)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    portal = build_portal_payload(report)
    PORTAL_PATH.write_text(json.dumps(portal, ensure_ascii=False, indent=2), encoding="utf-8")
    global _portal_cache
    _portal_cache = {"mtime": None, "payload": None}
    return report


def event_topic_and_summary(title: str, abstract: str) -> tuple[str, str]:
    """Тема и краткий текст без дубля (RSS часто даёт text≈title ± источник)."""
    topic = (title or "").strip()
    summary = (abstract or "").strip()
    if not summary or is_near_duplicate_text(topic, summary):
        return topic, ""
    return topic, summary


def forecast_from_trend(
    trend: list[dict[str, Any]],
    *,
    title: str,
    mentions: int,
) -> dict[str, Any]:
    """Сценарий как в gartner.pipeline.forecast._stat_forecast (без SQLite)."""
    values = [int(p.get("count") or 0) for p in trend]
    if len(values) < 2:
        return {
            "direction": "stable",
            "confidence": 0.3,
            "narrative": (
                f"По теме «{title}» мало помесячной истории ({mentions} упоминаний). "
                "Направление выглядит стабильным до накопления ряда."
            ),
            "action": "Мониторить публикации компаний по теме ежемесячно",
            "monthly_multipliers": [1.0] * 6,
            "provider": "foreign_it_stat",
        }
    n = len(values)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    denom = sum((x - mean_x) ** 2 for x in xs) or 1.0
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values)) / denom
    if slope > 0.15:
        direction = "growing"
        mults = [1.0 + 0.05 * (i + 1) for i in range(6)]
        narrative = (
            f"Упоминания «{title}» растут у иностранных компаний. "
            "Вероятен переход от пилотов к расширению практик у лидеров."
        )
        action = "Сопоставить пилоты ИИ/автоматизации с практиками Exxon/Shell/Aramco в течение квартала"
    elif slope < -0.15:
        direction = "declining"
        mults = [max(0.5, 1.0 - 0.05 * (i + 1)) for i in range(6)]
        narrative = (
            f"Интенсивность упоминаний «{title}» снижается. "
            "Тема может уходить в зрелость или терять информационный интерес."
        )
        action = "Пересмотреть приоритет направления и зафиксировать критерии продолжения мониторинга"
    else:
        direction = "stable"
        mults = [1.0] * 6
        narrative = (
            f"Поток упоминаний «{title}» относительно ровный. "
            "Тема присутствует без резкого ускорения."
        )
        action = "Удерживать точечный мониторинг внедрений компаний по теме"
    return {
        "direction": direction,
        "confidence": round(min(0.75, 0.35 + n * 0.05), 2),
        "narrative": narrative,
        "action": action,
        "monthly_multipliers": [round(m, 3) for m in mults],
        "provider": "foreign_it_stat",
    }


def _stage_from_scores(innovation: float, execution: float) -> str:
    if innovation >= 55 and execution >= 55:
        return "breakthrough"
    if innovation >= 55 and execution < 55:
        return "emerging"
    if innovation < 55 and execution >= 55:
        return "mature"
    return "fading"


def _cluster_axis_scores(events_raw: list[dict[str, Any]]) -> tuple[float, float, str]:
    """Эвристика новизны × внедрённости — как в gartner.pipeline.enrich."""
    n = len(events_raw)
    titles = [str(e.get("title") or "") for e in events_raw if e.get("title")]
    companies = [str(e.get("company") or "") for e in events_raw if e.get("company")]
    months = sorted(
        {
            m
            for m in ((e.get("date_norm") or e.get("date") or "")[:7] for e in events_raw)
            if len(m) == 7
        }
    )
    unique_topics = len({t.casefold() for t in titles})
    unique_companies = len({c.casefold() for c in companies})
    latest = months[-1] if months else None
    earliest = months[0] if months else None
    freshness = 50.0
    if latest:
        try:
            ly, lm = map(int, latest.split("-"))
            now = datetime.now(timezone.utc)
            age_months = max(0, (now.year - ly) * 12 + (now.month - lm))
            freshness = max(10.0, 90.0 - age_months * 4)
        except Exception:
            pass
    innovation = min(
        95.0,
        0.45 * freshness
        + 0.35 * min(100.0, unique_topics * 12)
        + 0.20 * min(100.0, n * 5),
    )
    span_bonus = 70.0 if earliest and latest and earliest != latest else 40.0
    execution = min(
        95.0,
        0.40 * min(100.0, n * 6)
        + 0.40 * min(100.0, unique_companies * 15)
        + 0.20 * span_bonus,
    )
    # лёгкий разброс по id, чтобы совпавшие scores не слипались в одну точку
    jitter = (hash(str(events_raw[0].get("cluster_id") or titles[:1])) % 7) - 3
    innovation = max(5.0, min(95.0, innovation + jitter * 0.4))
    execution = max(5.0, min(95.0, execution - jitter * 0.35))
    stage = _stage_from_scores(innovation, execution)
    return float(innovation), float(execution), stage


def run_cluster(
    rows: list[dict[str, Any]],
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    *,
    n_clusters: int | None = None,
    max_subclusters: int = DEFAULT_MAX_SUBCLUSTERS,
) -> dict[str, Any]:
    settings = settings or get_settings()
    client = llm or LLMClient(settings)
    embeddings, article_ids = load_embeddings()
    if len(article_ids) < 3:
        return {"status": "skip", "reason": "not_enough", "n": int(len(article_ids))}

    by_id = {r["article_id"]: r for r in rows}
    keep_ids = set(by_id.keys())
    mask = np.array([str(a) in keep_ids for a in article_ids], dtype=bool)
    if mask.any() and int(mask.sum()) < len(article_ids):
        embeddings = embeddings[mask]
        article_ids = article_ids[mask]

    xy = _svd_xy(embeddings)
    auto_k = max(6, min(18, max(2, len(article_ids) // 25)))
    k = int(n_clusters) if n_clusters and int(n_clusters) >= 2 else auto_k
    k = max(2, min(k, max(2, len(article_ids) // 2)))
    print(f"[foreign-it] MiniBatchKMeans k={k} (auto={auto_k})", flush=True)
    labels, probs = _fallback_kmeans(embeddings, n_clusters=k)
    method = "minibatch_kmeans"

    use_llm = bool(client.enabled)
    print(
        f"[foreign-it] naming clusters ({'llm:' + settings.llm_model if use_llm else 'heuristic'})",
        flush=True,
    )
    cluster_titles: dict[int, tuple[str, str]] = {}
    label_ids = sorted({int(x) for x in labels.tolist() if int(x) >= 0})
    for i, label in enumerate(label_ids, start=1):
        mask_l = labels == label
        titles = []
        abstracts = []
        for aid in article_ids[mask_l]:
            row = by_id.get(str(aid)) or {}
            if row.get("title"):
                titles.append(row["title"])
            if row.get("text"):
                abstracts.append(str(row["text"])[:240])
        if not use_llm:
            cluster_titles[label] = _heuristic_name(titles[:40])
            continue
        try:
            print(f"[foreign-it] llm name {i}/{len(label_ids)} fi{label}…", flush=True)
            named = client.json_call(
                CLUSTER_PROMPT,
                {"titles": titles[:18], "abstracts": abstracts[:10]},
                max_retries=2,
            )
            name = str(named.get("name") or "").strip()
            desc = str(named.get("description") or "").strip()
            if not name:
                raise ValueError("empty LLM name")
            cluster_titles[label] = (name[:80], desc or f"Группа новостей вокруг темы «{name}».")
        except Exception as exc:
            print(f"[foreign-it] llm name failed fi{label}: {exc}", flush=True)
            cluster_titles[label] = _heuristic_name(titles[:40])

    # подкластеры
    min_parent = max(8, int(settings.subcluster_min_parent_size) - 2)
    min_sub = max(3, int(settings.subcluster_min_size) - 1)
    id_to_idx = {str(aid): i for i, aid in enumerate(article_ids)}
    sub_by_parent: dict[str, list[dict[str, Any]]] = {}
    member_sub: dict[str, tuple[str | None, int | None, str | None]] = {}

    from sklearn.cluster import MiniBatchKMeans

    for label in label_ids:
        cid = f"fi{label}"
        mask_l = labels == label
        n_members = int(mask_l.sum())
        if n_members < min_parent:
            continue
        local_ids = [str(a) for a in article_ids[mask_l]]
        titles = [(by_id.get(a) or {}).get("title") or "" for a in local_ids]
        texts = [(by_id.get(a) or {}).get("text") or "" for a in local_ids]
        idx = np.array([id_to_idx[a] for a in local_ids], dtype=int)
        local_emb = embeddings[idx]
        k_sub = 2 if n_members < 30 else (3 if n_members < 60 else min(4, max_subclusters))
        k_sub = min(k_sub, max_subclusters, max(2, n_members // max(min_sub, 2)))
        if k_sub < 2:
            continue
        try:
            km = MiniBatchKMeans(
                n_clusters=k_sub, random_state=42, n_init=8, batch_size=min(128, n_members)
            )
            sl = km.fit_predict(local_emb)
        except Exception:
            continue
        subs: list[dict[str, Any]] = []
        for lid in sorted({int(x) for x in sl.tolist()}):
            smask = sl == lid
            if int(smask.sum()) < min_sub:
                continue
            sub_titles = [titles[j] for j, ok in enumerate(smask.tolist()) if ok]
            sub_abstracts = [str(texts[j])[:200] for j, ok in enumerate(smask.tolist()) if ok]
            sub_name = compress_label(_heuristic_name(sub_titles)[0])
            if use_llm:
                try:
                    named = client.json_call(
                        SUB_PROMPT,
                        {
                            "titles": sub_titles[:14],
                            "abstracts": sub_abstracts[:8],
                            "parent_title": cluster_titles.get(label, ("", ""))[0],
                        },
                        max_retries=2,
                    )
                    llm_name = str(
                        named.get("cluster_name") or named.get("name") or ""
                    ).strip()
                    if llm_name:
                        sub_name = compress_label(llm_name)
                except Exception as exc:
                    print(f"[foreign-it] llm sub-name failed {cid}_s{lid}: {exc}", flush=True)
            sid = f"{cid}_s{lid}"
            subs.append(
                {
                    "id": sid,
                    "local_id": lid,
                    "title": sub_name,
                    "member_count": int(smask.sum()),
                }
            )
            for j, ok in enumerate(smask.tolist()):
                if ok:
                    member_sub[local_ids[j]] = (sid, lid, sub_name)
        if len(subs) >= 2:
            sub_by_parent[cid] = sorted(subs, key=lambda s: -s["member_count"])

    counts: Counter[str] = Counter()
    for label in labels.tolist():
        if int(label) >= 0:
            counts[f"fi{int(label)}"] += 1

    clusters_out: list[dict[str, Any]] = []
    for label in sorted(counts.keys(), key=lambda c: -counts[c]):
        lid = int(label.replace("fi", ""))
        title, desc = cluster_titles.get(lid, (f"Тема {label}", ""))
        clusters_out.append(
            {
                "id": label,
                "title": title,
                "description": desc,
                "member_count": int(counts[label]),
                "subclusters": sub_by_parent.get(label, []),
            }
        )

    index: list[dict[str, Any]] = []
    for aid, label, prob, x, y in zip(
        article_ids, labels, probs, xy[:, 0], xy[:, 1], strict=False
    ):
        row = by_id.get(str(aid)) or {}
        is_noise = 1 if int(label) < 0 else 0
        cid = None if is_noise else f"fi{int(label)}"
        ctitle = cluster_titles.get(int(label), ("", ""))[0] if cid else None
        sid, s_local, s_title = member_sub.get(str(aid), (None, None, None))
        date = str(row.get("datatime") or "")[:10]
        index.append(
            {
                "article_id": str(aid),
                "title": (row.get("title") or "")[:180],
                "title_en": (row.get("title_en") or "")[:180],
                "abstract": (row.get("text") or "")[:1200],
                "date": date,
                "date_norm": date,
                "source": row.get("source") or "",
                "link": row.get("link") or "",
                "company": row.get("company") or "",
                "company_id": row.get("company_id") or "",
                "cluster_id": cid,
                "cluster_title": ctitle,
                "sub_cluster_id": sid,
                "sub_cluster_title": s_title,
                "sub_local_id": s_local,
                "is_noise": is_noise,
                "kind": "news",
                "probability": float(prob),
                "umap_x": float(x),
                "umap_y": float(y),
            }
        )

    index.sort(
        key=lambda item: (1 if item.get("date_norm") else 0, item.get("date_norm") or ""),
        reverse=True,
    )

    by_month_counter: Counter[str] = Counter()
    by_company: Counter[str] = Counter()
    by_source: Counter[str] = Counter()
    for item in index:
        month = (item.get("date_norm") or "")[:7]
        if len(month) == 7:
            by_month_counter[month] += 1
        if item.get("company"):
            by_company[str(item["company"])] += 1
        if item.get("source"):
            by_source[str(item["source"])] += 1

    report = {
        "source": "foreign_it_clusters",
        "flow": "foreign_it",
        "mode": "news",
        "method": method,
        "requested_n_clusters": k,
        "max_subclusters": max_subclusters,
        "n_articles": len(index),
        "n_clusters": len(clusters_out),
        "n_subclusters": sum(len(c.get("subclusters") or []) for c in clusters_out),
        "noise": int(sum(1 for i in index if i.get("is_noise"))),
        "articles": len(index),
        "by_month": [
            {"month": m, "count": by_month_counter[m]}
            for m in sorted(by_month_counter, reverse=True)
        ],
        "by_company": [
            {"name": n, "count": c} for n, c in by_company.most_common(20)
        ],
        "by_source": [
            {"name": n, "count": c} for n, c in by_source.most_common(20)
        ],
        "clusters": clusters_out,
        "index": index,
        "generated_at": _utc_now(),
        "note": (
            "Поток «Иностранные компании · ИТ/автоматизация»: "
            "перевод Lab → TF-IDF/KMeans → русские имена кластеров."
        ),
    }
    report = save_report_and_portal(report)

    return {
        "status": "ok",
        "method": method,
        "n_articles": report["n_articles"],
        "n_clusters": report["n_clusters"],
        "n_subclusters": report["n_subclusters"],
        "cleanup": report.get("cleanup"),
        "report": str(REPORT_PATH),
        "portal": str(PORTAL_PATH),
    }


def build_portal_payload(report: dict[str, Any] | None = None) -> dict[str, Any]:
    """Форма как у data/portal/portal_data.json (ИТ-поток), для будущей подгрузки."""
    if report is None:
        if not REPORT_PATH.exists():
            return {}
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    index_all = list(report.get("index") or [])
    index = []
    dropped_old = 0
    for item in index_all:
        d = (item.get("date_norm") or item.get("date") or "")[:10]
        if d and d < PORTAL_MIN_DATE:
            dropped_old += 1
            continue
        index.append(item)
    if dropped_old:
        print(
            f"[foreign-it] portal drop date<{PORTAL_MIN_DATE}: {dropped_old}",
            flush=True,
        )

    clusters_meta = {c["id"]: c for c in (report.get("clusters") or []) if c.get("id")}

    by_cluster: dict[str, list[dict[str, Any]]] = {}
    for item in index:
        cid = item.get("cluster_id")
        if not cid or item.get("is_noise"):
            continue
        by_cluster.setdefault(str(cid), []).append(item)

    cluster_cards: list[dict[str, Any]] = []
    for cid, events_raw in by_cluster.items():
        meta = clusters_meta.get(cid) or {}
        companies: Counter[str] = Counter()
        months: Counter[str] = Counter()
        for e in events_raw:
            if e.get("company"):
                companies[str(e["company"])] += 1
            m = (e.get("date_norm") or e.get("date") or "")[:7]
            if len(m) == 7:
                months[m] += 1
        month_keys = sorted(months.keys())
        trend = [{"month": m, "count": months[m]} for m in month_keys]
        slope = _month_slope(month_keys, [months[m] for m in month_keys])
        events_sorted = sorted(
            events_raw,
            key=lambda x: (x.get("date_norm") or x.get("date") or ""),
            reverse=True,
        )
        innovation, execution, stage = _cluster_axis_scores(
            [{**e, "cluster_id": cid} for e in events_raw]
        )
        title = normalize_ai_term(str(meta.get("title") or cid))
        description = normalize_ai_term(str(meta.get("description") or ""))
        subs = []
        for s in meta.get("subclusters") or []:
            row = dict(s)
            row["title"] = normalize_ai_term(str(row.get("title") or ""))
            subs.append(row)
        events_out = []
        for e in events_sorted[:40]:
            topic, summary = event_topic_and_summary(
                str(e.get("title") or ""),
                str(e.get("abstract") or ""),
            )
            link = str(e.get("link") or "")
            events_out.append(
                {
                    "id": e.get("article_id"),
                    "date": (e.get("date_norm") or e.get("date") or "")[:10],
                    "topic": topic,
                    "summary": summary,
                    "company": e.get("company") or "",
                    "category": "IT",
                    "source": normalize_source_label(str(e.get("source") or ""), link),
                    "link": link,
                    "sub_cluster_id": e.get("sub_cluster_id"),
                    "sub_cluster_title": normalize_ai_term(
                        str(e.get("sub_cluster_title") or "")
                    ),
                    "sub_local_id": e.get("sub_local_id"),
                }
            )
        forecast = forecast_from_trend(trend, title=title, mentions=len(events_raw))
        # UI иногда показывает up/down — оставляем совместимый alias
        if forecast["direction"] == "growing":
            forecast["direction"] = "up"
        elif forecast["direction"] == "declining":
            forecast["direction"] = "down"
        cluster_cards.append(
            {
                "id": cid,
                "title": title,
                "description": description,
                "stage": stage,
                "stage_label": STAGE_LABELS.get(stage, stage),
                "segment_focus": "IT / Automation",
                "innovation_score": round(innovation, 1),
                "execution_score": round(execution, 1),
                "mentions": len(events_raw),
                "companies": [{"name": n, "count": int(c)} for n, c in companies.most_common(8)],
                "trend": trend,
                "slope": round(float(slope), 4),
                "events": events_out,
                "subclusters": subs,
                "forecast": forecast,
            }
        )

    cluster_cards.sort(key=lambda x: x["mentions"], reverse=True)
    growing = [c for c in cluster_cards if c["slope"] > 0.05][:5]
    fading = [c for c in cluster_cards if c["slope"] < -0.05][:5]
    company_counter: Counter[str] = Counter()
    for card in cluster_cards:
        for co in card["companies"]:
            company_counter[co["name"]] += co["count"]
    sources = sorted(
        {
            normalize_source_label(str(i.get("source") or ""), str(i.get("link") or ""))
            for i in index
            if i.get("source") or i.get("link")
        }
    )
    sources = [s for s in sources if s]
    n_events = sum(len(c.get("events") or []) for c in cluster_cards)

    return {
        "generated_at": _utc_now(),
        "product": "OilTech Radar · Foreign IT",
        "flow": "foreign_it",
        "provenance": {
            "live_article_links": len(index),
            "is_live_scrape": True,
            "banner": (
                "Иностранные нефтегазовые компании · ИТ и автоматизация. "
                f"Статей в кластерах: {len(index)} (с {PORTAL_MIN_DATE})."
            ),
            "source_report": str(REPORT_PATH),
            "min_date": PORTAL_MIN_DATE,
            "dropped_before_min_date": dropped_old,
        },
        "kpis": {
            "topics": len(cluster_cards),
            "events": n_events if n_events else len(index),
            "articles": len(index),
            "sources": len(sources),
            "growing": len(growing),
        },
        "sources": sources,
        "geography": {"mode": "none", "cities": [], "matched_events": 0, "unmatched_events": 0},
        "diff_lines": [],
        "clusters": cluster_cards,
        "growing": [
            {"id": c["id"], "title": c["title"], "slope": c["slope"], "mentions": c["mentions"]}
            for c in growing
        ],
        "fading": [
            {"id": c["id"], "title": c["title"], "slope": c["slope"], "mentions": c["mentions"]}
            for c in fading
        ],
        "companies": [{"name": n, "count": int(c)} for n, c in company_counter.most_common(12)],
        "quadrant": [
            {
                "id": c["id"],
                "title": c["title"],
                "x": c["execution_score"],
                "y": c["innovation_score"],
                "mentions": c["mentions"],
            }
            for c in cluster_cards
        ],
    }


_portal_cache: dict[str, Any] = {"mtime": None, "payload": None}


def foreign_it_portal_payload() -> dict[str, Any]:
    """Payload для /api/portal/foreign-it — тот же контракт, что /api/portal."""
    if not PORTAL_PATH.exists() and not REPORT_PATH.exists():
        return {
            "generated_at": _utc_now(),
            "product": "OilTech Radar · Foreign IT",
            "flow": "foreign_it",
            "kpis": {"topics": 0, "events": 0, "articles": 0, "sources": 0, "growing": 0},
            "sources": [],
            "clusters": [],
            "growing": [],
            "fading": [],
            "companies": [],
            "quadrant": [],
            "provenance": {
                "banner": "Нет данных. Сначала: python scripts/cluster_foreign_it_lab.py",
                "is_live_scrape": False,
            },
        }
    try:
        mtime = PORTAL_PATH.stat().st_mtime if PORTAL_PATH.exists() else REPORT_PATH.stat().st_mtime
    except OSError:
        mtime = None
    if (
        _portal_cache.get("payload") is not None
        and _portal_cache.get("mtime") == mtime
    ):
        return _portal_cache["payload"]

    if PORTAL_PATH.exists():
        payload = json.loads(PORTAL_PATH.read_text(encoding="utf-8"))
    else:
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        payload = build_portal_payload(report)
    _portal_cache["mtime"] = mtime
    _portal_cache["payload"] = payload
    return payload


def foreign_it_article_detail(article_id: str) -> dict[str, Any] | None:
    if not REPORT_PATH.exists():
        return None
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    for item in report.get("index") or []:
        if str(item.get("article_id") or "") != str(article_id):
            continue
        return {
            "article_id": item.get("article_id"),
            "title": item.get("title") or "",
            "title_en": item.get("title_en") or "",
            "abstract": item.get("abstract") or "",
            "date": item.get("date") or "",
            "source": item.get("source") or "",
            "link": item.get("link") or "",
            "company": item.get("company") or "",
            "cluster_id": item.get("cluster_id"),
            "cluster_title": item.get("cluster_title"),
            "sub_cluster_id": item.get("sub_cluster_id"),
            "sub_cluster_title": item.get("sub_cluster_title"),
        }
    return None


def run_foreign_it_pipeline(
    *,
    input_paths: list[Path] | None = None,
    force_translate: bool = False,
    skip_translate: bool = False,
    translate_only: bool = False,
    force_embeddings: bool = False,
    local_embeddings: bool = True,
    batch_size: int = 5,
    limit: int = 0,
    n_clusters: int | None = None,
    max_subclusters: int = DEFAULT_MAX_SUBCLUSTERS,
    settings: Settings | None = None,
    llm: LLMClient | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    client = llm or LLMClient(settings)

    raw = load_raw_articles(input_paths)
    if limit and limit > 0:
        raw = raw[:limit]

    if skip_translate:
        rows = load_translated()
        if not rows:
            raise FileNotFoundError(
                f"Нет перевода: {TRANSLATED_JSONL}. Уберите --skip-translate."
            )
        if limit and limit > 0:
            rows = rows[:limit]
        translate_meta = {"status": "skipped_cached", "n": len(rows)}
    else:
        rows = translate_articles(
            raw,
            client,
            batch_size=batch_size,
            limit=0,  # raw already sliced
            force=force_translate,
        )
        translate_meta = {"status": "ok", "n": len(rows)}

    if translate_only:
        return {"translate": translate_meta, "cluster": {"status": "skipped"}}

    emb = ensure_embeddings(
        rows, force=force_embeddings, local=local_embeddings, llm=client
    )
    cluster = run_cluster(
        rows,
        settings=settings,
        llm=client,
        n_clusters=n_clusters,
        max_subclusters=max_subclusters,
    )
    return {"translate": translate_meta, "embeddings": emb, "cluster": cluster}
