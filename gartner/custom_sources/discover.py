"""LLM: найти ленту новостей и составить JSON-правила (схема A)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from gartner.custom_sources.fetch import _is_js_cookie_challenge, fetch_html_safe
from gartner.custom_sources.engine import extract_article, extract_list_links, run_rules_engine
from gartner.custom_sources.feeds import discover_feeds
from gartner.custom_sources.theme import classify_theme, classify_theme_llm
from gartner.custom_sources.rules import ScrapeRules, domain_from_url, normalize_start_url, validate_rules_dict
from gartner.llm import LLMClient

DISCOVER_PROMPT = """
Ты — эксперт по HTML новостных сайтов российского ТЭК/ИТ.
По HTML предложи JSON-правила для BeautifulSoup (только CSS-селекторы).

Верни ТОЛЬКО один JSON-объект. Обязательные поля — НЕПУСТЫЕ СТРОКИ (никогда null):
{
  "list_url": "https://полный-url-ленты-новостей",
  "list": {
    "article_link_selector": "CSS селектор ссылок на статьи",
    "link_attr": "href",
    "pagination": {"next_selector": "", "max_pages": 3}
  },
  "article": {
    "title_selector": "h1",
    "date_selector": "time",
    "date_attr": "datetime",
    "text_selector": "article",
    "remove_selectors": ["script", "style", "noscript"]
  },
  "source_name": "domain.ru",
  "version": 1
}

Правила:
- не используй null; для опциональных селекторов пиши "" ;
- list_url из candidate_news_urls или очевидный /news ;
- селекторы должны встречаться в HTML;
- source_name = домен без www.
""".strip()

REPAIR_PROMPT = """
Правила скрейпинга не сработали. Исправь JSON той же схемы.
Обязательные строки (list_url, article_link_selector, title_selector, text_selector) НЕ могут быть null или пустыми.
Опциональные date_selector/date_attr/next_selector — пустая строка вместо null.
Верни ТОЛЬКО JSON.
""".strip()

LINK_SELECTOR_CANDIDATES = [
    "a.news-item",
    "a.news-card__link",
    "div.news a[href]",
    "article a[href]",
    ".news-list a[href]",
    ".list-news a[href]",
    "h2 a[href]",
    "h3 a[href]",
    "a[href*='/news/20']",
    "a[href*='/news/']",
    "a[href*='/novosti/']",
    "a[href*='/analytics/']",
    "a[href*='/article/']",
]

TITLE_SELECTORS = ["h1", "h1.title", "h1.entry-title", ".article-title", ".news-title", "article h1"]
TEXT_SELECTORS = [
    ".content-blocks",
    ".kind-common",
    "article",
    ".article-body",
    ".article__text",
    ".news-detail",
    ".content",
    ".entry-content",
    "div.text",
    "main",
    "[itemprop='articleBody']",
]
DATE_SELECTORS = ["time", ".date", ".news-date", ".article-date", "span.date"]

def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _trim_html(html: str, limit: int = 18000) -> str:
    text = html or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n<!-- truncated -->"


def _candidate_news_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    keywords = (
        "news",
        "novosti",
        "analytics",
        "analitic",
        "press",
        "media",
        "blog",
        "лента",
        "новост",
        "аналит",
    )
    found: list[str] = []
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "")
        label = (a.get_text(" ", strip=True) or "").lower()
        abs_url = urljoin(base_url, href)
        blob = f"{href} {label}".lower()
        if any(k in blob for k in keywords):
            found.append(abs_url)
    out: list[str] = []
    seen: set[str] = set()
    for u in found:
        if u not in seen:
            seen.add(u)
            out.append(u)
    # частые пути
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    for path in ("/news/", "/novosti/", "/analytics/", "/press/", "/media/"):
        out.append(urljoin(origin + "/", path.lstrip("/")))
    # unique again
    final: list[str] = []
    seen2: set[str] = set()
    for u in out:
        if u not in seen2:
            seen2.add(u)
            final.append(u)
    return final[:25]


def _clean_nulls(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, dict):
        return {str(k): _clean_nulls(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_nulls(v) for v in value if v is not None]
    return value


def _normalize_llm_rules(raw: dict[str, Any], *, start_url: str, candidates: list[str]) -> dict[str, Any]:
    data = _clean_nulls(raw if isinstance(raw, dict) else {})
    if not isinstance(data.get("list"), dict):
        data["list"] = {}
    if not isinstance(data.get("article"), dict):
        data["article"] = {}
    lst = data["list"]
    art = data["article"]
    if not isinstance(lst.get("pagination"), dict):
        lst["pagination"] = {}

    list_url = str(data.get("list_url") or "").strip()
    if not list_url:
        list_url = candidates[0] if candidates else start_url
    try:
        list_url = normalize_start_url(list_url)
    except ValueError:
        list_url = normalize_start_url(start_url)

    link_sel = str(lst.get("article_link_selector") or "").strip() or "a[href]"
    title_sel = str(art.get("title_selector") or "").strip() or "h1"
    text_sel = str(art.get("text_selector") or "").strip() or "article"
    date_sel = str(art.get("date_selector") or "").strip()
    date_attr = str(art.get("date_attr") or "").strip()
    next_sel = str(lst["pagination"].get("next_selector") or "").strip()
    strategy = str(lst["pagination"].get("strategy") or "").strip().lower()
    if not strategy:
        strategy = "next_link" if next_sel else "none"
    page_param = str(lst["pagination"].get("page_param") or "").strip() or None
    offset_param = str(lst["pagination"].get("offset_param") or "").strip() or None
    try:
        max_pages = int(lst["pagination"].get("max_pages") or 3)
    except (TypeError, ValueError):
        max_pages = 3
    max_pages = max(1, min(max_pages, 10))
    try:
        page_start = int(lst["pagination"].get("page_start") or 1)
    except (TypeError, ValueError):
        page_start = 1
    try:
        page_step = int(lst["pagination"].get("page_step") or 1)
    except (TypeError, ValueError):
        page_step = 1
    try:
        offset_step = int(lst["pagination"].get("offset_step") or 20)
    except (TypeError, ValueError):
        offset_step = 20

    remove = art.get("remove_selectors") or ["script", "style", "noscript"]
    if not isinstance(remove, list) or not remove:
        remove = ["script", "style", "noscript"]
    remove = [str(x) for x in remove if x]

    theme = str(data.get("theme") or "").strip() or None
    feeds = data.get("feeds") if isinstance(data.get("feeds"), list) else []
    protection = str(data.get("protection") or "").strip() or None

    return {
        "list_url": list_url,
        "list": {
            "article_link_selector": link_sel,
            "link_attr": str(lst.get("link_attr") or "href") or "href",
            "pagination": {
                "strategy": strategy,
                "next_selector": next_sel or None,
                "page_param": page_param,
                "page_start": page_start,
                "page_step": page_step,
                "offset_param": offset_param,
                "offset_step": offset_step,
                "load_more_selector": str(lst["pagination"].get("load_more_selector") or "").strip() or None,
                "max_pages": max_pages,
            },
        },
        "article": {
            "title_selector": title_sel,
            "date_selector": date_sel or None,
            "date_attr": date_attr or None,
            "text_selector": text_sel,
            "remove_selectors": remove,
        },
        "source_name": domain_from_url(start_url),
        "version": 1,
        "theme": theme,
        "feeds": [str(x) for x in feeds if x],
        "protection": protection,
    }


def _score_list_selector(html: str, selector: str, base_url: str) -> int:
    try:
        rules = validate_rules_dict(
            {
                "list_url": base_url,
                "list": {
                    "article_link_selector": selector,
                    "link_attr": "href",
                    "pagination": {"next_selector": None, "max_pages": 1, "strategy": "none"},
                },
                "article": {
                    "title_selector": "h1",
                    "date_selector": None,
                    "date_attr": None,
                    "text_selector": "article",
                    "remove_selectors": ["script", "style"],
                },
                "source_name": "tmp",
                "version": 1,
            }
        )
        return len(extract_list_links(html, rules, base_url))
    except Exception:
        return 0


def heuristic_rules(start_url: str, home_html: str, candidates: list[str]) -> ScrapeRules | None:
    """Подбор list_url + селекторов без LLM, с проверкой числа ссылок."""
    domain = domain_from_url(start_url)
    pages: list[tuple[str, str]] = []
    if home_html and not _is_js_cookie_challenge(home_html):
        pages.append((normalize_start_url(start_url), home_html))
    for cand in candidates[:8]:
        html, err = fetch_html_safe(cand)
        if err or not html or _is_js_cookie_challenge(html):
            continue
        pages.append((cand, html))

    best: tuple[int, str, str, str] | None = None  # score, list_url, html, selector
    for list_url, html in pages:
        for sel in LINK_SELECTOR_CANDIDATES:
            score = _score_list_selector(html, sel, list_url)
            if score < 2:
                continue
            # при близком score предпочитаем URL ленты /news|/novosti
            path_bonus = 1 if any(x in list_url.lower() for x in ("/news", "/novosti", "/analytics")) else 0
            ranked = score * 10 + path_bonus
            if best is None:
                best = (score, list_url, html, sel)
                continue
            prev = best[0] * 10 + (
                1 if any(x in best[1].lower() for x in ("/news", "/novosti", "/analytics")) else 0
            )
            if ranked > prev:
                best = (score, list_url, html, sel)

    if not best:
        return None

    _, list_url, list_html, link_sel = best
    guessed = _guess_pagination(list_html, list_url)
    raw = {
        "list_url": list_url,
        "list": {
            "article_link_selector": link_sel,
            "link_attr": "href",
            "pagination": {
                "next_selector": guessed.get("next_selector"),
                "max_pages": _safe_int(guessed.get("max_pages"), 3),
                "strategy": guessed.get("strategy") or "none",
                "page_param": guessed.get("page_param"),
                "page_start": _safe_int(guessed.get("page_start"), 1),
                "offset_param": guessed.get("offset_param"),
                "offset_step": _safe_int(guessed.get("offset_step"), 20),
            },
        },
        "article": {
            "title_selector": TITLE_SELECTORS[0],
            "date_selector": DATE_SELECTORS[0],
            "date_attr": "datetime",
            "text_selector": TEXT_SELECTORS[0],
            "remove_selectors": ["script", "style", "noscript"],
        },
        "source_name": domain,
        "version": 1,
    }
    try:
        list_rules = validate_rules_dict(raw)
    except Exception:
        return None
    links = extract_list_links(list_html, list_rules, list_url)
    article_pages: list[tuple[str, str]] = []
    for link in links[:2]:
        html, err = fetch_html_safe(link)
        if err or not html or _is_js_cookie_challenge(html):
            continue
        article_pages.append((link, html))
    if not article_pages:
        return None

    for title_sel in TITLE_SELECTORS:
        for text_sel in TEXT_SELECTORS:
            for date_sel in DATE_SELECTORS + [None]:
                trial = dict(raw)
                trial["article"] = {
                    **raw["article"],
                    "title_selector": title_sel,
                    "text_selector": text_sel,
                    "date_selector": date_sel,
                    "date_attr": "datetime" if date_sel == "time" else None,
                }
                try:
                    rules = validate_rules_dict(trial)
                except Exception:
                    continue
                if all(extract_article(html, rules, link) for link, html in article_pages):
                    return rules
    return None


def discover_rules(start_url: str, llm: LLMClient) -> ScrapeRules:
    if not llm.enabled:
        raise RuntimeError("LLM выключен: для добавления источника нужен API_KEY (Astra)")

    url = normalize_start_url(start_url)
    html, err = fetch_html_safe(url)
    if err or not html:
        raise RuntimeError(f"Не удалось загрузить URL: {err}")
    if _is_js_cookie_challenge(html):
        # главная закрыта антиботом — всё равно пробуем типовые ленты /news
        candidates = _candidate_news_links("", url)
        for cand in list(candidates):
            cand_html, cand_err = fetch_html_safe(cand)
            if not cand_err and cand_html and not _is_js_cookie_challenge(cand_html):
                html = cand_html
                break
        else:
            raise RuntimeError(
                "Сайт отдаёт anti-bot challenge без HTML статей. "
                "Попробуйте URL ленты новостей напрямую (например /news)."
            )
    else:
        candidates = _candidate_news_links(html, url)
    payload = {
        "start_url": url,
        "domain": domain_from_url(url),
        "candidate_news_urls": candidates,
        "html": _trim_html(html),
        "instruction": "Все обязательные поля — непустые строки, без null.",
    }

    last_error: Exception | None = None
    for _ in range(2):
        try:
            raw = llm.json_call(DISCOVER_PROMPT, payload)
            normalized = _normalize_llm_rules(raw, start_url=url, candidates=candidates)
            rules = validate_rules_dict(normalized)
            rules.source_name = domain_from_url(url)
            return rules
        except Exception as exc:
            last_error = exc
            payload["previous_error"] = str(exc)
            payload["fix_reminder"] = "Нельзя возвращать null в list_url/селекторах"

    # heuristic fallback
    heur = heuristic_rules(url, html, candidates)
    if heur:
        return heur
    raise RuntimeError(f"Модель вернула неполные правила: {last_error}")


def repair_rules(rules: ScrapeRules, error: str, llm: LLMClient) -> ScrapeRules:
    if not llm.enabled:
        raise RuntimeError("LLM выключен: нельзя починить правила")
    html, fetch_err = fetch_html_safe(rules.list_url)
    payload = {
        "previous_rules": rules.model_dump(),
        "error": error,
        "fetch_error": fetch_err,
        "html": _trim_html(html or ""),
        "domain": rules.source_name,
    }
    raw = llm.json_call(REPAIR_PROMPT, payload)
    normalized = _normalize_llm_rules(
        raw,
        start_url=rules.list_url or f"https://{rules.source_name}/",
        candidates=[rules.list_url] if rules.list_url else [],
    )
    fixed = validate_rules_dict(normalized)
    fixed.source_name = rules.source_name or domain_from_url(rules.list_url)
    return fixed


def _guess_protection(home_html: str | None, home_error: str | None) -> str:
    if home_html and _is_js_cookie_challenge(home_html):
        return "js_cookie"
    err = (home_error or "").lower()
    if "ssl" in err or "certificate" in err:
        return "tls_odd"
    if "timeout" in err:
        return "timeout"
    if home_error:
        return "unknown"
    return "none"


def _guess_pagination(html: str, list_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html or "", "html.parser")
    for sel in (
        "a.next",
        "a.next-page",
        "a[rel='next']",
        ".pagination a.next",
        "li.next a",
        "a.pager-next",
    ):
        node = soup.select_one(sel)
        if node and node.get("href"):
            return {"strategy": "next_link", "next_selector": sel, "max_pages": 3}
    text_hits = soup.find_all("a", href=True)
    for a in text_hits:
        label = (a.get_text(" ", strip=True) or "").lower()
        href = str(a.get("href") or "")
        if label in {"далее", "следующая", ">", "»", "next"} and href:
            return {"strategy": "next_link", "next_selector": "a[rel='next']" if a.get("rel") else "a.next-page", "max_pages": 3}
    parsed = urlparse(list_url)
    qs = parsed.query.lower()
    if "page=" in qs or "pagen" in qs:
        param = "page"
        if "pagen_1=" in qs:
            param = "PAGEN_1"
        return {"strategy": "page_query", "page_param": param, "page_start": 1, "max_pages": 3}
    if "offset=" in qs:
        return {"strategy": "offset", "offset_param": "offset", "offset_step": 20, "max_pages": 3}
    for a in text_hits:
        href = str(a.get("href") or "").lower()
        if "page=" in href or "pagen" in href:
            return {"strategy": "page_query", "page_param": "page", "page_start": 1, "max_pages": 3}
    return {"strategy": "none", "max_pages": 1}


def inspect_domain(
    start_url: str,
    llm: LLMClient | None = None,
    *,
    probe_feeds: bool = True,
) -> dict[str, Any]:
    """Домен → ленты + тематика (без записи в БД)."""
    url = normalize_start_url(start_url)
    if probe_feeds:
        feed_info = discover_feeds(url)
        home_html, home_err = fetch_html_safe(url)
        if not home_html:
            home_html, home_err = None, feed_info.get("home_error")
    else:
        home_html, home_err = fetch_html_safe(url)
        feed_info = {
            "start_url": url,
            "domain": domain_from_url(url),
            "home_ok": bool(home_html) and not home_err,
            "home_error": home_err,
            "home_challenge": _is_js_cookie_challenge(home_html or "") if home_html else False,
            "candidates": [],
            "feeds": [],
        }
        if home_html:
            from gartner.custom_sources.feeds import extract_feed_candidates

            cands = extract_feed_candidates(home_html, url)[:8]
            feed_info["candidates"] = [{"url": c, "ok": None, "score": None} for c in cands]
    if home_html:
        theme = classify_theme(home_html, url=url, extra_text=url)
        if llm:
            llm_theme = classify_theme_llm(llm, domain=domain_from_url(url), html=home_html, url=url)
            if llm_theme:
                theme = llm_theme
    else:
        theme = {
            "theme": "unknown",
            "hits": 0,
            "accepted": False,
            "reason": f"страница не загрузилась: {home_err or feed_info.get('home_error')}",
            "method": "fetch_fail",
        }
    protection = _guess_protection(home_html, feed_info.get("home_error") or home_err)
    return {
        "start_url": url,
        "domain": domain_from_url(url),
        "theme": theme,
        "protection": protection,
        "feeds": feed_info.get("feeds") or [],
        "candidates": feed_info.get("candidates") or [],
        "home_ok": feed_info.get("home_ok"),
        "home_error": feed_info.get("home_error") or home_err,
        "home_challenge": feed_info.get("home_challenge"),
    }


def discover_and_validate(
    start_url: str,
    llm: LLMClient,
    *,
    max_articles_probe: int = 3,
    require_oilgas: bool = True,
) -> tuple[ScrapeRules, dict[str, Any]]:
    """Ленты → тематика → правила → dry-run → repair → heuristic."""
    url = normalize_start_url(start_url)
    inspection = inspect_domain(url, llm=llm)
    theme = inspection["theme"]
    if require_oilgas and not theme.get("accepted"):
        if theme.get("theme") == "unknown":
            raise RuntimeError(
                "Не удалось загрузить сайт, тематику проверить нельзя. "
                f"{theme.get('reason') or ''}"
            )
        raise RuntimeError(
            "Сайт отклонён по тематике (нет нефтегаза). "
            f"{theme.get('reason') or theme}"
        )

    feeds = [f["url"] for f in inspection.get("feeds") or [] if f.get("url")]
    preferred = feeds[0] if feeds else url
    if not getattr(llm, "enabled", False):
        home_html, _ = fetch_html_safe(preferred)
        cand_urls = feeds[:8] or _candidate_news_links(home_html or "", preferred)
        heur = heuristic_rules(preferred, home_html or "", cand_urls)
        if not heur:
            raise RuntimeError("LLM выключен: для добавления источника нужен API_KEY (Astra)")
        heur.theme = theme.get("theme")
        heur.feeds = feeds[:8]
        heur.protection = inspection.get("protection")
        result = run_rules_engine(heur, max_articles=max_articles_probe)
        if not result.ok:
            raise RuntimeError(
                "LLM выключен, эвристика нашла ленту, но статьи не извлеклись. "
                f"{result.error or ''}"
            )
        return heur, {
            "probe_ok": True,
            "articles": len(result.articles),
            "links_found": result.links_found,
            "pages_fetched": result.pages_fetched,
            "list_url": result.list_url,
            "repaired": False,
            "method": "heuristic_no_llm",
            "theme": theme,
            "feeds": feeds[:8],
            "protection": inspection.get("protection"),
            "pagination": heur.list.pagination.strategy,
        }

    rules = discover_rules(preferred, llm)
    rules.theme = theme.get("theme")
    rules.feeds = feeds[:8]
    rules.protection = inspection.get("protection")

    # если LLM не задал пагинацию — эвристика по HTML ленты
    list_html, _ = fetch_html_safe(rules.list_url)
    guessed = _guess_pagination(list_html or "", rules.list_url)
    if rules.list.pagination.strategy in {"none", ""} and guessed.get("strategy") not in {None, "none"}:
        pag = rules.list.pagination.model_dump()
        pag.update({k: v for k, v in guessed.items() if v is not None})
        rules.list.pagination = type(rules.list.pagination).model_validate(pag)

    result = run_rules_engine(rules, max_articles=max_articles_probe)
    if result.ok:
        return rules, {
            "probe_ok": True,
            "articles": len(result.articles),
            "links_found": result.links_found,
            "pages_fetched": result.pages_fetched,
            "list_url": result.list_url,
            "repaired": False,
            "method": "llm",
            "theme": theme,
            "feeds": feeds[:8],
            "protection": inspection.get("protection"),
            "pagination": rules.list.pagination.strategy,
        }

    try:
        fixed = repair_rules(rules, result.error or "unknown", llm)
        fixed.theme = rules.theme
        fixed.feeds = rules.feeds
        fixed.protection = rules.protection
        result2 = run_rules_engine(fixed, max_articles=max_articles_probe)
        if result2.ok:
            return fixed, {
                "probe_ok": True,
                "articles": len(result2.articles),
                "links_found": result2.links_found,
                "pages_fetched": result2.pages_fetched,
                "list_url": result2.list_url,
                "repaired": True,
                "first_error": result.error,
                "method": "llm_repair",
                "theme": theme,
                "feeds": feeds[:8],
                "protection": inspection.get("protection"),
                "pagination": fixed.list.pagination.strategy,
            }
        last_err = result2.error or result.error
    except Exception as exc:
        last_err = f"{result.error}; repair failed: {exc}"

    home_html, _ = fetch_html_safe(preferred)
    heur = heuristic_rules(preferred, home_html or "", _candidate_news_links(home_html or "", preferred))
    if heur:
        heur.theme = rules.theme
        heur.feeds = rules.feeds
        heur.protection = rules.protection
        result3 = run_rules_engine(heur, max_articles=max_articles_probe)
        if result3.ok:
            return heur, {
                "probe_ok": True,
                "articles": len(result3.articles),
                "links_found": result3.links_found,
                "pages_fetched": result3.pages_fetched,
                "list_url": result3.list_url,
                "repaired": True,
                "first_error": last_err,
                "method": "heuristic",
                "theme": theme,
                "feeds": feeds[:8],
                "protection": inspection.get("protection"),
                "pagination": heur.list.pagination.strategy,
            }

    raise RuntimeError(
        "Не удалось составить рабочие правила для сайта. "
        f"Детали: {last_err}"
    )
