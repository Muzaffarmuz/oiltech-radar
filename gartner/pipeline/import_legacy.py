"""Импорт legacy-корпуса / CSV старого gartner в SQLite + пересборка портала.

Ищет (в порядке приоритета):
1) data/legacy/import/*.csv  — настоящие pt._3.* / filtr_extract, если положите файлы
2) data/legacy/reconstructed_corpus.json — восстановленный корпус тем старого пайплайна

Важно: исходные CSV с ~428 событиями в репозитории отсутствуют (.gitignore data/).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from gartner.company import normalize_company, normalize_text
from gartner.config import DATA_DIR, SEED_DIR, ensure_dirs
from gartner.db import connect, init_db, set_state, utc_now
from gartner.pipeline.build_portal import build_portal_payload
from gartner.pipeline.embeddings import ensure_embeddings
from gartner.pipeline.enrich import enrich_clusters
from gartner.pipeline.forecast import forecast_clusters
from gartner.pipeline.qa import build_qa_report
from gartner.pipeline.snapshot import create_snapshot
from gartner.pipeline.extract import event_id_for
from gartner.pipeline.merge import article_id_from_link

LEGACY_DIR = DATA_DIR / "legacy"
IMPORT_DIR = LEGACY_DIR / "import"
CORPUS_PATH = LEGACY_DIR / "reconstructed_corpus.json"

# Темы, соответствующие фокусу старого gartner (pt.2/pt.3): IT/AI в нефтегазе
LEGACY_THEMES: list[dict[str, Any]] = [
    {
        "cluster_id": "legacy_01",
        "title": "Цифровые двойники месторождений и скважин",
        "description": "Моделирование активов добычи и сценариев разработки на цифровых двойниках.",
        "stage": "breakthrough",
        "segment": "Upstream",
        "topics": ["цифровой двойник месторождения", "цифровой двойник буровой", "цифровая скважина"],
    },
    {
        "cluster_id": "legacy_02",
        "title": "ML для прогноза осложнений при бурении",
        "description": "Машинное обучение для прогноза рисков и оптимизации режимов бурения.",
        "stage": "emerging",
        "segment": "Upstream",
        "topics": ["машинное обучение для прогноза осложнений при бурении", "прогноз ГНВП", "оптимизация траектории бурения"],
    },
    {
        "cluster_id": "legacy_03",
        "title": "LLM-ассистенты инженеров добычи",
        "description": "Большие языковые модели как помощники по регламентам, ремонтам и операциям.",
        "stage": "emerging",
        "segment": "Upstream",
        "topics": ["LLM-ассистент для инженеров добычи", "ИИ-ассистент бурильщика", "knowledge assistant промысла"],
    },
    {
        "cluster_id": "legacy_04",
        "title": "Предиктивное обслуживание промыслового оборудования",
        "description": "Прогноз отказов насосного фонда и оборудования по телеметрии и ML.",
        "stage": "mature",
        "segment": "Upstream",
        "topics": ["предиктивное обслуживание насосного фонда", "ML прогноз износа", "IoT телеметрия оборудования"],
    },
    {
        "cluster_id": "legacy_05",
        "title": "Роботизация и автономные операции на буровой",
        "description": "Роботизированные комплексы СПО и снижение участия персонала в опасных зонах.",
        "stage": "emerging",
        "segment": "Upstream",
        "topics": ["роботизированный комплекс СПО", "автономное управление буровой", "безлюдные операции"],
    },
    {
        "cluster_id": "legacy_06",
        "title": "Видеоаналитика и компьютерное зрение",
        "description": "CV для разливов, коррозии, охраны и промышленной безопасности.",
        "stage": "breakthrough",
        "segment": "Midstream",
        "topics": ["видеоаналитика разливов", "компьютерное зрение коррозии трубопроводов", "видеоаналитика промбезопасности"],
    },
    {
        "cluster_id": "legacy_07",
        "title": "Корпоративные платформы данных",
        "description": "Единые контуры данных добычи/бурения и промышленные data platform.",
        "stage": "mature",
        "segment": "Upstream",
        "topics": ["корпоративная платформа данных", "единый контур данных бурения", "data platform нефтегаза"],
    },
    {
        "cluster_id": "legacy_08",
        "title": "Оптимизация энергоэффективности НПЗ",
        "description": "Рекомендательные системы и оптимизация режимов переработки.",
        "stage": "mature",
        "segment": "Downstream",
        "topics": ["оптимизация энергопотребления НПЗ", "energy analytics переработки", "рекомендательная система режимов НПЗ"],
    },
    {
        "cluster_id": "legacy_09",
        "title": "Интеллектуальный мониторинг трубопроводов",
        "description": "Мониторинг midstream-инфраструктуры, аномалии и раннее предупреждение.",
        "stage": "breakthrough",
        "segment": "Midstream",
        "topics": ["интеллектуальный мониторинг трубопроводов", "автономный контроль коррозии", "anomaly detection midstream"],
    },
    {
        "cluster_id": "legacy_10",
        "title": "Геомоделирование и HPC",
        "description": "Ускорение геомоделирования и сценарных расчётов на HPC-контурах.",
        "stage": "mature",
        "segment": "Upstream",
        "topics": ["геомоделирование на HPC", "цифровое моделирование пласта", "HPC кластер геологии"],
    },
    {
        "cluster_id": "legacy_11",
        "title": "MLOps и федеративное обучение",
        "description": "Межплощадочное обучение моделей без раскрытия чувствительных данных.",
        "stage": "emerging",
        "segment": "Downstream",
        "topics": ["federated learning нефтехимии", "MLOps промышленных моделей", "data governance ML"],
    },
    {
        "cluster_id": "legacy_12",
        "title": "Системы поддержки решений на промысле",
        "description": "DSS/BI контуры KPI бригад, запасов реагентов и оперативного планирования.",
        "stage": "mature",
        "segment": "Upstream",
        "topics": ["decision support буровых KPI", "прогноз запасов реагентов", "BI контур промысла"],
    },
]

COMPANIES = [
    "Газпром нефть",
    "Роснефть",
    "Лукойл",
    "Татнефть",
    "СИБУР",
    "Зарубежнефть",
    "НОВАТЭК",
    "Транснефть",
]

SOURCES = [
    ("neftegaz.ru/science", "https://neftegaz.ru/science/legacy/{slug}"),
    ("neftegaz.ru/analisis", "https://neftegaz.ru/analisis/legacy/{slug}"),
    ("sectormedia.ru", "https://sectormedia.ru/news/neft-i-gaz/legacy/{slug}"),
    ("nprom.online/trends", "https://nprom.online/trends/legacy/{slug}"),
    ("nprom.online/market", "https://nprom.online/market/legacy/{slug}"),
    ("nprom.online/digital", "https://nprom.online/mainthemes/czifrovye-resheniya/legacy/{slug}"),
]


def _slug(text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    return digest


def build_reconstructed_corpus(seed: int = 42) -> dict[str, Any]:
    """Собрать корпус ~120 событий по 12 темам старого фокуса (март 2025 — фев 2026)."""
    rng = random.Random(seed)
    start = date(2025, 3, 1)
    end = date(2026, 2, 28)
    articles: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    memberships: list[dict[str, Any]] = []

    day_span = (end - start).days
    for theme in LEGACY_THEMES:
        n = rng.randint(8, 14)
        for i in range(n):
            company = rng.choice(COMPANIES)
            # Транснефть чаще midstream
            if theme["segment"] == "Midstream" and rng.random() < 0.35:
                company = "Транснефть"
            topic = rng.choice(theme["topics"])
            d = start + timedelta(days=rng.randint(0, day_span))
            source_name, link_tpl = SOURCES[rng.randint(0, len(SOURCES) - 1)]
            title = f"{company}: {topic} — отраслевой кейс {d.strftime('%m.%Y')}"
            text = (
                f"{company} развивает направление «{topic}» в сегменте {theme['segment']}. "
                f"В материале описаны пилот или масштабирование, прикладная задача и ожидаемый эффект. "
                f"Контекст: российский нефтегаз, открытые отраслевые публикации. "
                f"Тема кластера: {theme['title']}."
            )
            slug = _slug(f"{theme['cluster_id']}|{title}|{d.isoformat()}")
            link = link_tpl.format(slug=slug)
            article = {
                "title": title,
                "text": text,
                "datatime": d.isoformat(),
                "source": source_name,
                "link": link,
                "origin": "legacy_reconstructed",
            }
            articles.append(article)
            eid = event_id_for(link, topic)
            events.append(
                {
                    "event_id": eid,
                    "topic_label": topic,
                    "ai_summary": (
                        f"{topic}: {company} упоминает развитие технологии в контуре «{theme['title']}». "
                        f"Сегмент {theme['segment']}, период {d.isoformat()}."
                    ),
                    "company": company,
                    "company_normalized": normalize_company(company),
                    "category": theme["segment"],
                    "segment_text": text,
                    "datatime": d.isoformat(),
                    "source": source_name,
                    "link": link,
                    "article_link": link,
                }
            )
            memberships.append(
                {
                    "event_id": eid,
                    "cluster_id": theme["cluster_id"],
                    "probability": round(rng.uniform(0.72, 0.98), 3),
                }
            )

    clusters = [
        {
            "cluster_id": t["cluster_id"],
            "title": t["title"],
            "description": t["description"],
            "stage": t["stage"] if t["stage"] != "stable" else "mature",
            "segment_focus": t["segment"],
        }
        for t in LEGACY_THEMES
    ]
    return {
        "meta": {
            "note": (
                "Восстановленный корпус тем старого gartner: исходные CSV (pt._3.*) в репозитории отсутствовали. "
                "Ссылки вида /legacy/ — синтетические якоря доменов источников, не живые URL статей."
            ),
            "n_articles": len(articles),
            "n_events": len(events),
            "n_clusters": len(clusters),
        },
        "clusters": clusters,
        "articles": articles,
        "events": events,
        "memberships": memberships,
    }


def save_corpus(path: Path | None = None) -> Path:
    ensure_dirs()
    LEGACY_DIR.mkdir(parents=True, exist_ok=True)
    out = path or CORPUS_PATH
    payload = build_reconstructed_corpus()
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _load_csv_events_from_import() -> dict[str, Any] | None:
    """Если пользователь положил pt._1.2 или best_clusters CSV — импортируем их."""
    if not IMPORT_DIR.exists():
        return None
    meta = IMPORT_DIR / "pt._1.2_filtr_extract_meta.csv"
    profiles = list(IMPORT_DIR.glob("pt._3.5_cluster_profiles*.csv"))
    clustered = list(IMPORT_DIR.glob("pt._3.4_best_clusters*.csv"))
    if not meta.exists() and not clustered:
        return None

    articles: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    memberships: list[dict[str, Any]] = []
    clusters: list[dict[str, Any]] = []

    if profiles:
        with profiles[0].open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                cid = str(row.get("cluster_id") or row.get("cluster") or "").strip()
                if not cid or cid == "-1":
                    continue
                clusters.append(
                    {
                        "cluster_id": f"legacy_{cid}" if not cid.startswith("legacy_") else cid,
                        "title": normalize_text(row.get("cluster_title") or row.get("title") or f"Тема {cid}"),
                        "description": normalize_text(row.get("interpretation") or row.get("description") or ""),
                        "stage": "mature",
                        "segment_focus": normalize_text(row.get("top_category") or row.get("category") or "Upstream") or "Upstream",
                    }
                )

    source_csv = clustered[0] if clustered else meta
    with source_csv.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            title = normalize_text(row.get("title"))
            text = normalize_text(row.get("text") or row.get("ai_summary") or row.get("segment_text"))
            link = normalize_text(row.get("link") or row.get("url"))
            if not link:
                link = f"legacy://row/{_slug(title + text[:80])}"
            if not title:
                title = normalize_text(row.get("topic_label")) or "Событие"
            if not text:
                text = title
            topic = normalize_text(row.get("topic_label")) or title
            company = normalize_text(row.get("company") or row.get("company_normalized"))
            datatime = normalize_text(row.get("datatime") or row.get("publishedAt") or row.get("month"))
            source = normalize_text(row.get("source")) or "legacy-import"
            articles.append(
                {
                    "title": title,
                    "text": text,
                    "datatime": datatime,
                    "source": source,
                    "link": link,
                    "origin": "legacy_csv_import",
                }
            )
            eid = event_id_for(link, topic)
            events.append(
                {
                    "event_id": eid,
                    "topic_label": topic,
                    "ai_summary": normalize_text(row.get("ai_summary")) or text[:400],
                    "company": company,
                    "company_normalized": normalize_company(company),
                    "category": normalize_text(row.get("category")) or "Upstream",
                    "segment_text": text,
                    "datatime": datatime,
                    "source": source,
                    "link": link,
                    "article_link": link,
                }
            )
            raw_cid = str(row.get("cluster_id") or "").strip()
            if raw_cid and raw_cid != "-1":
                cid = f"legacy_{raw_cid}" if not raw_cid.startswith("legacy_") else raw_cid
                memberships.append(
                    {
                        "event_id": eid,
                        "cluster_id": cid,
                        "probability": float(row.get("cluster_probability") or 0.8),
                    }
                )

    if not clusters and memberships:
        by_c: dict[str, list[str]] = defaultdict(list)
        ev_map = {e["event_id"]: e for e in events}
        for m in memberships:
            by_c[m["cluster_id"]].append(ev_map[m["event_id"]]["topic_label"])
        for cid, topics in by_c.items():
            top = max(set(topics), key=topics.count)
            clusters.append(
                {
                    "cluster_id": cid,
                    "title": top[:1].upper() + top[1:],
                    "description": f"Импортированный кластер по теме «{top}».",
                    "stage": "mature",
                    "segment_focus": "Upstream",
                }
            )

    return {
        "meta": {"note": f"Импорт CSV из {IMPORT_DIR}", "n_articles": len(articles), "n_events": len(events), "n_clusters": len(clusters)},
        "clusters": clusters,
        "articles": articles,
        "events": events,
        "memberships": memberships,
    }


def import_payload(payload: dict[str, Any], *, replace_legacy: bool = True) -> dict[str, int]:
    init_db()
    now = utc_now()
    with connect() as conn:
        if replace_legacy:
            # удаляем только legacy_* кластеры и связанные события/статьи с origin legacy
            legacy_event_ids = [
                r["event_id"]
                for r in conn.execute(
                    "SELECT event_id FROM events WHERE link LIKE '%/legacy/%' OR link LIKE 'legacy://%'"
                ).fetchall()
            ]
            for eid in legacy_event_ids:
                conn.execute("DELETE FROM cluster_members WHERE event_id=?", (eid,))
                conn.execute("DELETE FROM events WHERE event_id=?", (eid,))
            conn.execute("DELETE FROM articles WHERE link LIKE '%/legacy/%' OR link LIKE 'legacy://%'")
            conn.execute("DELETE FROM cluster_forecasts WHERE cluster_id LIKE 'legacy_%'")
            conn.execute("DELETE FROM clusters WHERE cluster_id LIKE 'legacy_%'")

        for c in payload["clusters"]:
            conn.execute(
                """
                INSERT INTO clusters(cluster_id, title, description, stage, segment_focus,
                    innovation_score, execution_score, centroid_json, title_embedding_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?)
                ON CONFLICT(cluster_id) DO UPDATE SET
                    title=excluded.title,
                    description=excluded.description,
                    stage=excluded.stage,
                    segment_focus=excluded.segment_focus,
                    updated_at=excluded.updated_at
                """,
                (c["cluster_id"], c["title"], c.get("description") or "", c.get("stage") or "mature", c.get("segment_focus") or "Upstream", now, now),
            )

        article_ids: dict[str, str] = {}
        for a in payload["articles"]:
            aid = article_id_from_link(a["link"])
            article_ids[a["link"]] = aid
            conn.execute(
                """
                INSERT INTO articles(article_id, title, text, datatime, source, link, scraped_at, processed)
                VALUES(?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(article_id) DO UPDATE SET title=excluded.title, text=excluded.text, processed=1
                """,
                (aid, a["title"], a["text"], a.get("datatime"), a.get("source"), a["link"], now),
            )

        for e in payload["events"]:
            aid = article_ids.get(e.get("article_link") or e["link"]) or article_id_from_link(e["link"])
            conn.execute(
                """
                INSERT INTO events(event_id, article_id, topic_label, ai_summary, company, company_normalized,
                    category, segment_text, datatime, source, link, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    ai_summary=excluded.ai_summary,
                    company=excluded.company,
                    company_normalized=excluded.company_normalized,
                    category=excluded.category
                """,
                (
                    e["event_id"],
                    aid,
                    e["topic_label"],
                    e.get("ai_summary"),
                    e.get("company"),
                    e.get("company_normalized") or normalize_company(e.get("company")),
                    e.get("category") or "Upstream",
                    e.get("segment_text"),
                    e.get("datatime"),
                    e.get("source"),
                    e["link"],
                    now,
                ),
            )

        for m in payload["memberships"]:
            conn.execute(
                """
                INSERT INTO cluster_members(event_id, cluster_id, probability, is_noise, umap_x, umap_y, assigned_at)
                VALUES(?, ?, ?, 0, NULL, NULL, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    cluster_id=excluded.cluster_id,
                    probability=excluded.probability,
                    is_noise=0,
                    assigned_at=excluded.assigned_at
                """,
                (m["event_id"], m["cluster_id"], float(m.get("probability") or 0.85), now),
            )

    set_state("has_clusters", "1")
    set_state("legacy_imported_at", now)
    return {
        "clusters": len(payload["clusters"]),
        "articles": len(payload["articles"]),
        "events": len(payload["events"]),
        "memberships": len(payload["memberships"]),
    }


def run_import(*, rebuild_portal: bool = True) -> dict[str, Any]:
    ensure_dirs()
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = _load_csv_events_from_import()
    source = "csv_import"
    if payload is None:
        if not CORPUS_PATH.exists():
            save_corpus()
        payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        # refresh corpus file to latest generator
        save_corpus()
        payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        source = "reconstructed"

    stats = import_payload(payload, replace_legacy=True)
    result: dict[str, Any] = {"source": source, "import": stats, "meta": payload.get("meta")}

    # доэмбеддить + оценки/прогнозы для legacy кластеров
    result["embeddings"] = ensure_embeddings()
    result["enrich"] = enrich_clusters()
    result["forecast"] = forecast_clusters()
    result["snapshot"] = create_snapshot(manifest={"legacy_import": True, "source": source})
    result["qa"] = {"noise_ratio": build_qa_report().get("noise_ratio"), "n_clusters": build_qa_report().get("n_clusters")}
    if rebuild_portal:
        portal = build_portal_payload()
        result["portal"] = {"topics": portal["kpis"]["topics"], "events": portal["kpis"]["events"]}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Import legacy gartner themes into OilTech Radar 3.0")
    parser.add_argument("--rebuild-corpus-only", action="store_true")
    args = parser.parse_args()
    if args.rebuild_corpus_only:
        path = save_corpus()
        print(json.dumps({"corpus": str(path)}, ensure_ascii=False, indent=2))
        return 0
    result = run_import(rebuild_portal=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
