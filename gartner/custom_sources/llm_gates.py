"""Точечные LLM-гейты: keep/drop, хаб/статья, chrome-заголовок, нефтегаз домена."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from gartner.custom_sources.article_extract import is_generic_title
from gartner.custom_sources.scoring import ARTICLE_QUERY_KEYS, looks_like_article_url, looks_like_hub_url, news_score
from gartner.custom_sources.theme import classify_theme_llm

KIND_PROMPT = """
Ты классификатор страниц нефтегазового сайта.
Верни ТОЛЬКО JSON: {"kind":"article|hub|junk","reason":"кратко"}
article — одна новость, пресс-релиз или аналитическая статья.
hub — список новостей, пресс-центр, архив, лента.
junk — контакты, вакансии, о компании, каталог, cookie, политика ПДн, пустая оболочка.
""".strip()

KEEP_PROMPT = """
Ты фильтр карточек для радара нефтегазовых технологий.
Верни ТОЛЬКО JSON: {"keep":true|false,"reason":"кратко"}
keep=true — реальная новость, пресс-релиз, отраслевая статья или аналитика с содержанием.
keep=false — навигация, «о компании», контакты, вакансии, политика ПДн, каталог без события,
заголовок из меню, битый бинарник, пустышка.
""".strip()

TITLE_PROMPT = """
Извлеки настоящий заголовок статьи без хрома сайта (меню, «Новости | Компания», язык RU|EN).
Верни ТОЛЬКО JSON: {"title":"..."}
Если заголовка нет, верни лучший осмысленный вариант из входа, не копируй меню.
""".strip()

INDEX_NAMES = {"index.php", "index.html", "index.htm", "index.aspx", "index"}
DOMAIN_OIL_TOKENS = ("neft", "gaz", "oil", "petro", "lukoil", "novatek")


@dataclass
class LlmBudget:
    kind_limit: int = 8
    title_limit: int = 10
    keep_limit: int = 24
    theme_limit: int = 1
    left: dict[str, int] = field(init=False)
    used: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.left = {
            "kind": self.kind_limit,
            "title": self.title_limit,
            "keep": self.keep_limit,
            "theme": self.theme_limit,
        }
        self.used = {
            "kind": 0,
            "title": 0,
            "keep": 0,
            "theme": 0,
            "drop": 0,
            "title_fixed": 0,
            "kind_changed": 0,
            "errors": 0,
        }

    def take(self, name: str) -> bool:
        if self.left.get(name, 0) <= 0:
            return False
        self.left[name] -= 1
        self.used[name] = self.used.get(name, 0) + 1
        return True

    def as_dict(self) -> dict[str, int]:
        return dict(self.used)


def llm_ready(llm: Any) -> bool:
    return bool(llm is not None and getattr(llm, "enabled", False))


def html_excerpt(html: str, limit: int = 2500) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    h1 = soup.h1.get_text(" ", strip=True) if soup.h1 else ""
    text = " ".join(soup.get_text(" ", strip=True).split())
    return f"{title}\n{h1}\n{text}"[:limit]


def _last_path(url: str) -> str:
    parts = [p for p in urlparse(url).path.split("/") if p]
    return parts[-1].lower() if parts else ""


def has_article_query(url: str) -> bool:
    qs = parse_qs(urlparse(url).query)
    keys = {k.lower() for k in qs}
    return bool(keys & {k.lower() for k in ARTICLE_QUERY_KEYS})


def is_ambiguous_kind(url: str, *, heuristic: str, articleish_n: int = 0) -> bool:
    """Спорный URL: эвристика хаб/статья конфликтует — только такие отдаём LLM."""
    if heuristic == "rss":
        return False
    article_u = looks_like_article_url(url)
    hub_u = looks_like_hub_url(url)
    last = _last_path(url)
    has_id = has_article_query(url)
    parts = [p for p in urlparse(url).path.split("/") if p]
    if has_id:
        return False
    if article_u and hub_u and (last in INDEX_NAMES or len(parts) <= 1):
        return True
    if article_u and articleish_n >= 4:
        return True
    if last in INDEX_NAMES and not has_id and heuristic == "article":
        return True
    if heuristic == "hub" and article_u and has_id:
        return True
    if heuristic == "other" and (article_u or news_score(url) > 0):
        return True
    if has_id and heuristic != "article":
        return True
    return False


def _json_call(llm: Any, prompt: str, payload: dict[str, Any], budget: LlmBudget) -> dict[str, Any] | None:
    try:
        try:
            raw = llm.json_call(prompt, payload, max_retries=2)
        except TypeError:
            raw = llm.json_call(prompt, payload)
        return raw if isinstance(raw, dict) else None
    except Exception:
        budget.used["errors"] = budget.used.get("errors", 0) + 1
        return None


def refine_theme_once(
    llm: Any,
    *,
    domain: str,
    url: str,
    html: str,
    keyword_theme: dict[str, Any],
    budget: LlmBudget,
) -> dict[str, Any]:
    """Нефтегаз — один вызов на домен, не на каждую ссылку."""
    if not llm_ready(llm) or not html:
        return keyword_theme
    hits = keyword_theme.get("hits")
    if keyword_theme.get("theme") == "oilgas" and isinstance(hits, int) and hits >= 3:
        return keyword_theme
    if not budget.take("theme"):
        return keyword_theme
    result = classify_theme_llm(llm, domain=domain, html=html, url=url)
    if not result:
        budget.used["errors"] = budget.used.get("errors", 0) + 1
        return keyword_theme
    host = (domain or "").lower()
    if not result.get("accepted") and any(tok in host for tok in DOMAIN_OIL_TOKENS):
        result = {
            **result,
            "theme": "oilgas",
            "accepted": True,
            "reason": (result.get("reason") or "") + "; домен похож на нефтегаз",
            "method": "llm+domain",
        }
    result["keyword_theme"] = keyword_theme.get("theme")
    return result


def classify_kind_llm(
    llm: Any,
    *,
    url: str,
    html: str,
    heuristic: str,
    articleish_n: int,
    budget: LlmBudget,
) -> str | None:
    if not llm_ready(llm) or not is_ambiguous_kind(url, heuristic=heuristic, articleish_n=articleish_n):
        return None
    if not budget.take("kind"):
        return None
    raw = _json_call(
        llm,
        KIND_PROMPT,
        {
            "url": url,
            "heuristic": heuristic,
            "articleish_links": articleish_n,
            "excerpt": html_excerpt(html),
        },
        budget,
    )
    if not raw:
        return None
    kind = str(raw.get("kind") or "").strip().lower()
    if kind == "junk":
        kind = "other"
    if kind not in {"article", "hub", "other"}:
        return None
    return kind


def polish_title_llm(
    llm: Any,
    *,
    title: str,
    text: str,
    url: str,
    budget: LlmBudget,
) -> str | None:
    if not llm_ready(llm) or not is_generic_title(title):
        return None
    if not budget.take("title"):
        return None
    raw = _json_call(
        llm,
        TITLE_PROMPT,
        {"url": url, "title": title[:300], "text": (text or "")[:900]},
        budget,
    )
    if not raw:
        return None
    new_title = " ".join(str(raw.get("title") or "").split())
    if len(new_title) < 12 or is_generic_title(new_title):
        return None
    return new_title[:240]


def judge_article_keep(
    llm: Any,
    *,
    url: str,
    title: str,
    text: str,
    budget: LlmBudget,
) -> bool | None:
    """True/False если LLM ответил; None — пропуск (нет LLM / бюджет / ошибка)."""
    if not llm_ready(llm):
        return None
    if not budget.take("keep"):
        return None
    raw = _json_call(
        llm,
        KEEP_PROMPT,
        {
            "url": url,
            "title": (title or "")[:300],
            "text_preview": (text or "")[:700],
        },
        budget,
    )
    if not raw or "keep" not in raw:
        return None
    keep = bool(raw.get("keep"))
    if not keep:
        budget.used["drop"] = budget.used.get("drop", 0) + 1
    return keep
