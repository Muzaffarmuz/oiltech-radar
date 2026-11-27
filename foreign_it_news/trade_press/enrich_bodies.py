"""Дотянуть тела статей для out_trade (Google News → publisher → text).

Стратегия (быстрая):
  1) googlenewsdecoder — резолв Google News → URL издателя (без браузера)
  2) параллельный HTTP + trafilatura
  3) publisher URL guess (как раньше)
  4) опционально Playwright только для остатка (--playwright)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gartner.custom_sources.article_extract import extract_article_page  # noqa: E402
from gartner.custom_sources.fetch import fetch_html_safe  # noqa: E402

from foreign_it_news.scrape_trade_press import _headline_only  # noqa: E402
from foreign_it_news.trade_press.rss_parse import normalize_published  # noqa: E402

SOURCE_DOMAIN = {
    "world oil": "worldoil.com",
    "offshore energy": "offshore-energy.biz",
    "offshore engineer": "oedigital.com",
    "offshore engineer magazine": "oedigital.com",
    "hart energy": "hartenergy.com",
    "rigzone": "rigzone.com",
    "drilling contractor": "drillingcontractor.org",
    "jpt homepage": "jpt.spe.org",
    "jpt": "jpt.spe.org",
    "oil & gas middle east": "oilandgasmiddleeast.com",
    "energy digital magazine": "energydigital.com",
    "energy digital": "energydigital.com",
    "upstream online": "upstreamonline.com",
    "bnamericas": "bnamericas.com",
    "slb": "slb.com",
    "computer weekly": "computerweekly.com",
    "offshore magazine": "offshore-mag.com",
    "s&p global": "spglobal.com",
    "equinor": "equinor.com",
    "totalenergies.com": "totalenergies.com",
    "klover.ai": "klover.ai",
    "brazil energy insight": "brazilenergyinsight.com",
    "oil review middle east": "oilreviewmiddleeast.com",
    "marine technology news": "marinetechnologynews.com",
    "unite.ai": "unite.ai",
    "egypt oil & gas": "egyptoil-gas.com",
    "marine news magazine": "marinelink.com",
}


def log(msg: str) -> None:
    print(f"[enrich {datetime.now():%H:%M:%S}] {msg}", flush=True)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:120]


def _bad_body(text: str) -> bool:
    t = (text or "").strip().lower()
    if len(t) < 220:
        return True
    return any(
        b in t[:350]
        for b in (
            "access denied",
            "permission to access",
            "unusual traffic",
            "about this page",
            "captcha",
            "enable javascript",
            "400. that’s an error",
        )
    )


def _source(title: str, row: dict) -> str:
    if " - " in (title or ""):
        return title.rsplit(" - ", 1)[-1].strip().lower()
    return (row.get("source") or "").strip().lower()


def candidate_urls(row: dict) -> list[str]:
    title = row.get("title") or ""
    head = _headline_only(title)
    source = _source(title, row)
    domain = SOURCE_DOMAIN.get(source)
    if not domain:
        for key, dom in SOURCE_DOMAIN.items():
            if key in source:
                domain = dom
                break
    out: list[str] = []
    for key in ("resolved_link", "link"):
        u = row.get(key) or ""
        if u.startswith("http") and "news.google.com" not in u and "consent.google" not in u and "sorry" not in u:
            out.append(u)
    if not domain:
        return list(dict.fromkeys(out))

    slug = _slug(head)
    dt = normalize_published(row.get("datatime") or "")
    if domain == "worldoil.com" and re.match(r"\d{4}-\d{2}-\d{2}", dt or ""):
        base = date.fromisoformat(dt[:10])
        for delta in range(0, 5):
            for sign in ((0,) if delta == 0 else (-1, 1)):
                day = base + timedelta(days=sign * delta)
                for mm, dd in ((str(day.month), str(day.day)), (f"{day.month:02d}", f"{day.day:02d}")):
                    out += [
                        f"https://worldoil.com/news/{day.year}/{mm}/{dd}/{slug}/",
                        f"https://www.worldoil.com/news/{day.year}/{mm}/{dd}/{slug}/",
                    ]
    if domain == "offshore-energy.biz":
        out += [f"https://www.offshore-energy.biz/{slug}/"]
        if re.match(r"\d{4}-\d{2}-\d{2}", dt or ""):
            y, m, d = dt[:4], dt[5:7], dt[8:10]
            out.append(f"https://www.offshore-energy.biz/{y}/{m}/{d}/{slug}/")
    if domain == "oedigital.com":
        out.append(f"https://www.oedigital.com/news/{slug}")
    if domain == "hartenergy.com":
        out += [f"https://www.hartenergy.com/exclusives/{slug}", f"https://www.hartenergy.com/news/{slug}"]
    if domain == "slb.com":
        out.append(
            "https://www.slb.com/resource-library/case-study-with-navigation/di/"
            + (dt[:4] + "/" if dt else "")
            + slug
        )
    if domain == "energydigital.com":
        out.append(f"https://energydigital.com/articles/{slug}")
    if domain == "rigzone.com":
        out.append(f"https://www.rigzone.com/news/{slug}")
    if domain == "drillingcontractor.org":
        out.append(f"https://www.drillingcontractor.org/{slug}/")
    if domain == "equinor.com":
        out.append(f"https://www.equinor.com/news/{slug}")
    if domain == "totalenergies.com":
        out.append(f"https://totalenergies.com/news/{slug}")
    return list(dict.fromkeys([u for u in out if u]))


def extract_from_url(url: str) -> dict | None:
    html, _ = fetch_html_safe(url, timeout=28.0)
    if not html:
        return None
    rec = extract_article_page(html, url, source_name="trade")
    if not rec or _bad_body(rec.text):
        return None
    return {"url": url, "title": rec.title, "text": rec.text, "datatime": rec.datatime or ""}


def apply_extract(row: dict, got: dict, *, method: str, google_link: str | None = None) -> None:
    if google_link and "news.google.com" in google_link:
        row["resolved_from_google"] = google_link
    row["link"] = got["url"]
    if got.get("title"):
        row["title"] = got["title"]
    row["text"] = got["text"]
    if got.get("datatime"):
        row["datatime"] = normalize_published(got["datatime"]) or got["datatime"]
    row["enriched"] = True
    row["enrich_method"] = method
    row.pop("enrich_error", None)


def resolve_google_links(rows: list[dict], *, batch_size: int = 20) -> tuple[int, int]:
    """Google News RSS → прямой URL издателя через googlenewsdecoder."""
    try:
        from googlenewsdecoder import gnewsdecoder
    except ImportError:
        log("googlenewsdecoder не установлен — pip install googlenewsdecoder")
        return 0, 0

    need = [
        r
        for r in rows
        if not r.get("enriched")
        and "news.google.com" in (r.get("link") or "")
        and not r.get("resolved_link")
    ]
    log(f"decode google … {len(need)}")
    ok = fail = 0
    for start in range(0, len(need), batch_size):
        chunk = need[start : start + batch_size]
        links = [r.get("link") or "" for r in chunk]
        try:
            results = gnewsdecoder(links, interval=0, timeout=15.0)
        except Exception as exc:
            log(f"decode batch fail @{start}: {exc}")
            fail += len(chunk)
            for r in chunk:
                r["enrich_error"] = "gnews_decode"
            continue
        if isinstance(results, dict):
            results = [results]
        # сопоставляем по порядку батча
        for r, item in zip(chunk, results or []):
            if not isinstance(item, dict) or not item.get("success"):
                fail += 1
                r["enrich_error"] = "gnews_decode"
                continue
            decoded = str(item.get("decoded_url") or "").strip()
            if not decoded.startswith("http"):
                fail += 1
                r["enrich_error"] = "gnews_decode_empty"
                continue
            r["resolved_from_google"] = r.get("link")
            r["resolved_link"] = decoded
            r["link"] = decoded
            r.pop("enrich_error", None)
            ok += 1
        log(f"decode … {min(start + batch_size, len(need))}/{len(need)} ok={ok} fail={fail}")
        time.sleep(0.25)
    return ok, fail


def _http_try_row(row: dict) -> tuple[dict, dict | None, str]:
    """Один ряд: перебрать URL и вытащить тело (для пула потоков)."""
    google = row.get("resolved_from_google") or (
        row.get("link") if "news.google.com" in (row.get("link") or "") else None
    )
    urls: list[str] = []
    for key in ("resolved_link", "link"):
        u = row.get(key) or ""
        if u.startswith("http") and "news.google.com" not in u:
            urls.append(u)
    urls.extend(candidate_urls(row)[:8])
    # unique preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    for url in uniq[:12]:
        got = extract_from_url(url)
        if got:
            return row, got, google or ""
    return row, None, google or ""


def enrich_http_parallel(rows: list[dict], *, workers: int = 10) -> tuple[int, int]:
    need = [r for r in rows if not r.get("enriched")]
    log(f"http parallel … {len(need)} workers={workers}")
    ok = fail = 0
    if not need:
        return 0, 0
    with ThreadPoolExecutor(max_workers=max(2, workers)) as pool:
        futs = {pool.submit(_http_try_row, r): r for r in need}
        done = 0
        for fut in as_completed(futs):
            done += 1
            row, got, google = fut.result()
            if got:
                apply_extract(row, got, method="http_parallel", google_link=google or None)
                ok += 1
            else:
                fail += 1
                row["enrich_error"] = row.get("enrich_error") or "http_fail"
            if done == 1 or done % 25 == 0 or done == len(need):
                log(f"http … {done}/{len(need)} ok={ok} fail={fail}")
    return ok, fail


def enrich_guess(rows: list[dict]) -> tuple[int, int]:
    ok = fail = 0
    need = [r for r in rows if not r.get("enriched")]
    for i, row in enumerate(need, 1):
        if i == 1 or i % 20 == 0 or i == len(need):
            log(f"guess … {i}/{len(need)} ok={ok} fail={fail}")
        got = None
        for url in candidate_urls(row)[:10]:
            got = extract_from_url(url)
            if got:
                break
        if got:
            apply_extract(row, got, method="publisher_guess", google_link=row.get("resolved_from_google"))
            ok += 1
        else:
            fail += 1
            row["enrich_error"] = "guess_failed"
    return ok, fail


def enrich_playwright(rows: list[dict], *, pause_s: float = 4.0, save_cb=None) -> tuple[int, int]:
    from playwright.sync_api import sync_playwright

    need = [r for r in rows if not r.get("enriched")]
    log(f"playwright remaining={len(need)}")
    ok = fail = 0

    def accept(page) -> None:
        for sel in ('button:has-text("Accept all")', 'button:has-text("I agree")'):
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible(timeout=800):
                    loc.click(timeout=2000)
                    page.wait_for_timeout(800)
                    return
            except Exception:
                continue

    def new_page(p):
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            ignore_https_errors=True,
        )
        page = context.new_page()
        # без прогрева news.google.com — часто таймаут и валит весь прогон
        try:
            page.goto("about:blank", wait_until="domcontentloaded", timeout=10000)
        except Exception:
            pass
        return browser, page

    with sync_playwright() as p:
        browser, page = new_page(p)
        for i, row in enumerate(need, 1):
            log(f"pw … {i}/{len(need)} ok={ok} fail={fail} · {(row.get('title') or '')[:70]}")
            link = row.get("link") or ""
            google_link = row.get("resolved_from_google") or (
                link if "news.google.com" in link else None
            )
            # publisher URL предпочтительнее Google
            target = row.get("resolved_link") or link
            if "news.google.com" in (target or ""):
                target = link.replace("/rss/articles/", "/articles/")

            # быстрый HTTP; если пусто — браузер на тот же URL
            got = extract_from_url(target) if target.startswith("http") and "news.google.com" not in target else None
            if got:
                apply_extract(row, got, method="pw_http_first", google_link=google_link)
                ok += 1
                if save_cb and i % 10 == 0:
                    save_cb()
                time.sleep(0.4)
                continue

            try:
                page.goto(target, wait_until="domcontentloaded", timeout=50000)
            except Exception:
                fail += 1
                row["enrich_error"] = "pw_goto"
                try:
                    browser.close()
                except Exception:
                    pass
                time.sleep(pause_s)
                try:
                    browser, page = new_page(p)
                except Exception as exc:
                    log(f"browser restart fail: {exc}")
                    time.sleep(3)
                    browser, page = new_page(p)
                continue

            page.wait_for_timeout(1200)
            if "consent.google.com" in page.url:
                accept(page)
            for _ in range(30):
                u = page.url or ""
                if "news.google.com" not in u and "consent.google.com" not in u and "sorry" not in u:
                    break
                if "consent.google.com" in u:
                    accept(page)
                page.wait_for_timeout(350)

            cur = page.url or ""
            if "news.google.com" in cur or "consent.google.com" in cur or "sorry" in cur:
                fail += 1
                row["enrich_error"] = "pw_unresolved"
                time.sleep(pause_s)
                if fail % 5 == 0:
                    try:
                        browser.close()
                    except Exception:
                        pass
                    time.sleep(2)
                    try:
                        browser, page = new_page(p)
                    except Exception as exc:
                        log(f"browser restart fail: {exc}")
                        time.sleep(3)
                        browser, page = new_page(p)
                continue

            html = None
            try:
                page.wait_for_load_state("domcontentloaded", timeout=8000)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                html = page.content()
            except Exception:
                html = None
            rec = extract_article_page(html, cur, source_name="trade") if html else None
            if rec and not _bad_body(rec.text):
                apply_extract(
                    row,
                    {"url": cur, "title": rec.title, "text": rec.text, "datatime": rec.datatime or ""},
                    method="playwright_dom",
                    google_link=google_link,
                )
                ok += 1
            else:
                got2 = extract_from_url(cur)
                if got2:
                    apply_extract(row, got2, method="playwright_url_http", google_link=google_link)
                    ok += 1
                else:
                    fail += 1
                    row["enrich_error"] = "pw_extract"
                    row["resolved_link"] = cur

            if save_cb and i % 10 == 0:
                save_cb()
            time.sleep(pause_s)
            if i % 12 == 0:
                try:
                    browser.close()
                except Exception:
                    pass
                time.sleep(2)
                try:
                    browser, page = new_page(p)
                except Exception as exc:
                    log(f"browser restart fail: {exc}")
                    time.sleep(3)
                    browser, page = new_page(p)
        try:
            browser.close()
        except Exception:
            pass
    return ok, fail


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, default=Path("foreign_it_news/out_trade"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--playwright", action="store_true", help="Добить остаток через браузер")
    parser.add_argument("--pause", type=float, default=2.0)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--skip-decode", action="store_true")
    parser.add_argument("--skip-guess", action="store_true")
    args = parser.parse_args()

    path = args.dir / "it_focus.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("articles") or []
    for r in rows:
        if r.get("enriched") and _bad_body(r.get("text") or ""):
            r["enriched"] = False

    todo = [r for r in rows if not r.get("enriched")]
    if args.limit:
        todo = todo[: args.limit]

    def save() -> None:
        data["n_enriched"] = sum(
            1 for r in rows if r.get("enriched") and not _bad_body(r.get("text") or "")
        )
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    log(f"todo={len(todo)} already={sum(1 for r in rows if r.get('enriched'))}")

    if not args.skip_decode:
        d_ok, d_fail = resolve_google_links(todo)
        log(f"decode ok={d_ok} fail={d_fail}")
        save()

    h_ok, h_fail = enrich_http_parallel(todo, workers=args.workers)
    log(f"http ok={h_ok} fail={h_fail}")
    save()

    if not args.skip_guess:
        g_ok, g_fail = enrich_guess(todo)
        log(f"guess ok={g_ok} fail={g_fail}")
        save()

    if args.playwright:
        ok2, fail2 = enrich_playwright(todo, pause_s=args.pause, save_cb=save)
        log(f"playwright ok={ok2} fail={fail2}")
        save()

    # sync all_articles + wide_pool
    for name in ("all_articles.json", "wide_pool.json"):
        all_path = args.dir / name
        if not all_path.exists():
            continue
        all_data = json.loads(all_path.read_text(encoding="utf-8"))
        by_g = {
            r.get("resolved_from_google"): r
            for r in rows
            if r.get("enriched") and r.get("resolved_from_google")
        }
        by_t = {
            _headline_only(r.get("title") or "").lower(): r for r in rows if r.get("enriched")
        }
        n = 0
        for r in all_data.get("articles") or []:
            src = by_g.get(r.get("link")) or by_t.get(
                _headline_only(r.get("title") or "").lower()
            )
            if not src:
                # также match по старому google link в resolved_from_google поля цели
                continue
            r.update(
                {
                    "link": src.get("link"),
                    "text": src.get("text"),
                    "title": src.get("title") or r.get("title"),
                    "datatime": src.get("datatime") or r.get("datatime"),
                    "enriched": True,
                    "resolved_from_google": src.get("resolved_from_google"),
                    "resolved_link": src.get("resolved_link") or src.get("link"),
                }
            )
            n += 1
        all_path.write_text(json.dumps(all_data, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"patched {name}={n}")

    enriched = sum(1 for r in rows if r.get("enriched") and not _bad_body(r.get("text") or ""))
    log(f"DONE enriched={enriched}/{len(rows)}")
    return 0 if enriched else 1


if __name__ == "__main__":
    raise SystemExit(main())
