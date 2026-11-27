"""Парсинг RSS/Atom + Google News search feeds."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import quote_plus, urlparse

from gartner.custom_sources.fetch import fetch_html_safe

from .companies import COMPANIES


@dataclass
class FeedItem:
    title: str
    link: str
    published: str
    summary: str
    feed_id: str
    feed_name: str
    source_hint: str = ""


def _local(tag: str) -> str:
    return tag.split("}")[-1].lower() if tag else ""


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return unescape("".join(el.itertext())).strip()


def _strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return unescape(re.sub(r"\s+", " ", text)).strip()


def _child(el: ET.Element, *names: str) -> ET.Element | None:
    want = {n.lower() for n in names}
    for child in list(el):
        if _local(child.tag) in want:
            return child
    return None


def _link_from_item(el: ET.Element) -> str:
    # RSS <link>text</link> or Atom <link href="">
    for child in list(el):
        if _local(child.tag) != "link":
            continue
        href = child.attrib.get("href") or child.attrib.get("url")
        if href:
            return href.strip()
        if (child.text or "").strip():
            return child.text.strip()
    # guid often is url
    guid = _child(el, "guid")
    if guid is not None:
        is_permalink = (guid.attrib.get("isPermaLink") or "true").lower() != "false"
        val = _text(guid)
        if is_permalink and val.startswith("http"):
            return val
    return ""


def _google_article_url(link: str, summary_html: str) -> str:
    """Попробовать вытащить исходный URL из Google News item."""
    if "news.google.com" not in (link or ""):
        return link
    # в description часто <a href="https://...">
    for m in re.finditer(r'href=["\'](https?://[^"\']+)["\']', summary_html or "", flags=re.I):
        u = m.group(1)
        host = (urlparse(u).hostname or "").lower()
        if "news.google.com" in host or "google.com" in host:
            continue
        return u
    return link


def parse_feed_xml(xml_text: str, *, feed_id: str, feed_name: str) -> list[FeedItem]:
    if not xml_text:
        return []
    # убрать encoding declaration issues
    cleaned = re.sub(r"^\s*<\?xml[^.]*\?>", "", xml_text, count=1, flags=re.I)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        try:
            root = ET.fromstring(cleaned)
        except ET.ParseError:
            return []

    items: list[FeedItem] = []
    nodes = [n for n in root.iter() if _local(n.tag) in {"item", "entry"}]
    for node in nodes:
        title = _text(_child(node, "title"))
        summary_el = _child(node, "description", "summary", "content")
        summary_html = ""
        if summary_el is not None:
            summary_html = ET.tostring(summary_el, encoding="unicode", method="html")
        summary = _strip_html(_text(summary_el))
        link = _link_from_item(node)
        link = _google_article_url(link, summary_html)
        published_raw = _text(_child(node, "pubdate", "published", "updated", "date"))
        source_hint = ""
        src = _child(node, "source")
        if src is not None:
            source_hint = _text(src)
        # Google title often "Headline - Source"
        if " - " in title and not source_hint:
            source_hint = title.rsplit(" - ", 1)[-1].strip()
        items.append(
            FeedItem(
                title=title,
                link=link,
                published=published_raw,
                summary=summary,
                feed_id=feed_id,
                feed_name=feed_name,
                source_hint=source_hint,
            )
        )
    return items


def fetch_feed(url: str, *, feed_id: str, feed_name: str, timeout: float = 28.0) -> tuple[list[FeedItem], str | None]:
    html, err = fetch_html_safe(url, timeout=timeout)
    if not html:
        return [], err or "empty"
    return parse_feed_xml(html, feed_id=feed_id, feed_name=feed_name), None


def google_news_url(company_name: str) -> str:
    # для коротких/шумных имён — более жёсткая формулировка
    special = {
        "Shell": '"Shell plc" OR "Shell Oil" OR "Shell Exploration"',
        "BP": '"BP plc" OR "British Petroleum" OR "bp.com"',
        "Eni": '"Eni" oil OR "Eni Spa" OR "Eni S.p.A"',
        "Occidental (Oxy)": '"Occidental Petroleum" OR "Oxy Petroleum"',
    }
    name_q = special.get(company_name, f'"{company_name}"')
    q = (
        f"({name_q}) (digital OR AI OR \"artificial intelligence\" OR automation OR cloud "
        f"OR cybersecurity OR \"digital twin\" OR software OR SCADA OR IoT OR robotics "
        f"OR \"machine learning\" OR \"data platform\") when:365d"
    )
    return (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(q)}&hl=en-US&gl=US&ceid=US:en"
    )


def google_news_feeds() -> list[dict[str, str]]:
    out = []
    for co in COMPANIES:
        out.append(
            {
                "id": f"gnews_{co.id}",
                "name": f"Google News · {co.name}",
                "url": google_news_url(co.name),
                "company_id": co.id,
            }
        )
    # тематические / добирающие запросы (слабые majors + digital oilfield)
    thematic = [
        (
            "gnews_theme_digital_oilfield",
            "Google News · digital oilfield",
            '"digital oilfield" OR "digital twin" oil (AI OR automation OR cloud) when:365d',
        ),
        (
            "gnews_theme_og_ai",
            "Google News · oil&gas AI",
            "oil gas (AI OR digital OR automation OR cyber OR SCADA OR IoT) when:365d",
        ),
        (
            "gnews_theme_scada_majors",
            "Google News · SCADA/IoT majors",
            "SCADA OR IoT (ExxonMobil OR Chevron OR Shell OR Aramco OR Equinor OR ADNOC) when:365d",
        ),
        (
            "gnews_theme_oxy",
            "Google News · Occidental digital",
            '(Occidental OR "Oxy Petroleum") (digital OR AI OR automation OR cloud OR cyber) when:365d',
        ),
        (
            "gnews_theme_conoco",
            "Google News · Conoco digital",
            "ConocoPhillips (digital OR AI OR automation OR cloud OR software OR cyber) when:365d",
        ),
        (
            "gnews_theme_shell_plc",
            "Google News · Shell plc digital",
            '"Shell plc" OR "Shell Oil" (digital OR AI OR automation OR cloud OR cyber) when:365d',
        ),
        (
            "gnews_theme_worldoil",
            "Google News · site World Oil",
            "site:worldoil.com (AI OR digital OR automation OR robotics) (Exxon OR Chevron OR Shell OR Aramco) when:365d",
        ),
        (
            "gnews_theme_hart",
            "Google News · site Hart Energy",
            "site:hartenergy.com (AI OR automation OR digital OR robotics) when:365d",
        ),
        (
            "gnews_theme_rigzone",
            "Google News · site Rigzone",
            "site:rigzone.com (AI OR digital OR automation OR software) when:365d",
        ),
        (
            "gnews_theme_jpt",
            "Google News · site JPT/SPE",
            "site:jpt.spe.org (digital OR AI OR automation OR cloud) when:365d",
        ),
        (
            "gnews_theme_bp",
            "Google News · BP digital ops",
            '("BP plc" OR "bp.com") (digital OR "artificial intelligence" OR automation OR cloud OR cybersecurity OR robotics OR "digital twin") (oil OR gas OR energy) when:365d',
        ),
        (
            "gnews_theme_eni",
            "Google News · Eni digital",
            '("Eni" OR "Eni Spa") (digital OR AI OR automation OR cloud OR cybersecurity OR "digital twin" OR HPC OR supercomput) (oil OR gas OR energy) when:365d',
        ),
        (
            "gnews_theme_petrobras",
            "Google News · Petrobras digital",
            "Petrobras (digital OR AI OR automation OR cloud OR software OR robotics OR IoT) when:365d",
        ),
        (
            "gnews_theme_adnoc",
            "Google News · ADNOC digital",
            "ADNOC (digital OR AI OR automation OR cloud OR smart OR AIQ OR cybersecurity) when:365d",
        ),
        (
            "gnews_theme_aramco_digital",
            "Google News · Aramco digital",
            "Aramco (digital OR AI OR automation OR cloud OR \"4IR\" OR cybersecurity OR robotics) when:365d",
        ),
        (
            "gnews_theme_equinor_digital",
            "Google News · Equinor digital",
            "Equinor (digital OR AI OR automation OR cloud OR robotics OR \"digital twin\") when:365d",
        ),
        (
            "gnews_theme_slb_majors",
            "Google News · SLB digital majors",
            "(SLB OR Schlumberger OR Halliburton OR Baker Hughes) (Exxon OR Chevron OR Shell OR BP OR Aramco OR Equinor) (digital OR AI OR software OR automation) when:365d",
        ),
        (
            "gnews_bing_style_oxy",
            "Google News · Oxy DAC digital",
            '"Occidental Petroleum" (digital OR AI OR automation OR software OR cloud OR "direct air") when:365d',
        ),
        (
            "gnews_shell_ops",
            "Google News · Shell digital ops",
            '("Shell plc" OR "Shell Oil") (AI OR "artificial intelligence" OR automation OR robotics OR "digital twin" OR cloud OR cybersecurity) (upstream OR offshore OR refining OR LNG OR Permian) when:365d',
        ),
        (
            "gnews_conoco_ops",
            "Google News · Conoco ops tech",
            'ConocoPhillips (AI OR automation OR robotics OR "digital twin" OR cloud OR cybersecurity OR software) (Permian OR drilling OR production) when:365d',
        ),
        (
            "gnews_site_bnamericas",
            "Google News · BNamericas IT",
            "site:bnamericas.com (Petrobras OR Equinor OR Shell OR TotalEnergies) (IT OR cloud OR AI OR cyber OR digital) when:365d",
        ),
        (
            "gnews_site_offshore_energy",
            "Google News · Offshore Energy digital",
            "site:offshore-energy.biz (automation OR digital OR AI OR robotics) when:365d",
        ),
        (
            "gnews_shell_worldoil",
            "Google News · Shell @ World Oil",
            "site:worldoil.com Shell (AI OR digital OR automation OR robotics OR \"digital twin\")",
        ),
        (
            "gnews_shell_offshore",
            "Google News · Shell @ Offshore Energy",
            "site:offshore-energy.biz Shell (AI OR digital OR automation OR robot OR \"digital twin\")",
        ),
        (
            "gnews_shell_drones",
            "Google News · Shell drones/automation",
            "Shell (drone OR robotics OR \"digital twin\" OR \"C3.ai\" OR cybersecurity) (offshore OR Permian OR upstream) when:365d",
        ),
        (
            "gnews_conoco_hart",
            "Google News · Conoco @ Hart",
            "site:hartenergy.com (ConocoPhillips OR COP) (AI OR automation OR digital OR robotics)",
        ),
        (
            "gnews_conoco_xom_cvx",
            "Google News · COP automation peers",
            "ConocoPhillips (automation OR \"artificial lift\" OR digital OR AI) (Permian OR production) when:365d",
        ),
    ]
    for fid, name, q in thematic:
        out.append(
            {
                "id": fid,
                "name": name,
                "url": (
                    "https://news.google.com/rss/search?"
                    f"q={quote_plus(q)}&hl=en-US&gl=US&ceid=US:en"
                ),
            }
        )
    return out


def normalize_published(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        dt = parsedate_to_datetime(raw)
        return dt.date().isoformat()
    except Exception:
        pass
    # ISO-ish
    m = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
    return m.group(1) if m else raw[:32]
