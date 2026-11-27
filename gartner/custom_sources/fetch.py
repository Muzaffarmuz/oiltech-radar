"""HTTP-загрузка HTML для custom sources (в т.ч. обход JS-cookie challenge)."""

from __future__ import annotations

import time
from urllib.parse import quote, urlparse

import requests

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

# Per-host solved challenge tokens (process lifetime).
_CHALLENGE_BY_HOST: dict[str, dict[str, str]] = {}


def _is_js_cookie_challenge(html: str) -> bool:
    if not html:
        return False
    if "get_jhash" in html and "__js_p_" in html:
        return True
    if 'name="robots" content="noindex, noarchive"' in html and "gorizontal-vertikal" in html:
        return True
    return False


def _compute_jhash(code: int) -> int:
    """Порт get_jhash() из challenge-скрипта (QRATOR-подобный)."""
    x = 123456789
    k = 0
    for i in range(1677696):
        x = ((x + code) ^ (x + (x % 3) + (x % 17) + code) ^ i) % 16776960
        if x % 117 == 0:
            k = (k + 1) % 1111
    return k


def _fixed_encode_ua(ua: str) -> str:
    return (
        quote(ua, safe="")
        .replace("!", "%21")
        .replace("'", "%27")
        .replace("(", "%28")
        .replace(")", "%29")
        .replace("*", "%2A")
    )


def _host_key(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.hostname or "").lower().lstrip("www.")


def _cookie_header(tokens: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in tokens.items() if v)


def _solve_from_js_p(js_p: str) -> dict[str, str] | None:
    """Разобрать __js_p_ cookie. Бинарный/битый challenge → None (не бросаем)."""
    raw = str(js_p or "").strip()
    if not raw or len(raw) > 200 or any(ord(ch) < 32 for ch in raw if ch not in "\t"):
        return None
    parts: list[int] = []
    for chunk in raw.split(","):
        piece = chunk.strip()
        if not piece.isdigit() and not (piece.startswith("-") and piece[1:].isdigit()):
            return None
        try:
            parts.append(int(piece))
        except ValueError:
            return None
    if not parts:
        return None
    return {
        "__js_p_": raw,
        "__jhash_": str(_compute_jhash(parts[0])),
        "__jua_": _fixed_encode_ua(DEFAULT_UA),
    }


def fetch_html(url: str, *, timeout: float = 25.0, verify_tls: bool = True) -> str:
    host = _host_key(url)
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    known = _CHALLENGE_BY_HOST.get(host)
    request_kwargs: dict = {
        "timeout": timeout,
        "allow_redirects": True,
        "verify": verify_tls,
    }
    if known:
        request_kwargs["headers"] = {"Cookie": _cookie_header(known)}
        request_kwargs["cookies"] = dict(known)

    response = session.get(url, **request_kwargs)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    html = response.text

    if not _is_js_cookie_challenge(html):
        return html

    js_p = session.cookies.get("__js_p_") or (known or {}).get("__js_p_")
    if not js_p:
        # challenge HTML без cookie — дальше нечего решать
        return html

    tokens = _solve_from_js_p(js_p)
    if not tokens:
        return html

    _CHALLENGE_BY_HOST[host] = tokens
    html2 = html
    for attempt in range(3):
        # в браузере challenge ждёт ~1s перед reload
        time.sleep(1.05 if attempt == 0 else 0.35)
        response2 = session.get(
            url,
            headers={"Cookie": _cookie_header(tokens)},
            cookies=dict(tokens),
            timeout=timeout,
            allow_redirects=True,
            verify=verify_tls,
        )
        response2.raise_for_status()
        response2.encoding = response2.apparent_encoding or response2.encoding or "utf-8"
        html2 = response2.text
        if not _is_js_cookie_challenge(html2):
            return html2
        # новый __js_p_ на повторном challenge
        fresh = session.cookies.get("__js_p_") or response2.cookies.get("__js_p_")
        if fresh and fresh != tokens.get("__js_p_"):
            solved = _solve_from_js_p(fresh)
            if solved:
                tokens = solved
                _CHALLENGE_BY_HOST[host] = tokens
    return html2


def fetch_html_safe(url: str, *, timeout: float = 28.0) -> tuple[str | None, str | None]:
    """Скачать HTML. При TLS/timeout — повтор с verify=False и тем же таймаутом.

    В запасном режиме Firecrawl страницы сначала берутся через него.
    """
    from gartner.custom_sources import firecrawl

    if firecrawl.firecrawl_active() and not firecrawl.is_machine_url(url):
        html, _err = firecrawl.fetch_html(url)
        if html:
            return html, None
    errors: list[str] = []
    for verify in (True, False):
        try:
            return fetch_html(url, timeout=timeout, verify_tls=verify), None
        except Exception as exc:
            errors.append(f"verify_tls={verify}: {type(exc).__name__}: {exc}")
            continue
    return None, " | ".join(errors)


def reset_fetch_sessions() -> None:
    """Для тестов."""
    _CHALLENGE_BY_HOST.clear()
