"""Тематика сайта: нефтегаз или брак."""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

# Подстроки (длинные/однозначные) — обычный `in`
OILGAS_KEYWORDS = (
    "нефт",
    "газпром",
    "газификац",
    "нефтегаз",
    "нефтехим",
    "нефтесервис",
    "месторожд",
    "скважин",
    "бурен",
    "буров",
    "буровую",
    "гидроразрыв",
    "колтюбинг",
    "углеводород",
    "геолог",
    "геофиз",
    "сейсми",
    "трубопровод",
    "нефтепровод",
    "газопровод",
    "транснефт",
    "лукойл",
    "роснефт",
    "татнефть",
    "новатэк",
    "сибур",
    "сургутнефтегаз",
    "башнефть",
    "зарубежнефть",
    "yamal",
    "arctic lng",
    "oil & gas",
    "oil and gas",
    "petroleum",
    "hydrocarbon",
    "refinery",
    "wellbore",
    "drilling",
    "upstream",
    "downstream",
    "midstream",
)

# Короткие/опасные токены — только как отдельные слова (не «газете», не «муниципал», не «обмундирование»)
OILGAS_BOUNDED = (
    "газ",
    "газа",
    "газе",
    "газов",
    "спг",
    "lng",
    "грп",
    "керн",
    "мун",
    "пнг",
    "нпз",
    "гпз",
)

# слишком общие «газ» в «магазин» не ловим — смотрим словоформы выше
REJECT_HINTS = (
    "интернет-магазин",
    "каталог товаров",
    "доставка по россии",
    "корзина",
)

_BOUNDED_RE = {
    kw: re.compile(rf"(?<![а-яa-z0-9]){re.escape(kw)}(?![а-яa-z0-9])", re.IGNORECASE)
    for kw in OILGAS_BOUNDED
}


def _plain_text(html: str, limit: int = 12000) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = " ".join(soup.get_text(" ", strip=True).split())
    return f"{title} {text}"[:limit].lower()


def score_oilgas(text: str) -> int:
    blob = (text or "").lower()
    hits = 0
    for kw in OILGAS_KEYWORDS:
        if kw in blob:
            hits += 1
    for kw, rx in _BOUNDED_RE.items():
        if rx.search(blob):
            hits += 1
    return hits


def classify_theme(html: str, *, url: str = "", extra_text: str = "") -> dict[str, Any]:
    """oilgas / mixed / other по HTML главной или ленты."""
    blob = _plain_text(html) + " " + (extra_text or "").lower() + " " + (url or "").lower()
    hits = score_oilgas(blob)
    reject = any(h in blob for h in REJECT_HINTS) and hits < 2
    if hits >= 3 and not reject:
        theme = "oilgas"
    elif hits >= 1 and not reject:
        theme = "mixed"
    else:
        theme = "other"
    return {
        "theme": theme,
        "hits": hits,
        "accepted": theme in {"oilgas", "mixed"},
        "reason": (
            f"ключевых совпадений нефтегаза: {hits}"
            + ("; похоже на витрину, не медиа" if reject else "")
        ),
    }


def classify_theme_llm(llm: Any, *, domain: str, html: str, url: str) -> dict[str, Any] | None:
    if llm is None or not getattr(llm, "enabled", False):
        return None
    prompt = """
Ты классификатор сайтов для радара нефтегаза РФ.
Верни ТОЛЬКО JSON:
{"theme":"oilgas|mixed|other","accepted":true,"reason":"кратко"}
oilgas — оператор/отраслевое медиа/сервис нефтегаза.
mixed — есть раздел про нефтегаз среди прочего.
other — нет нефтегаза (отказать).
""".strip()
    try:
        raw = llm.json_call(
            prompt,
            {
                "domain": domain,
                "url": url,
                "html_excerpt": (html or "")[:8000],
            },
        )
        theme = str(raw.get("theme") or "other").lower()
        if theme not in {"oilgas", "mixed", "other"}:
            theme = "other"
        accepted = bool(raw.get("accepted")) if "accepted" in raw else theme != "other"
        if theme == "other":
            accepted = False
        return {
            "theme": theme,
            "hits": None,
            "accepted": accepted,
            "reason": str(raw.get("reason") or ""),
            "method": "llm",
        }
    except Exception:
        return None
