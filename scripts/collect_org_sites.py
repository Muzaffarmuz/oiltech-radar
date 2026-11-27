"""Полный сбор официальных сайтов и лент новостей для патентообладателей.

Источники:
  1) curated KNOWN (мажоры / вузы / НИИ — high/medium)
  2) live DuckDuckGo (ddgs) для остальных не-person
  3) probe типичных /news|/press путей

Запуск:
  python scripts/collect_org_sites.py
  python scripts/collect_org_sites.py --resume
  python scripts/collect_org_sites.py --limit 50   # smoke

Пишет в data/exports/org_sites_prompt/:
  all_patent_holders_sites.json, science_enterprises_sites.json|.tsv,
  org_news_sources.json|.tsv, org_news_sources_v2.json,
  org_sites_cleaned.json, sites_collection_summary.json,
  batches/, прогресс: _sites_collect_progress.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPORT = ROOT / "data" / "exports" / "org_sites_prompt"
UNIQUE = ROOT / "data" / "runs" / "patents" / "unique_orgs.json"
PROGRESS = EXPORT / "_sites_collect_progress.json"

UA = "OilTechRadar/4.0 (local research; patent org sites)"
BAD_HOST_PARTS = (
    "wikipedia.org",
    "wikidata.org",
    "facebook.com",
    "vk.com",
    "linkedin.com",
    "youtube.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "t.me",
    "spark-interfax",
    "kontur.ru",
    "list-org.com",
    "checko.ru",
    "rusprofile.ru",
    "sbis.ru",
    "zachestnyibiznes",
    "neftegaz.ru/catalog",
    "yellowpages",
    "2gis.ru",
    "yandex.ru",
    "google.com",
    "bing.com",
    "market.neftegaz",
    "hh.ru",
    "avito.ru",
    "rospatent",
    "fips.ru",
    "patents.google",
    "espacenet",
)

NEWS_PATHS = (
    "/press/",
    "/press",
    "/press-center/",
    "/press-center",
    "/press-tsentr/",
    "/media/",
    "/media/news",
    "/news/",
    "/news",
    "/novosti/",
    "/novosti",
    "/ru/press/",
    "/ru/news/",
    "/en/news/",
    "/en/media/",
)

# (official, news, lang, confidence, note) — ключ = lower(name) с ё→е, схлопнутые пробелы
KNOWN: dict[str, tuple[str | None, str | None, str | None, str, str | None]] = {
    "татнефть": ("https://www.tatneft.ru", "https://www.tatneft.ru/press-tsentr/press-relizi", "ru", "high", None),
    "газпром": ("https://www.gazprom.ru", "https://www.gazprom.ru/press/", "ru", "high", None),
    "газпром нефть": ("https://www.gazprom-neft.ru", "https://www.gazprom-neft.ru/press-center", "ru", "high", None),
    "роснефть": ("https://www.rosneft.ru", "https://www.rosneft.ru/press/", "ru", "high", None),
    "лукойл": ("https://lukoil.ru", "https://lukoil.ru/PressCenter", "ru", "high", None),
    "новатэк": ("https://www.novatek.ru", "https://www.novatek.ru/ru/press/releases/", "ru", "high", None),
    "сургутнефтегаз": ("https://www.surgutneftegas.ru", "https://www.surgutneftegas.ru/press/", "ru", "high", None),
    "транснефть": ("https://www.transneft.ru", "https://www.transneft.ru/press/", "ru", "high", None),
    "сибур": ("https://www.sibur.ru", "https://www.sibur.ru/press-center/", "ru", "high", None),
    "башнефть": ("https://www.bashneft.ru", "https://www.bashneft.ru/press/", "ru", "high", None),
    "зарубежнефть": ("https://www.zarubezhneft.ru", "https://www.zarubezhneft.ru/press/", "ru", "high", None),
    "gaztransport & technigaz": ("https://www.gtt.fr", "https://www.gtt.fr/en/media", "en", "high", "GTT"),
    "sinopec": ("http://www.sinopecgroup.com", "http://www.sinopecgroup.com/group/en/Sinopecnews", "en", "high", None),
    "ifp energies nouvelles": ("https://www.ifpenergiesnouvelles.com", "https://www.ifpenergiesnouvelles.com/article", "en", "high", "IFPEN"),
    "innospec": ("https://www.innospec.com", "https://www.innospec.com/news-media/", "en", "high", None),
    "jfe steel": ("https://www.jfe-steel.co.jp/en/", "https://www.jfe-steel.co.jp/en/release/", "en", "high", None),
    "шлюмберже": ("https://www.slb.com", "https://www.slb.com/newsroom", "en", "high", "SLB"),
    "топсеэ а/с": ("https://www.topsoe.com", "https://www.topsoe.com/news", "en", "high", "Topsoe"),
    "буринтех": ("https://burinteh.com", "https://burinteh.com/press-centr/", "ru", "high", None),
    "газпром трансгаз томск": ("https://tomsk-tr.gazprom.ru", "https://tomsk-tr.gazprom.ru/press/", "ru", "high", None),
    "газпром трансгаз ухта": ("https://ukhta-tr.gazprom.ru", "https://ukhta-tr.gazprom.ru/press/", "ru", "high", None),
    "газпром трансгаз уфа": ("https://ufa-tr.gazprom.ru", "https://ufa-tr.gazprom.ru/press/", "ru", "high", None),
    "газпром трансгаз казань": ("https://kazan-tr.gazprom.ru", "https://kazan-tr.gazprom.ru/press/", "ru", "high", None),
    "газпром трансгаз нижний новгород": ("https://nn-tr.gazprom.ru", "https://nn-tr.gazprom.ru/press/", "ru", "high", None),
    "газпром трансгаз самара": ("https://samara-tr.gazprom.ru", "https://samara-tr.gazprom.ru/press/", "ru", "high", None),
    "газпром трансгаз саратов": ("https://saratov-tr.gazprom.ru", "https://saratov-tr.gazprom.ru/press/", "ru", "high", None),
    "газпром трансгаз чайковский": ("https://chaikovsky-tr.gazprom.ru", "https://chaikovsky-tr.gazprom.ru/press/", "ru", "high", None),
    "газпром добыча ямбург": ("https://yamburg-dobycha.gazprom.ru", "https://yamburg-dobycha.gazprom.ru/press/", "ru", "high", None),
    "газпром добыча уренгой": ("https://urengoy-dobycha.gazprom.ru", "https://urengoy-dobycha.gazprom.ru/press/", "ru", "high", None),
    "газпром добыча надым": ("https://nadymdobycha.gazprom.ru", "https://nadymdobycha.gazprom.ru/press/", "ru", "medium", None),
    "газпром добыча ноябрьск": ("https://noyabrsk-dobycha.gazprom.ru", "https://noyabrsk-dobycha.gazprom.ru/press/", "ru", "high", None),
    "газпром добыча оренбург": ("https://orenburg-dobycha.gazprom.ru", "https://orenburg-dobycha.gazprom.ru/press/", "ru", "high", None),
    "газпром добыча иркутск": ("https://irkutsk-dobycha.gazprom.ru", "https://irkutsk-dobycha.gazprom.ru/press/", "ru", "high", None),
    "газпром пхг": ("https://phg.gazprom.ru", "https://phg.gazprom.ru/press/", "ru", "high", None),
    "вниигаз": ("https://vniigaz.gazprom.ru", "https://vniigaz.gazprom.ru/press/", "ru", "high", None),
    "новатэк нтц": ("https://www.novatek.ru", "https://www.novatek.ru/ru/press/releases/", "ru", "medium", "НТЦ через novatek.ru"),
    "кубгту": ("https://kubstu.ru", "https://kubstu.ru/s-109", "ru", "high", None),
    "санкт-петербургский горный университет": ("https://spmi.ru", "https://spmi.ru/news", "ru", "high", None),
    "угнту": ("https://www.rusoil.net", "https://www.rusoil.net/news/", "ru", "high", "УГНТУ"),
    "казанский федеральный университет": ("https://kpfu.ru", "https://media.kpfu.ru", "ru", "high", None),
    "пнипу": ("https://pstu.ru", "https://pstu.ru/news/", "ru", "high", None),
    "сфу": ("https://www.sfu-kras.ru", "https://news.sfu-kras.ru", "ru", "high", None),
    "высшая школа нефти (альметьевск)": ("https://www.agni-rt.ru", "https://www.agni-rt.ru/news/", "ru", "medium", "АГНИ / ВШН"),
    "ргу нефти и газа им. губкина": ("https://www.gubkin.ru", "https://www.gubkin.ru/news/", "ru", "high", None),
    "уунит": ("https://uust.ru", "https://uust.ru/news/", "ru", "high", "УУНиТ"),
    "томский политехнический университет": ("https://tpu.ru", "https://news.tpu.ru", "ru", "high", None),
    "тюменский индустриальный университет": ("https://www.tyuiu.ru", "https://www.tyuiu.ru/news/", "ru", "high", None),
    "удмуртский государственный университет": ("https://udsu.ru", "https://udsu.ru/news/", "ru", "high", None),
    "кузбасский государственный технический университет имени т.ф. горбачева": (
        "https://kuzstu.ru",
        "https://kuzstu.ru/news/",
        "ru",
        "high",
        None,
    ),
    "новосибирский национальный исследовательский государственный университет": (
        "https://www.nsu.ru",
        "https://www.nsu.ru/n/",
        "ru",
        "high",
        None,
    ),
    "рудн": ("https://www.rudn.ru", "https://www.rudn.ru/media/news", "ru", "high", None),
    "сгту им. гагарина": ("https://www.sstu.ru", "https://www.sstu.ru/news/", "ru", "high", None),
    "институт геофизики уро ран": ("https://igfu.ru", "https://igfu.ru/news/", "ru", "medium", None),
    "ингг со ран": ("https://www.ipgg.sbras.ru", "https://www.ipgg.sbras.ru/ru/news", "ru", "high", None),
    "институт катализа со ран": ("https://catalysis.ru", "https://catalysis.ru/news/", "ru", "high", None),
    "гбун ордена трудового красного знамени институт нефтехимического синтеза им. а.в. топчиева российской академии наук (инхс ран)": (
        "https://www.ips.ac.ru",
        "https://www.ips.ac.ru/news/",
        "ru",
        "high",
        "ИНХС РАН",
    ),
    "министерство науки и высшего образования фгбун институт проблем нефти и газа ран (ипнг ран)": (
        "https://www.ipng.ru",
        "https://www.ipng.ru/news/",
        "ru",
        "high",
        "ИПНГ РАН",
    ),
    "гбун институт физики земли им. о.ю. шмидта российской академии наук": (
        "https://www.ifz.ru",
        "https://www.ifz.ru/novosti/",
        "ru",
        "high",
        None,
    ),
    "федеральный исследовательский центр угля и углехимии сибирского отделения российской академии наук": (
        "https://fic-ugi.ru",
        None,
        "ru",
        "medium",
        None,
    ),
    "всероссийский нии физико-технических и радиотехнических измерений «вниифтри»": (
        "https://www.vniiftri.ru",
        "https://www.vniiftri.ru/press/",
        "ru",
        "high",
        None,
    ),
    "тюменский нефтяной научный центр": ("https://tnnc.rosneft.ru", None, "ru", "medium", "ТННЦ / Роснефть"),
    "пегаз": ("https://www.pegas.su", None, "ru", "medium", None),
}

SUBSTRING_RULES: list[tuple[str, tuple]] = [
    ("schlumberger", ("https://www.slb.com", "https://www.slb.com/newsroom", "en", "high", None)),
    ("halliburton", ("https://www.halliburton.com", "https://www.halliburton.com/en/news", "en", "high", None)),
    ("baker hughes", ("https://www.bakerhughes.com", "https://www.bakerhughes.com/news", "en", "high", None)),
    ("weatherford", ("https://www.weatherford.com", "https://www.weatherford.com/newsroom/", "en", "high", None)),
    ("exxon", ("https://corporate.exxonmobil.com", "https://corporate.exxonmobil.com/news", "en", "high", None)),
    ("totalenergies", ("https://totalenergies.com", "https://totalenergies.com/media", "en", "high", None)),
    ("chevron", ("https://www.chevron.com", "https://www.chevron.com/newsroom", "en", "high", None)),
    ("equinor", ("https://www.equinor.com", "https://www.equinor.com/news", "en", "high", None)),
    ("topsoe", ("https://www.topsoe.com", "https://www.topsoe.com/news", "en", "high", None)),
    ("губкина", ("https://www.gubkin.ru", "https://www.gubkin.ru/news/", "ru", "high", None)),
    ("вниигаз", ("https://vniigaz.gazprom.ru", "https://vniigaz.gazprom.ru/press/", "ru", "high", None)),
    ("инхс", ("https://www.ips.ac.ru", "https://www.ips.ac.ru/news/", "ru", "high", None)),
    ("ипнг", ("https://www.ipng.ru", "https://www.ipng.ru/news/", "ru", "high", None)),
    ("ингг", ("https://www.ipgg.sbras.ru", "https://www.ipgg.sbras.ru/ru/news", "ru", "high", None)),
]


def norm(s: str) -> str:
    s = (s or "").lower().replace("ё", "е")
    s = re.sub(r"[«»\"']", "", s)
    return re.sub(r"\s+", " ", s).strip()


def empty_row(name: str, note: str | None = None, conf: str = "low") -> dict:
    return {
        "name": name,
        "official_url": None,
        "news_url": None,
        "lang": None,
        "confidence": conf,
        "note": note,
        "source": "skip",
    }


def from_tuple(name: str, t: tuple, source: str) -> dict:
    o, n, lang, conf, note = t
    return {
        "name": name,
        "official_url": o,
        "news_url": n,
        "lang": lang,
        "confidence": conf,
        "note": note,
        "source": source,
    }


def resolve_known(name: str) -> dict | None:
    key = norm(name)
    if key in KNOWN:
        return from_tuple(name, KNOWN[key], "known")
    for sub, t in SUBSTRING_RULES:
        if sub in key and t is not None:
            return from_tuple(name, t, "substring")
    return None


def is_bad_url(url: str) -> bool:
    u = (url or "").lower()
    if not u.startswith("http"):
        return True
    return any(b in u for b in BAD_HOST_PARTS)


def rootish(url: str) -> str:
    try:
        p = urlparse(url)
        host = (p.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        # предпочитаем apex / короткий путь
        path = p.path or "/"
        if path in ("/", "") or path.count("/") <= 1:
            return f"{p.scheme}://{p.netloc}/"
        # убираем deep paths для official
        return f"{p.scheme}://{p.netloc}/"
    except Exception:
        return url


def score_hit(name: str, href: str, title: str, body: str) -> float:
    if is_bad_url(href):
        return -100.0
    score = 0.0
    host = (urlparse(href).netloc or "").lower()
    path = (urlparse(href).path or "").lower()
    blob = f"{title} {body}".lower()
    n = norm(name)
    tokens = [t for t in re.split(r"[^\w]+", n) if len(t) >= 4][:6]

    if "официальн" in blob or "official" in blob:
        score += 3.0
    if host.endswith(".edu") or ".ac.ru" in host or host.endswith(".edu.ru"):
        score += 2.5
    if host.endswith(".ru") or host.endswith(".su"):
        score += 0.5
    # короткие пути лучше
    depth = path.strip("/").count("/")
    score -= depth * 0.4
    if any(x in host for x in ("azs.", "oil.", "market.", "shop.", "store.")):
        score -= 2.0
    if "old." in host:
        score -= 1.5
    hit_tokens = sum(1 for t in tokens if t in host or t in blob)
    score += min(hit_tokens, 3) * 1.2
    # gazprom subdomain patterns
    if "gazprom.ru" in host:
        score += 1.5
    return score


def _ddg_worker(query: str, max_results: int, q) -> None:
    """Отдельный процесс — можно убить при зависании DDG."""
    try:
        from ddgs import DDGS

        rows = list(DDGS().text(query, max_results=max_results))
        out = []
        for r in rows:
            href = r.get("href") or r.get("link") or ""
            out.append(
                {
                    "href": href,
                    "title": r.get("title") or "",
                    "body": r.get("body") or r.get("snippet") or "",
                }
            )
        q.put(out)
    except Exception:
        q.put([])


def ddg_search(query: str, max_results: int = 6, timeout_sec: float = 15.0) -> list[dict]:
    """DDG в отдельном процессе с kill по таймауту."""
    import multiprocessing as mp

    ctx = mp.get_context("spawn")
    q: mp.Queue = ctx.Queue()
    proc = ctx.Process(target=_ddg_worker, args=(query, max_results, q))
    proc.start()
    proc.join(timeout=timeout_sec)
    if proc.is_alive():
        proc.terminate()
        proc.join(2)
        if proc.is_alive():
            proc.kill()
            proc.join(1)
        return []
    try:
        return q.get_nowait() if not q.empty() else []
    except Exception:
        return []


def pick_official(name: str, org_type: str) -> tuple[str | None, str]:
    if org_type == "foreign":
        queries = [f"{name} official website"]
    elif org_type in ("university", "nii"):
        queries = [f"{name} официальный сайт"]
    else:
        queries = [f"{name} официальный сайт"]

    best_url = None
    best_score = -1.0
    for q in queries:
        hits = ddg_search(q, max_results=6)
        time.sleep(0.5)
        for h in hits:
            sc = score_hit(name, h["href"], h["title"], h["body"])
            if sc > best_score:
                best_score = sc
                best_url = h["href"]

    if not best_url or best_score < 1.5:
        return None, "low"
    url = rootish(best_url)
    if best_score >= 5.0:
        conf = "high"
    elif best_score >= 3.0:
        conf = "medium"
    else:
        conf = "low"
    return url, conf


def probe_news(official: str, client: httpx.Client) -> str | None:
    """Только HTTP probe типичных путей — без второго DDG (он часто зависает)."""
    if not official:
        return None
    base = official.rstrip("/") + "/"
    for path in NEWS_PATHS:
        url = urljoin(base, path.lstrip("/"))
        try:
            r = client.head(url, follow_redirects=True, timeout=6.0)
            if r.status_code < 400:
                final = str(r.url)
                low = final.lower()
                # отсекаем редиректы на главную без news-маркера, если path не сохранился
                if any(x in low for x in ("/news", "/press", "/media", "/novosti", "press-center", "press-tsentr")):
                    return final
                if path.strip("/") and path.strip("/").split("/")[0] in low:
                    return final
        except Exception:
            continue
    return None


def guess_lang(url: str | None) -> str | None:
    if not url:
        return None
    host = (urlparse(url).netloc or "").lower()
    if host.endswith(".ru") or host.endswith(".su") or ".ru." in host:
        return "ru"
    return "en"


def load_items() -> list[dict]:
    data = json.loads(UNIQUE.read_text(encoding="utf-8"))
    return list(data.get("items") or [])


def load_progress() -> dict[str, dict]:
    if not PROGRESS.exists():
        return {}
    raw = json.loads(PROGRESS.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "by_name" in raw:
        return raw["by_name"]
    if isinstance(raw, list):
        return {x["name"]: x for x in raw if x.get("name")}
    return {}


def save_progress(by_name: dict[str, dict]) -> None:
    EXPORT.mkdir(parents=True, exist_ok=True)
    payload = {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "count": len(by_name), "by_name": by_name}
    PROGRESS.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_outputs(by_name: dict[str, dict], items: list[dict]) -> None:
    holders_order = sorted(items, key=lambda x: (-int(x.get("patent_count") or 0), norm(x["canonical_name"])))
    science_names = {
        x["canonical_name"]
        for x in holders_order
        if x.get("org_type") in ("university", "nii") and int(x.get("patent_count") or 0) > 0
    }

    def pub(row: dict) -> dict:
        return {
            "name": row["name"],
            "official_url": row.get("official_url"),
            "news_url": row.get("news_url"),
            "lang": row.get("lang"),
            "confidence": row.get("confidence"),
            "note": row.get("note"),
        }

    holders_pub = [pub(by_name[x["canonical_name"]]) for x in holders_order if x["canonical_name"] in by_name]
    science_pub = [pub(by_name[n]) for n in [x["canonical_name"] for x in holders_order if x["canonical_name"] in science_names] if n in by_name]
    news_only = [x for x in holders_pub if x.get("news_url")]

    (EXPORT / "all_patent_holders_sites.json").write_text(
        json.dumps(holders_pub, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (EXPORT / "science_enterprises_sites.json").write_text(
        json.dumps(science_pub, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (EXPORT / "org_news_sources.json").write_text(json.dumps(news_only, ensure_ascii=False, indent=2), encoding="utf-8")
    (EXPORT / "org_news_sources_v2.json").write_text(json.dumps(news_only, ensure_ascii=False, indent=2), encoding="utf-8")
    cleaned = {x["name"]: x for x in holders_pub if x.get("official_url") or x.get("news_url")}
    (EXPORT / "org_sites_cleaned.json").write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")

    tsv = ["name\tofficial_url\tnews_url\tlang\tconfidence\tnote"]
    for x in science_pub:
        tsv.append(
            "\t".join(
                [
                    x["name"],
                    x.get("official_url") or "",
                    x.get("news_url") or "",
                    x.get("lang") or "",
                    x.get("confidence") or "",
                    (x.get("note") or "").replace("\t", " "),
                ]
            )
        )
    (EXPORT / "science_enterprises_sites.tsv").write_text("\n".join(tsv), encoding="utf-8")

    tsv2 = ["name\tofficial_url\tnews_url\tlang\tconfidence\tnote"]
    for x in news_only:
        tsv2.append(
            "\t".join(
                [
                    x["name"],
                    x.get("official_url") or "",
                    x.get("news_url") or "",
                    x.get("lang") or "",
                    x.get("confidence") or "",
                    (x.get("note") or "").replace("\t", " "),
                ]
            )
        )
    (EXPORT / "org_news_sources.tsv").write_text("\n".join(tsv2), encoding="utf-8")

    def stats(rows: list[dict]) -> dict:
        return {
            "total": len(rows),
            "with_official": sum(1 for x in rows if x.get("official_url")),
            "with_news": sum(1 for x in rows if x.get("news_url")),
            "high": sum(1 for x in rows if x.get("confidence") == "high"),
            "medium": sum(1 for x in rows if x.get("confidence") == "medium"),
            "low": sum(1 for x in rows if x.get("confidence") == "low"),
        }

    summary = {
        "science_enterprises": stats(science_pub),
        "all_patent_holders": stats(holders_pub),
        "with_news_url_for_scrape": len(news_only),
        "method": "known+substring + live DuckDuckGo + news path probe; persons skipped",
        "files": [
            "science_enterprises_sites.json",
            "science_enterprises_sites.tsv",
            "all_patent_holders_sites.json",
            "org_news_sources.json",
            "org_news_sources_v2.json",
            "org_sites_cleaned.json",
        ],
    }
    (EXPORT / "sites_collection_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # refresh Google-AI batches (science first, then others without site)
    batch_dir = EXPORT / "batches"
    batch_dir.mkdir(exist_ok=True)
    for old in batch_dir.glob("batch_*.txt"):
        old.unlink()
    names_sci = [x["name"] for x in science_pub]
    names_rest = [x["name"] for x in holders_pub if x["name"] not in science_names]
    all_names = names_sci + names_rest
    BATCH = 40
    n_batches = 0
    for i in range(0, len(all_names), BATCH):
        n_batches += 1
        chunk = all_names[i : i + BATCH]
        (batch_dir / f"batch_{n_batches:03d}.txt").write_text("\n".join(chunk), encoding="utf-8")

    readme = EXPORT / "README.md"
    readme.write_text(
        "\n".join(
            [
                "# Списки организаций для поиска сайтов / новостей",
                "",
                f"- Патентообладатели (все): {len(holders_pub)}",
                f"- Научные предприятия (вузы и НИИ с патентами): {len(science_pub)}",
                f"- С news_url для скрейпа: {len(news_only)}",
                f"- Батчи по 40 имён: {n_batches} файлов в batches/",
                "",
                "Сбор: `python scripts/collect_org_sites.py`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def collect(
    resume: bool,
    limit: int | None,
    skip_news_probe: bool,
    max_new: int | None,
    finalize: bool,
) -> dict:
    items = load_items()
    by_name = load_progress() if resume else {}
    if not resume and PROGRESS.exists():
        PROGRESS.unlink()

    # priority: science & companies first
    priority = {
        "university": 0,
        "nii": 1,
        "company": 2,
        "subsidiary": 3,
        "foreign": 4,
        "unknown": 5,
        "person": 9,
        "redacted": 9,
    }
    ordered = sorted(
        items,
        key=lambda x: (
            priority.get(x.get("org_type") or "", 6),
            -int(x.get("patent_count") or 0),
            norm(x["canonical_name"]),
        ),
    )
    if limit:
        ordered = ordered[:limit]

    total_all = len(items)
    pending = [x for x in ordered if x["canonical_name"] not in by_name]
    if max_new is not None:
        pending = pending[:max_new]

    client = httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=12.0)
    newly = 0
    try:
        for item in pending:
            name = item["canonical_name"]
            otype = item.get("org_type") or "unknown"

            if otype in ("person", "redacted"):
                by_name[name] = empty_row(name, note="person/redacted", conf="low")
                newly += 1
                save_progress(by_name)
                print(f"[+{newly}] person skip: {name[:50]}", flush=True)
                continue

            row = resolve_known(name)
            if row is None:
                official, conf = pick_official(name, otype)
                row = {
                    "name": name,
                    "official_url": official,
                    "news_url": None,
                    "lang": guess_lang(official),
                    "confidence": conf if official else "low",
                    "note": None if official else "not found via search",
                    "source": "ddg" if official else "ddg_miss",
                }
            else:
                if not row.get("lang"):
                    row["lang"] = guess_lang(row.get("official_url"))

            if row.get("official_url") and not row.get("news_url") and not skip_news_probe:
                try:
                    news = probe_news(row["official_url"], client)
                    if news:
                        row["news_url"] = news
                except Exception as e:
                    row["note"] = (row.get("note") or "") + f"; news probe err: {e}"

            by_name[name] = row
            newly += 1
            save_progress(by_name)
            print(
                f"[{len(by_name)}/{total_all} +{newly}] {name[:55]} -> {row.get('official_url') or '-'} | {row.get('confidence')} ({row.get('source')})",
                flush=True,
            )
    finally:
        client.close()
        save_progress(by_name)

    remaining = sum(1 for x in items if x["canonical_name"] not in by_name)
    with_url = sum(1 for v in by_name.values() if v.get("official_url"))
    status = {
        "saved": len(by_name),
        "total": total_all,
        "remaining": remaining,
        "newly": newly,
        "with_official": with_url,
        "done": remaining == 0,
    }
    print(f"BATCH_STATUS {json.dumps(status, ensure_ascii=False)}", flush=True)

    if finalize or remaining == 0:
        if remaining == 0:
            write_outputs(by_name, items)
        elif finalize:
            # partial finalize for inspection
            write_outputs(by_name, items)
    return status


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", action="store_true", help="продолжить с _sites_collect_progress.json")
    ap.add_argument("--limit", type=int, default=None, help="ограничить очередь (smoke)")
    ap.add_argument("--max-new", type=int, default=None, help="обработать не больше N новых орг и выйти")
    ap.add_argument("--finalize", action="store_true", help="перезаписать итоговые JSON даже если не всё готово")
    ap.add_argument("--skip-news-probe", action="store_true")
    args = ap.parse_args()
    collect(
        resume=args.resume,
        limit=args.limit,
        skip_news_probe=args.skip_news_probe,
        max_new=args.max_new,
        finalize=args.finalize,
    )


if __name__ == "__main__":
    main()
