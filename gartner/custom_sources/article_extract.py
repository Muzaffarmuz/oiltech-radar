"""Выемка title/date/text из HTML статьи: trafilatura, запас BeautifulSoup."""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from gartner.custom_sources.engine import ArticleRecord, infer_date_from_html, infer_date_from_url, parse_date_any
from gartner.custom_sources.rules import domain_from_url
from gartner.custom_sources.scoring import news_score

GENERIC_TITLES = {
    "пресс-релиз",
    "пресс-релизы",
    "пресс-релизы и мероприятия",
    "новости",
    "пресс-центр",
    "press releases",
    "press release",
    "news",
    "media",
}

CHROME_PREFIXES = (
    "главная ",
    "пресс-центр ",
    "пресс центр ",
    "новости ",
    "пресс-релизы и мероприятия ",
    "пресс-релизы ",
    "пресс-релиз ",
)


def _first_sentence(text: str) -> str:
    t = " ".join((text or "").split())
    low = t.lower()
    changed = True
    while changed:
        changed = False
        for prefix in CHROME_PREFIXES:
            if low.startswith(prefix):
                t = t[len(prefix) :].lstrip("—–-|/ ")
                low = t.lower()
                changed = True
    if len(t) < 20:
        return t
    m = re.match(r"(.{20,240}?(?:[.!?]|$))", t)
    chunk = (m.group(1) if m else t[:220]).strip()
    return chunk.rstrip(" .")


def is_generic_title(title: str) -> bool:
    t = re.sub(r"\s+", " ", (title or "").strip().lower())
    if not t or len(t) < 12:
        return True
    if t in GENERIC_TITLES:
        return True
    if t.startswith("новости |") or t.startswith("news |") or t.startswith("пресс-релиз"):
        return True
    if t.count("|") >= 1 and len(t) < 90:
        return True
    return False


def polish_title(title: str, text: str) -> str:
    t = re.sub(r"\s+", " ", (title or "").strip())
    first = _first_sentence(text)
    if is_generic_title(t) and len(first) >= 20:
        return first[:240]
    if t and first and t.lower() not in first.lower()[:80] and is_generic_title(t):
        return first[:240]
    return t[:240] or first[:240]


def _bs_extract(html: str, url: str) -> dict[str, str]:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        tag.decompose()
    title = ""
    for sel in ("h1", "article h1", ".news-title", ".article-title"):
        node = soup.select_one(sel)
        if node:
            title = node.get_text(" ", strip=True)
            if title:
                break
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)
    body_node = None
    for sel in ("article", "[itemprop='articleBody']", ".news-detail", ".article-body", "main"):
        body_node = soup.select_one(sel)
        if body_node:
            break
    text = " ".join((body_node or soup).get_text(" ", strip=True).split())
    date_raw = infer_date_from_html(soup) or infer_date_from_url(url)
    return {"title": title, "text": text, "date": date_raw}


def _trafilatura_extract(html: str, url: str) -> dict[str, str] | None:
    try:
        import trafilatura
    except ImportError:
        return None
    try:
        packed = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=False,
            with_metadata=True,
            output_format="json",
        )
    except Exception:
        packed = None
    if not packed:
        text_only = trafilatura.extract(html, url=url, include_comments=False) or ""
        if len(text_only) < 80:
            return None
        meta = {}
        try:
            meta_obj = trafilatura.extract_metadata(html, default_url=url)
            if meta_obj:
                meta = {
                    "title": getattr(meta_obj, "title", "") or "",
                    "date": getattr(meta_obj, "date", "") or "",
                }
        except Exception:
            meta = {}
        return {
            "title": str(meta.get("title") or ""),
            "text": text_only,
            "date": parse_date_any(str(meta.get("date") or "")),
        }
    import json

    try:
        data = json.loads(packed)
    except json.JSONDecodeError:
        return None
    text = str(data.get("text") or "")
    if len(text) < 80:
        return None
    return {
        "title": str(data.get("title") or ""),
        "text": text,
        "date": parse_date_any(str(data.get("date") or "")),
    }


def _looks_like_binary(html: str) -> bool:
    head = html[:24] if html else ""
    if head.startswith(("%PDF", "PK\x03\x04", "PK\x05\x06", "PK\x07\x08", "\xff\xd8")):
        return True
    if "JFIF" in html[:80] or "\x00" in html[:120]:
        return True
    return False


_POLICY_MARKERS = (
    "политикой конфиденциальности",
    "политика конфиденциальности",
    "общие положения",
    "обработки персональных данных",
    "privacy policy",
    "personal data",
)

# Скрытые модалки (как на onhpgroup.com: .eb-hide / #dialog*) и cookie-баннеры.
_STRIP_SELECTORS = (
    ".eb-hide",
    ".eb-dialog",
    "[hidden]",
    "#sp-cookie-consent",
    ".sp-cookie-consent",
    ".cookie-consent",
    ".cookie-banner",
    "#privacy-policy",
    ".privacy-policy",
)


def _sanitize_article_html(html: str) -> str:
    """Убрать скрытые диалоги/баннеры, которые trafilatura часто принимает за тело статьи."""
    try:
        soup = BeautifulSoup(html or "", "html.parser")
    except Exception:
        return html or ""
    for sel in _STRIP_SELECTORS:
        for node in soup.select(sel):
            node.decompose()
    for node in list(soup.find_all(["div", "section", "aside", "dialog"])):
        blob = " ".join(node.get_text(" ", strip=True).split()).lower()
        if len(blob) < 400:
            continue
        hits = sum(1 for m in _POLICY_MARKERS if m in blob)
        if hits >= 2 and ("1.1." in blob or "пользователь" in blob):
            node.decompose()
    return str(soup)


def _looks_like_policy_text(text: str) -> bool:
    """Текст почти целиком — политика ПДн / конфиденциальность, не новость."""
    t = " ".join((text or "").split())
    if len(t) < 200:
        return False
    low = t.lower()
    head = low[:500]
    hits = sum(1 for m in _POLICY_MARKERS if m in low)
    head_hits = sum(1 for m in _POLICY_MARKERS if m in head)
    if head_hits >= 2:
        return True
    if hits >= 3 and ("1.1." in low or "1.2." in low) and len(t) > 1500:
        # Политика часто длиннее новости и с нумерацией пунктов.
        return True
    return False


def _strip_trailing_policy(text: str) -> str:
    """Если после короткой новости прилипла политика — обрезать хвост."""
    t = " ".join((text or "").split())
    low = t.lower()
    cut_at = -1
    for marker in (
        "1. общие положения",
        "политика конфиденциальности",
        "политикой конфиденциальности",
    ):
        idx = low.find(marker)
        if idx >= 180 and (cut_at < 0 or idx < cut_at):
            cut_at = idx
    if cut_at > 0:
        return t[:cut_at].rstrip(" .;,—–-")
    return t


def extract_article_page(html: str, url: str, *, source_name: str | None = None) -> ArticleRecord | None:
    if not html or news_score(url) < -2:
        return None
    if _looks_like_binary(html):
        return None
    clean = _sanitize_article_html(html)
    raw = _trafilatura_extract(clean, url) or _bs_extract(clean, url)
    text = _strip_trailing_policy(" ".join((raw.get("text") or "").split()))
    if len(text) < 200 or _looks_like_policy_text(text):
        # Повтор без trafilatura — часто main/article чище модалки.
        raw_bs = _bs_extract(clean, url)
        text_bs = _strip_trailing_policy(" ".join((raw_bs.get("text") or "").split()))
        if len(text_bs) >= 200 and not _looks_like_policy_text(text_bs):
            raw, text = raw_bs, text_bs
        else:
            return None
    title = polish_title(raw.get("title") or "", text)
    if not title or title.startswith("PK") or "JFIF" in title:
        return None
    if is_generic_title(title) and _looks_like_policy_text(text):
        return None
    datatime = raw.get("date") or infer_date_from_url(url)
    if not datatime:
        soup = BeautifulSoup(clean, "html.parser")
        datatime = infer_date_from_html(soup)
    source = source_name or domain_from_url(url)
    return ArticleRecord(
        title=title[:500],
        text=text[:50000],
        datatime=datatime or "",
        source=source,
        link=url,
    )


def extract_probe_dict(rec: ArticleRecord) -> dict[str, Any]:
    return {
        "title": rec.title,
        "datatime": rec.datatime,
        "link": rec.link,
        "text_chars": len(rec.text),
        "text_preview": rec.text[:280],
    }
