"""Скоринг URL/анкоров: новость vs служебные страницы. Без LLM."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

from gartner.custom_sources.rules import domain_from_url

NEWS_POS = (
    "news",
    "novosti",
    "press",
    "press-tsentr",
    "press_center",
    "press-center",
    "press-reliz",
    "press_reliz",
    "reliz",
    "release",
    "media",
    "smi",
    "лента",
    "новост",
    "пресс",
    "аналит",
    "blog",
    "блог",
    "article",
    "statya",
)

NEWS_NEG = (
    "contact",
    "kontact",
    "kontakty",
    "vacancy",
    "vakans",
    "career",
    "about",
    "requisite",
    "rekvizit",
    "staff",
    "social",
    "facebook",
    "vk.com",
    "t.me",
    "linkedin",
    "instagram",
    "cookie",
    "privacy",
    "personal-data",
    "sitemap",
    "search",
    "login",
    "cart",
    "shop",
    "company/index",
    "o-kompanii",
    "о-компании",
)

ARTICLE_QUERY_KEYS = (
    "id_4",
    "element_id",
    "ELEMENT_ID",
    "rid",
    "news_id",
    "id",
    "ID",
    "elementid",
    "CODE",
    # WordPress: одиночный пост
    "p",
)

# Лента/рубрика в query (WordPress cat=… и аналоги), не статья.
HUB_QUERY_KEYS = (
    "cat",
    "category",
    "category_id",
    "category_name",
    "rubric",
    "section",
)


def same_site(url: str, base: str) -> bool:
    try:
        return domain_from_url(url) == domain_from_url(base)
    except ValueError:
        return False


def news_score(url: str, anchor: str = "") -> int:
    blob = f"{url} {anchor}".lower()
    score = 0
    for kw in NEWS_POS:
        if kw in blob:
            score += 2
    for kw in NEWS_NEG:
        if kw in blob:
            score -= 6
    parsed = urlparse(url)
    qs = {k.lower(): v for k, v in parse_qs(parsed.query).items()}
    if any(k.lower() in qs for k in ARTICLE_QUERY_KEYS):
        score += 4
    if any(k.lower() in qs for k in HUB_QUERY_KEYS) and not any(
        k.lower() in qs for k in ARTICLE_QUERY_KEYS
    ):
        score += 3
    path = parsed.path.lower()
    if path.rstrip("/") in {"", "/"} and not qs:
        score -= 1
    # Control Engineering и похожие: /2026/10/13/slug/
    if re.search(r"/\d{4}/\d{2}/\d{2}(?:/|$)", path):
        score += 4
    # TAdviser: /index.php/Название_статьи (не категория)
    if _tadviser_article_path(parsed):
        score += 4
    # ITPS / CTA: /press/news/slug/
    if re.search(r"/(?:press/)?(?:news|article)/[^/]+", path) and path.rstrip("/").count("/") >= 3:
        score += 3
    return score


_TADVISER_NAV = {
    "новости",
    "аналитика",
    "отрасли",
    "проекты",
    "компании",
    "продукты",
    "персоналии",
    "карта информатизации бизнеса",
    "главная страница",
}


def _tadviser_article_path(parsed) -> bool:
    host = (parsed.netloc or "").lower()
    if "tadviser." not in host:
        return False
    # Короткие алиасы /a/123456 — новости
    parts = [p for p in (parsed.path or "").split("/") if p]
    if len(parts) == 2 and parts[0] == "a" and parts[1].isdigit():
        return True
    path = unquote(parsed.path or "")
    path_l = path.lower()
    if path_l.startswith("/index.php/"):
        slug = path[len("/index.php/") :].strip("/")
        if not slug:
            return False
        slug_l = slug.lower()
        if slug_l.startswith(("категория:", "category:", "служебная:", "special:")):
            return False
        if slug_l in _TADVISER_NAV:
            return False
        return len(slug) >= 8
    qs = {k.lower(): v for k, v in parse_qs(parsed.query).items()}
    title = unquote((qs.get("title") or [""])[0])
    title_l = title.lower()
    ptype = (qs.get("ptype") or [""])[0].lower()
    if ptype == "news":
        return False
    if title and not title_l.startswith(("категория:", "category:", "служебная:")):
        if title_l in _TADVISER_NAV:
            return False
        return len(title) >= 8
    return False


def looks_like_article_url(url: str) -> bool:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if any(k in qs or k.lower() in {x.lower() for x in qs} for k in ARTICLE_QUERY_KEYS):
        return True
    lowered = {k.lower() for k in qs}
    if lowered & {k.lower() for k in ARTICLE_QUERY_KEYS}:
        return True
    path = parsed.path.lower()
    if re.search(r"/\d{4}/\d{2}/\d{2}(?:/|$)", path):
        return True
    if _tadviser_article_path(parsed):
        return True
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return False
    if len(parts) >= 3:
        return True
    hubs = {"news", "novosti", "press", "press-center", "presscenter", "media", "blog"}
    if len(parts) >= 2 and parts[0].lower() in hubs:
        return True
    return False


def looks_like_hub_url(url: str) -> bool:
    """Лента новостей — короткий путь или query-рубрика. Глубокие /press/news/slug — уже статьи."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    lowered = {k.lower() for k in qs}
    # WordPress / CMS: ?cat=5 — лента, ?p=… — пост (не хаб)
    if lowered & {k.lower() for k in HUB_QUERY_KEYS}:
        if lowered & {k.lower() for k in ARTICLE_QUERY_KEYS}:
            return False
        if "page_id" in lowered:
            return False
        return True
    # TAdviser category news hub
    if "tadviser." in (parsed.netloc or "").lower():
        title = unquote((qs.get("title") or [""])[0]).lower()
        ptype = (qs.get("ptype") or [""])[0].lower()
        if ptype == "news" or title.startswith(("категория:", "category:")):
            return True
        return False
    if qs:
        return False
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return False
    # /press/news/article-slug — не хаб
    if len(parts) >= 3:
        return False
    blob = parsed.path.lower()
    return any(k in blob for k in ("news", "novosti", "press", "media", "blog", "type"))