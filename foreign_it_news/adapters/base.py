"""Общие типы и хелперы для ручных адаптеров источников."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from gartner.custom_sources.article_extract import extract_article_page
from gartner.custom_sources.engine import ArticleRecord
from gartner.custom_sources.fetch import fetch_html_safe

MIN_DATE = date(2026, 1, 1)

# широкий словарь для пула (1 совпадения достаточно)
IT_HINTS_WIDE = re.compile(
    r"("
    r"\bdigital(?:i[sz]e|i[sz]ation|[- ]twin|[- ]oilfield)?\b|"
    r"\bartificial intelligence\b|\bmachine learning\b|\bdeep learning\b|"
    r"\bcyber(?:security|attack|threat)?\b|\bautomation\b|\bautonomous\b|"
    r"\brobot(?:ics|ic)?\b|\bdrone\b|\buav\b|\biot\b|\biiot\b|\bscada\b|\bmes\b|"
    r"\bdata(?:\s|-)?(?:platform|center|centre|science|analytics|driven)\b|"
    r"\bdatacent(?:er|re)s?\b|\banalytics\b|\bremote monitoring\b|"
    r"\bindustrial software\b|\bsoftware\b|\bplatform\b|\bcloud\b|"
    r"\bsupercomput(?:er|ing)?\b|\bhpc\b|\bsensor(?:s)?\b|"
    r"\bsmart (?:field|well|city|cities|rig)\b|"
    r"\b4ir\b|\bindustry 4\.0\b|\bdigital twin\b|\bopen process automation\b|"
    r"\bopa\b|\bagentic\b|\bgenerative ai\b|\bgenai\b|\bllm\b|"
    r"\bit infrastructure\b|\bit tender\b|\bcybersec\b|"
    r"(?<![a-z])ai(?![a-z])(?![^\n]{0,40}nominat)"
    r")",
    re.I,
)

# более строгий набор (для корпоративных адаптеров / старого поведения)
IT_HINTS = re.compile(
    r"("
    r"\bdigital(?:i[sz]ation|[- ]twin| oilfield)?\b|\bartificial intelligence\b|"
    r"\bmachine learning\b|\bdeep learning\b|\bcyber(?:security)?\b|"
    r"\bautomation\b|\bautonomous (?:drilling|operations|vehicles?|systems?)\b|"
    r"\brobot(?:ics)?\b|\bdrone\b|\buav\b|\biot\b|\biiot\b|\bscada\b|"
    r"\bdata platform\b|\bremote monitoring\b|\bindustrial software\b|"
    r"\bsupercomputing\b|\bhigh[- ]performance computing\b|\bhpc\b|"
    r"\bsmart (?:field|well|city|cities)\b|\bcloud computing\b|"
    r"\bdata centers?\b|\bdatacenters?\b|\bsoftware platform\b|"
    r"(?<![a-z])ai(?![a-z])(?![^\n]{0,40}nominat)"
    r")",
    re.I,
)

# шум в title — не зовём даже LLM
NOISE_TITLE = re.compile(
    r"(dividend|earnings|quarterly results|buyback|treasury shares|conference call|"
    r"board of directors|appointment|hybrid bond|fixed rate bond|credit facility|"
    r"form 20-f|aviso de pauta|supplier recognition|revolving credit|"
    r"reports? (?:first|second|third|fourth) quarter|"
    r"stock (?:to buy|picks?)|non-ai stocks|ghost in the shell|"
    r"powershell|java4shell|weekly recap|"
    r"ai prompts?|expert witness|climate lawsuit|climate litigation|"
    r"google ai (?:update|mode|mistakes)|donovan shell feud|"
    r"money matters: shell oil|drone attack|missile|houthis)",
    re.I,
)


@dataclass
class ListItem:
    url: str
    title: str = ""
    date_hint: str = ""


@dataclass
class AdapterResult:
    company_id: str
    company: str
    listed: int = 0
    fetched: int = 0
    from_2026: int = 0
    kept_it: int = 0
    dropped_date: int = 0
    dropped_keyword: int = 0
    dropped_it: int = 0
    extract_fail: int = 0
    errors: list[str] = field(default_factory=list)
    articles: list[dict] = field(default_factory=list)


def log_fn(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[foreign-it-adapter {ts}] {msg}", flush=True)


def fetch_html(url: str, *, timeout: float = 28.0) -> tuple[str | None, str | None]:
    return fetch_html_safe(url, timeout=timeout)


def parse_date(value: str) -> date | None:
    raw = (value or "").strip()
    if not raw:
        return None
    head = raw.replace("Z", "")
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%Y/%m/%d",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%d %b %Y",
    ):
        chunk = head[:19] if ("T" in fmt or " " in fmt) and "B" not in fmt and "b" not in fmt else head
        if "%B" in fmt or "%b" in fmt:
            chunk = head
        elif "T" in fmt or (" " in fmt and "%H" in fmt):
            chunk = head[:19]
        else:
            chunk = head[:10]
        try:
            return datetime.strptime(chunk, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def sitemap_locs(xml: str) -> list[str]:
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml or "", flags=re.I)


def extract_hrefs(html: str, base: str, pattern: str) -> list[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    rx = re.compile(pattern, re.I)
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        full = urljoin(base, a["href"]).split("#")[0]
        if rx.search(full):
            out.append(full)
    for m in re.finditer(pattern, html or "", flags=re.I):
        candidate = m.group(1) if m.lastindex else m.group(0)
        if candidate.startswith("http"):
            out.append(candidate.split("#")[0])
        elif candidate.startswith("/"):
            out.append(urljoin(base, candidate).split("#")[0])
    return list(dict.fromkeys(out))


def same_host(url: str, host: str) -> bool:
    h = (urlparse(url).hostname or "").lower().lstrip("www.")
    return h == host.lower().lstrip("www.")


def has_it_hint(title: str, text: str) -> bool:
    """Строже: title ИЛИ ≥2 хита в теле (корпоративные адаптеры)."""
    title = title or ""
    body = (text or "")[:1800]
    if IT_HINTS.search(title):
        return True
    return len(IT_HINTS.findall(body)) >= 2


def has_it_hint_wide(title: str, text: str) -> bool:
    """Шире для trade-press пула: 1 хит в title или body."""
    title = title or ""
    body = (text or "")[:2500]
    if IT_HINTS_WIDE.search(_headline_part(title)):
        return True
    if IT_HINTS_WIDE.search(title):
        return True
    return bool(IT_HINTS_WIDE.search(body))


def _headline_part(title: str) -> str:
    t = (title or "").strip()
    if " - " in t:
        return t.rsplit(" - ", 1)[0]
    return t


def is_noise_title(title: str) -> bool:
    return bool(NOISE_TITLE.search(title or ""))


def record_to_dict(rec: ArticleRecord, *, company: str, company_id: str, it_gate: str, reason: str = "") -> dict:
    return {
        "company_id": company_id,
        "company": company,
        "title": rec.title,
        "text": rec.text,
        "datatime": rec.datatime,
        "source": rec.source,
        "link": rec.link,
        "it_gate": it_gate,
        "it_reason": reason,
        "adapter": True,
    }


AdapterListFn = Callable[[], list[ListItem]]


def run_adapter(
    *,
    company_id: str,
    company: str,
    list_items: AdapterListFn,
    max_articles: int,
    skip_it_gate: bool,
    judge_it: Callable[[ArticleRecord], tuple[bool | None, str]],
    log: Callable[[str], None] = log_fn,
) -> AdapterResult:
    result = AdapterResult(company_id=company_id, company=company)
    try:
        items = list_items()
    except Exception as exc:
        result.errors.append(f"list failed: {exc}")
        log(f"  ✕ list failed: {exc}")
        return result

    # unique by url
    seen: set[str] = set()
    uniq: list[ListItem] = []
    for it in items:
        u = (it.url or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        uniq.append(it)
    result.listed = len(uniq)
    log(f"  listed={result.listed}, fetch up to {max_articles}")

    for idx, item in enumerate(uniq[:max_articles], 1):
        total_cap = min(len(uniq), max_articles)
        if idx == 1 or idx % 5 == 0 or idx == total_cap:
            log(
                f"  … {idx}/{total_cap} "
                f"kept={result.kept_it} drop_date={result.dropped_date} "
                f"drop_kw={result.dropped_keyword} drop_it={result.dropped_it}"
            )
        t0 = datetime.now()
        html, err = fetch_html(item.url)
        dt = (datetime.now() - t0).total_seconds()
        if dt >= 8.0 or err:
            log(f"  fetch {idx} slow/err {dt:.1f}s err={err} url={item.url[:100]}")
        if not html:
            result.extract_fail += 1
            if err:
                result.errors.append(f"{item.url}: {err[:120]}")
            continue
        rec = extract_article_page(html, item.url, source_name=company_id)
        if not rec:
            result.extract_fail += 1
            continue
        result.fetched += 1
        if item.title and (not rec.title or len(rec.title) < 12):
            rec.title = item.title[:500]
        if item.date_hint and not rec.datatime:
            rec.datatime = item.date_hint

        d = parse_date(rec.datatime)
        if d is None or d < MIN_DATE:
            result.dropped_date += 1
            continue
        result.from_2026 += 1

        if is_noise_title(rec.title):
            result.dropped_keyword += 1
            continue
        # широкий ИТ-фильтр (п.1): 1 маркер в title/text
        if not has_it_hint_wide(rec.title, rec.text):
            result.dropped_keyword += 1
            continue

        log(f"  IT-hint → LLM: {(rec.title or '')[:80]}")
        if skip_it_gate:
            result.articles.append(
                record_to_dict(rec, company=company, company_id=company_id, it_gate="disabled")
            )
            result.kept_it += 1
            continue

        decision, reason = judge_it(rec)
        log(f"  IT-gate decision={decision} reason={reason[:120]}")
        if decision is not True:
            result.dropped_it += 1
            continue
        result.articles.append(
            record_to_dict(rec, company=company, company_id=company_id, it_gate="keep", reason=reason)
        )
        result.kept_it += 1

    log(
        f"  ✓ {company_id}: listed={result.listed} fetched={result.fetched} "
        f"from2026={result.from_2026} kept_it={result.kept_it}"
    )
    return result
