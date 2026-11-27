"""Кластеризация новостей научных центров / патентообладателей (UMAP/HDBSCAN).

Корпус: data/runs/science_org_news/articles.jsonl
Отчёт:  data/runs/science_org_news/clusters_report.json

Не трогает IT-кластеры и patent_clusters в radar.db.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from gartner.config import CACHE_DIR, RUNS_DIR, Settings, ensure_dirs, get_settings
from gartner.llm import LLMClient
from gartner.pipeline.subcluster import compress_label

ARTICLES_JSONL = RUNS_DIR / "science_org_news" / "articles.jsonl"
REPORT_PATH = RUNS_DIR / "science_org_news" / "clusters_report.json"
EMBED_PATH = CACHE_DIR / "science_news_embeddings.npz"
MANIFEST_PATH = CACHE_DIR / "science_news_embedding_manifest.json"

CLUSTER_PROMPT = """Ты — старший аналитик нефтегазовых новостей науки и технологий.
Сформулируй ОДНУ высокоуровневую тему (3–7 слов) по группе близких новостей вузов/НИИ/компаний ТЭК.
Без названий организаций и дат.
Верни ТОЛЬКО JSON: {"name":"...","description":"1-2 предложения","confidence":0.0}
"""

SUB_PROMPT = """Ты строишь иерархическую таксономию новостных тем нефтегаза / науки.
Верни ТОЛЬКО JSON: {"cluster_name":"...","confidence":0.0}
ПРАВИЛА: 2–5 слов, НА РУССКОМ, без пустышек (цифровизация, инновации), фокус на технологии.
"""


def article_id_from_link(link: str) -> str:
    return hashlib.sha1((link or "").encode("utf-8")).hexdigest()[:16]


def article_text(title: str, text: str) -> str:
    title = (title or "").strip()
    body = (text or "").strip()
    if title and body:
        return f"{title}. {body[:1200]}"
    return title or body[:1400]


# Мусор парсинга / бытовой контент вузовских медиа — не для радара нефтегаза
_JUNK_MARKERS = (
    "begin:vcalendar",
    "vcalendar",
    "пожалуйста включите",
    "enable javascript",
    "включите javascript",
    "cookie",
    "captcha",
)
_LIFESTYLE_MARKERS = (
    "ресниц",
    "заикан",
    "йод",
    "йододефицит",
    "фитнес",
    "донорск",
    "тюрколог",
    "тумашевск",
    "наращивание",
    "эндокринолог",
    "ботаническ",
    "солдатском мешке",
    "солдатский мешок",
    "обмундир",
    "собственниками земли",
    "нерадив",
    "день открытых дверей",
    "посвящение в студенты",
    "выпускной бал",
    "квн",
)

# Сильные отраслевые маркеры: достаточно в заголовке или лиде
_OILGAS_STRONG = (
    "нефт",
    "газпром",
    "нефтегаз",
    "нефтехим",
    "месторожд",
    "скважин",
    "бурен",
    "буров",
    "гидроразрыв",
    "трубопровод",
    "нефтепровод",
    "газопровод",
    "транснефт",
    "лукойл",
    "роснефт",
    "татнефть",
    "новатэк",
    "сибур",
    "геолог",
    "геофиз",
    "сейсми",
    "углеводород",
    "drilling",
    "petroleum",
    "upstream",
)
_OILGAS_KEEP = (
    "нефт",
    "газ",
    "скважин",
    "бурен",
    "месторожд",
    "спг",
    "lng",
    "нефтехим",
    "углехим",
    "геолог",
    "геофиз",
    "патент",
    "добыч",
    "трубопровод",
    "нпз",
    "гпз",
    "роснефт",
    "газпром",
    "лукойл",
    "новатэк",
    "татнефть",
    "petroleum",
    "drilling",
    "upstream",
)


def _mojibake_ratio(text: str) -> float:
    """Доля типичных артефактов битой кодировки в заголовке."""
    if not text:
        return 0.0
    markers = text.count("\ufffd") + text.count("Ğ") + text.count("Ñ") + text.count("Ð")
    return markers / max(len(text), 1)


def is_junk_news(*, title: str, text: str = "", date: str = "", today: str | None = None) -> bool:
    """Отсев битого парсинга, календарей и бытовых вузовских новостей."""
    from datetime import date as date_cls

    title_l = (title or "").lower()
    text_l = (text or "").lower()
    blob = f"{title_l}\n{text_l}"
    if any(m in blob for m in _JUNK_MARKERS):
        return True
    if _mojibake_ratio(title or "") > 0.08 or _mojibake_ratio((title or "")[:200]) > 0.05:
        return True
    if "\ufffd" in (title or ""):
        return True
    if any(m in blob for m in _LIFESTYLE_MARKERS):
        # бытовуха вузовских медиа — вне радара, если нет сильного отраслевого сигнала в заголовке
        if not any(k in title_l for k in _OILGAS_STRONG):
            return True
    day = (date or "")[:10]
    if len(day) == 10 and day[4] == "-" and day[7] == "-":
        try:
            today_s = today or date_cls.today().isoformat()
            if day > today_s:
                return True
        except Exception:
            pass
    return False


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return vectors / norms


def _hash_embed(text: str, dim: int = 64) -> np.ndarray:
    rng = np.random.default_rng(abs(hash(text)) % (2**32))
    vec = rng.normal(size=dim).astype("float32")
    vec /= max(float(np.linalg.norm(vec)), 1e-8)
    return vec


def is_oilgas_relevant(title: str, text: str = "", *, min_hits: int = 1) -> bool:
    """Новость про нефтегаз / бурение / геологию.

    Не считаем «совпадением» случайные куски в подвале страницы
    (газета→«газе», муниципальный→«мун»). Смотрим заголовок + лид.
    """
    from gartner.custom_sources.theme import score_oilgas

    title_s = (title or "").strip()
    lead = (text or "").strip()[:900]
    title_l = title_s.lower()
    lead_blob = f"{title_s}\n{lead}".lower()

    if any(k in title_l for k in _OILGAS_STRONG):
        return True
    if any(k in lead_blob for k in _OILGAS_STRONG) and score_oilgas(lead_blob) >= 1:
        return True

    title_hits = score_oilgas(title_s)
    lead_hits = score_oilgas(lead_blob)
    need = max(1, int(min_hits))
    # заголовок сам по себе отраслевой
    if title_hits >= need:
        return True
    # в лиде нужно чуть сильнее, если заголовок «про студентов/землю»
    if lead_hits >= max(need + 1, 2):
        return True
    return False


def load_articles(
    path: Path | None = None,
    *,
    oilgas_min_hits: int = 1,
) -> list[dict[str, Any]]:
    path = path or ARTICLES_JSONL
    if not path.exists():
        return []
    by_link: dict[str, dict[str, Any]] = {}
    skipped_junk = 0
    skipped_offtopic = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            link = str(row.get("link") or "").strip()
            if not link:
                continue
            aid = article_id_from_link(link)
            title = str(row.get("title") or "").strip()
            text = str(row.get("text") or "").strip()
            if len(text) < 80 and len(title) < 20:
                continue
            # иногда title = org, text = новость
            if len(title) < 8 and text:
                title = text.split(".")[0][:180]
            if is_junk_news(title=title, text=text, date=str(row.get("datatime") or "")[:10]):
                skipped_junk += 1
                continue
            if oilgas_min_hits > 0 and not is_oilgas_relevant(
                title, text, min_hits=oilgas_min_hits
            ):
                skipped_offtopic += 1
                continue
            by_link[link] = {
                "article_id": aid,
                "title": title[:300],
                "text": text,
                "datatime": str(row.get("datatime") or "")[:10],
                "source": str(row.get("source") or ""),
                "link": link,
                "org_name": str(row.get("org_name") or "").strip(),
                "source_id": str(row.get("source_id") or ""),
            }
    print(
        f"[science-news] load_articles kept={len(by_link)} "
        f"junk={skipped_junk} offtopic={skipped_offtopic} "
        f"(oilgas_min_hits={oilgas_min_hits})",
        flush=True,
    )
    return list(by_link.values())


def _local_tfidf_embeddings(rows: list[dict[str, Any]], *, dim: int = 256) -> tuple[np.ndarray, np.ndarray]:
    from sklearn.decomposition import TruncatedSVD
    from sklearn.feature_extraction.text import TfidfVectorizer

    texts = [article_text(r.get("title") or "", r.get("text") or "") or " " for r in rows]
    ids = np.array([r["article_id"] for r in rows], dtype=str)
    if len(texts) < 3:
        emb = np.vstack([_hash_embed(t, dim=dim) for t in texts]).astype("float32")
        return emb, ids
    vectorizer = TfidfVectorizer(
        max_features=12000,
        ngram_range=(1, 2),
        min_df=2,
        max_df=0.9,
        sublinear_tf=True,
    )
    matrix = vectorizer.fit_transform(texts)
    n_comp = max(2, min(dim, matrix.shape[1] - 1, matrix.shape[0] - 1))
    svd = TruncatedSVD(n_components=n_comp, random_state=42)
    emb = svd.fit_transform(matrix).astype("float32")
    return _normalize(emb), ids


def _api_embeddings(rows: list[dict[str, Any]], client: LLMClient) -> tuple[np.ndarray, np.ndarray]:
    texts = [article_text(r.get("title") or "", r.get("text") or "") or " " for r in rows]
    ids = np.array([r["article_id"] for r in rows], dtype=str)
    vectors = np.asarray(client.embed(texts, batch_size=16), dtype="float32")
    return _normalize(vectors), ids


def ensure_embeddings(
    *,
    force: bool = False,
    local: bool = True,
    llm: LLMClient | None = None,
    oilgas_min_hits: int = 1,
) -> dict[str, Any]:
    ensure_dirs()
    rows = load_articles(oilgas_min_hits=oilgas_min_hits)
    if len(rows) < 3:
        return {"status": "skip", "reason": "not_enough_articles", "n": len(rows)}

    if EMBED_PATH.exists() and MANIFEST_PATH.exists() and not force:
        try:
            man = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            if int(man.get("n") or 0) == len(rows) and man.get("model"):
                return {"status": "cached", "n": len(rows), "model": man.get("model")}
        except Exception:
            pass

    client = llm or LLMClient()
    model = "tfidf-svd-256"
    if local or not client.enabled:
        emb, ids = _local_tfidf_embeddings(rows)
        model = f"tfidf-svd-{emb.shape[1]}"
    else:
        try:
            emb, ids = _api_embeddings(rows, client)
            model = get_settings().embedding_model
        except Exception as exc:
            print(f"[science-news] API embed fail → TF-IDF: {exc!r}", flush=True)
            emb, ids = _local_tfidf_embeddings(rows)
            model = f"tfidf-svd-{emb.shape[1]}"

    np.savez_compressed(EMBED_PATH, embeddings=emb, article_id=ids)
    MANIFEST_PATH.write_text(
        json.dumps(
            {"n": int(len(ids)), "dim": int(emb.shape[1]), "model": model, "source": str(ARTICLES_JSONL)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"status": "ok", "n": int(len(ids)), "dim": int(emb.shape[1]), "model": model}


def load_embeddings() -> tuple[np.ndarray, np.ndarray]:
    if not EMBED_PATH.exists():
        return np.zeros((0, 64), dtype="float32"), np.array([], dtype=str)
    payload = np.load(EMBED_PATH, allow_pickle=True)
    return payload["embeddings"].astype("float32"), payload["article_id"].astype(str)


def _svd_xy(emb: np.ndarray) -> np.ndarray:
    from sklearn.decomposition import TruncatedSVD

    k = 2 if emb.shape[1] >= 2 else 1
    svd = TruncatedSVD(n_components=k, random_state=42)
    out = svd.fit_transform(emb)
    if out.shape[1] == 1:
        out = np.column_stack([out[:, 0], np.zeros(len(out))])
    return out


def _fallback_kmeans(emb: np.ndarray, n_clusters: int) -> tuple[np.ndarray, np.ndarray]:
    from sklearn.cluster import MiniBatchKMeans

    k = max(2, min(n_clusters, len(emb)))
    km = MiniBatchKMeans(n_clusters=k, random_state=42, n_init=10, batch_size=min(256, len(emb)))
    labels = km.fit_predict(emb)
    # fake probabilities
    probs = np.ones(len(labels), dtype="float32")
    return labels.astype(int), probs


def _heuristic_name(titles: list[str]) -> tuple[str, str]:
    if not titles:
        return "Новостное направление", "Кластер близких новостей по эмбеддингам."
    stop = {
        "способ", "устройство", "система", "метод", "для", "при", "или", "его", "их",
        "новости", "пресс", "релиз", "компании", "года", "года", "and", "the", "of",
        "прошел", "прошла", "состоялось", "более", "также",
    }
    words: Counter[str] = Counter()
    for t in titles:
        for w in re.findall(r"[А-Яа-яA-Za-z]{4,}", t or ""):
            wl = w.lower()
            if wl not in stop:
                words[wl] += 1
    if words:
        top = [w for w, _ in words.most_common(3)]
        name = " ".join(top)[:48]
        name = name[:1].upper() + name[1:]
    else:
        top_title = titles[0]
        name = top_title if len(top_title) <= 48 else top_title[:45] + "…"
    return name, f"Группа новостей вокруг темы «{name}»."


def run_cluster(
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    *,
    oilgas_min_hits: int = 1,
    n_clusters: int | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    client = llm or LLMClient(settings)
    embeddings, article_ids = load_embeddings()
    if len(article_ids) < 3:
        return {"status": "skip", "reason": "not_enough", "n": int(len(article_ids))}

    rows = {r["article_id"]: r for r in load_articles(oilgas_min_hits=oilgas_min_hits)}
    # эмбеддинги могли быть по старой выборке — оставляем пересечение
    keep_ids = set(rows.keys())
    if keep_ids:
        mask = np.array([str(a) in keep_ids for a in article_ids], dtype=bool)
        if mask.any() and int(mask.sum()) < len(article_ids):
            embeddings = embeddings[mask]
            article_ids = article_ids[mask]
            print(
                f"[science-news] align embed∩oilgas → {len(article_ids)} articles",
                flush=True,
            )
    mcs = int(settings.hdbscan_min_cluster_size)
    if len(article_ids) < 40:
        mcs = min(mcs, max(3, len(article_ids) // 5))
    if len(article_ids) >= 400:
        mcs = max(mcs, 8)

    model_name = ""
    if MANIFEST_PATH.exists():
        try:
            model_name = str(json.loads(MANIFEST_PATH.read_text(encoding="utf-8")).get("model") or "")
        except Exception:
            model_name = ""
    skip_umap = model_name.startswith("tfidf-svd")
    n_neighbors = min(int(settings.umap_n_neighbors), max(2, len(article_ids) - 1))
    method = "umap_hdbscan"

    # HDBSCAN на этом корпусе/Windows зависает → стабильный MiniBatchKMeans
    # (тот же fallback, что у патентного пайплайна при сбое HDBSCAN).
    _ = (skip_umap, n_neighbors)  # UMAP/HDBSCAN params reserved
    xy = _svd_xy(embeddings)
    # ~1 кластер на 35 статей, потолок 28 (иначе темы дробятся слишком мелко)
    auto_k = max(8, min(28, max(2, len(article_ids) // 35)))
    k = int(n_clusters) if n_clusters and int(n_clusters) >= 2 else auto_k
    k = max(2, min(k, max(2, len(article_ids) // 2)))
    print(f"[science-news] MiniBatchKMeans k={k} (auto={auto_k})", flush=True)
    labels, probs = _fallback_kmeans(embeddings, n_clusters=k)
    method = "minibatch_kmeans"

    use_llm = bool(client.enabled)
    print(
        f"[science-news] naming clusters ({'llm:' + settings.llm_model if use_llm else 'heuristic'})",
        flush=True,
    )
    if use_llm:
        print(f"[science-news] llm base_url={settings.base_url}", flush=True)
    cluster_titles: dict[int, tuple[str, str]] = {}
    label_ids = sorted({int(x) for x in labels.tolist() if int(x) >= 0})
    for i, label in enumerate(label_ids, start=1):
        mask = labels == label
        titles = []
        abstracts = []
        for aid in article_ids[mask]:
            row = rows.get(str(aid)) or {}
            if row.get("title"):
                titles.append(row["title"])
            if row.get("text"):
                abstracts.append(str(row["text"])[:240])
        if not use_llm:
            cluster_titles[label] = _heuristic_name(titles[:40])
            continue
        try:
            print(f"[science-news] llm name {i}/{len(label_ids)} sn{label}…", flush=True)
            named = client.json_call(
                CLUSTER_PROMPT,
                {
                    "titles": titles[:18],
                    "abstracts": abstracts[:10],
                },
                max_retries=2,
            )
            name = str(named.get("name") or "").strip()
            desc = str(named.get("description") or "").strip()
            if not name:
                raise ValueError("empty LLM name")
            cluster_titles[label] = (name[:80], desc or f"Группа новостей вокруг темы «{name}».")
        except Exception as exc:
            print(f"[science-news] llm name failed sn{label}: {exc}", flush=True)
            cluster_titles[label] = _heuristic_name(titles[:40])

    # подкластеры: KMeans 2–4 + LLM-имена (или эвристика)
    print(
        f"[science-news] subclusters (kmeans + {'llm' if use_llm else 'heuristic'})",
        flush=True,
    )
    min_parent = max(12, int(settings.subcluster_min_parent_size))
    min_sub = int(settings.subcluster_min_size)
    id_to_idx = {str(aid): i for i, aid in enumerate(article_ids)}
    sub_by_parent: dict[str, list[dict[str, Any]]] = {}
    member_sub: dict[str, tuple[str | None, int | None, str | None]] = {}

    from sklearn.cluster import MiniBatchKMeans

    parent_labels = sorted({int(x) for x in labels.tolist() if int(x) >= 0})
    sub_name_jobs = 0
    for label in parent_labels:
        cid = f"sn{label}"
        mask = labels == label
        n_members = int(mask.sum())
        if n_members < min_parent:
            continue
        local_ids = [str(a) for a in article_ids[mask]]
        titles = [(rows.get(a) or {}).get("title") or "" for a in local_ids]
        texts = [(rows.get(a) or {}).get("text") or "" for a in local_ids]
        idx = np.array([id_to_idx[a] for a in local_ids], dtype=int)
        local_emb = embeddings[idx]
        k_sub = 2 if n_members < 40 else (3 if n_members < 80 else 4)
        k_sub = min(k_sub, max(2, n_members // max(min_sub, 2)))
        if k_sub < 2:
            continue
        try:
            km = MiniBatchKMeans(
                n_clusters=k_sub, random_state=42, n_init=8, batch_size=min(128, n_members)
            )
            sl = km.fit_predict(local_emb)
        except Exception:
            continue
        local_label_ids = sorted({int(x) for x in sl.tolist()})
        subs: list[dict[str, Any]] = []
        for lid in local_label_ids:
            smask = sl == lid
            if int(smask.sum()) < min_sub:
                continue
            sub_titles = [titles[i] for i, ok in enumerate(smask.tolist()) if ok]
            sub_abstracts = [str(texts[i])[:200] for i, ok in enumerate(smask.tolist()) if ok]
            sub_name = compress_label(_heuristic_name(sub_titles)[0])
            if use_llm:
                sub_name_jobs += 1
                try:
                    print(
                        f"[science-news] llm sub-name {sub_name_jobs} {cid}_s{lid}…",
                        flush=True,
                    )
                    named = client.json_call(
                        SUB_PROMPT,
                        {
                            "titles": sub_titles[:14],
                            "abstracts": sub_abstracts[:8],
                            "parent_title": cluster_titles.get(label, ("", ""))[0],
                        },
                        max_retries=2,
                    )
                    llm_name = str(
                        named.get("cluster_name") or named.get("name") or ""
                    ).strip()
                    if llm_name:
                        sub_name = compress_label(llm_name)
                except Exception as exc:
                    print(
                        f"[science-news] llm sub-name failed {cid}_s{lid}: {exc}",
                        flush=True,
                    )
            sid = f"{cid}_s{lid}"
            subs.append(
                {
                    "id": sid,
                    "local_id": lid,
                    "title": sub_name,
                    "member_count": int(smask.sum()),
                }
            )
            for i, ok in enumerate(smask.tolist()):
                if ok:
                    member_sub[local_ids[i]] = (sid, lid, sub_name)
        if len(subs) >= 2:
            sub_by_parent[cid] = sorted(subs, key=lambda s: -s["member_count"])
    print(f"[science-news] parents_with_subs={len(sub_by_parent)}", flush=True)

    # build index + clusters
    clusters_out: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for label in labels.tolist():
        if int(label) >= 0:
            counts[f"sn{int(label)}"] += 1

    for label in sorted(counts.keys(), key=lambda c: -counts[c]):
        lid = int(label.replace("sn", ""))
        title, desc = cluster_titles.get(lid, (f"Тема {label}", ""))
        clusters_out.append(
            {
                "id": label,
                "title": title,
                "description": desc,
                "member_count": int(counts[label]),
                "subclusters": sub_by_parent.get(label, []),
            }
        )

    # org type map from unique_orgs
    org_type_map: dict[str, str] = {}
    unique_path = RUNS_DIR / "patents" / "unique_orgs.json"
    if unique_path.exists():
        try:
            for item in json.loads(unique_path.read_text(encoding="utf-8")).get("items") or []:
                org_type_map[item.get("canonical_name") or ""] = str(item.get("org_type") or "")
        except Exception:
            pass

    org_counter: Counter[str] = Counter()
    science_counter: Counter[str] = Counter()
    index: list[dict[str, Any]] = []
    for aid, label, prob, x, y in zip(article_ids, labels, probs, xy[:, 0], xy[:, 1], strict=False):
        row = rows.get(str(aid)) or {}
        is_noise = 1 if int(label) < 0 else 0
        cid = None if is_noise else f"sn{int(label)}"
        ctitle = None
        if cid and int(label) in cluster_titles:
            ctitle = cluster_titles[int(label)][0]
        sid, s_local, s_title = member_sub.get(str(aid), (None, None, None))
        org = row.get("org_name") or ""
        org_names = [org] if org else []
        if org:
            org_counter[org] += 1
            otype = org_type_map.get(org) or ""
            if otype in ("university", "nii"):
                science_counter[org] += 1
        date = str(row.get("datatime") or "")[:10]
        index.append(
            {
                "patent_id": str(aid),  # совместимость с UI патентов
                "article_id": str(aid),
                "identity": row.get("source") or "",
                "title": (row.get("title") or "")[:180],
                "abstract": (row.get("text") or "")[:1200],
                "date": date,
                "date_norm": date,
                "patentee": org[:120],
                "link": row.get("link") or "",
                "source": row.get("source") or "",
                "cluster_id": cid,
                "cluster_title": ctitle,
                "sub_cluster_id": sid,
                "sub_cluster_title": s_title,
                "sub_local_id": s_local,
                "is_noise": is_noise,
                "org_names": org_names,
                "probability": float(prob),
                "umap_x": float(x),
                "umap_y": float(y),
            }
        )

    index.sort(key=lambda item: (1 if item.get("date_norm") else 0, item.get("date_norm") or ""), reverse=True)

    by_month_counter: Counter[str] = Counter()
    for item in index:
        month = (item.get("date_norm") or "")[:7]
        if len(month) == 7:
            by_month_counter[month] += 1

    science_orgs = [
        {"name": name, "org_type": org_type_map.get(name) or "unknown", "patent_count": count}
        for name, count in sorted(science_counter.items(), key=lambda p: (-p[1], p[0].lower()))
    ]
    filter_orgs = [
        {"name": name, "patent_count": count}
        for name, count in sorted(org_counter.items(), key=lambda p: (-p[1], p[0].lower()))
    ]

    report = {
        "source": "science_news_clusters",
        "mode": "news",
        "method": method,
        "n_articles": len(index),
        "n_clusters": len(clusters_out),
        "n_subclusters": sum(len(c.get("subclusters") or []) for c in clusters_out),
        "noise": int(sum(1 for i in index if i.get("is_noise"))),
        "min_cluster_size": mcs,
        "articles": len(index),
        "patents": {
            "total": len(index),
            "members": len(index),
            "clustered": int(sum(1 for i in index if not i.get("is_noise"))),
            "noise": int(sum(1 for i in index if i.get("is_noise"))),
        },
        "by_month": [
            {"month": m, "count": by_month_counter[m]} for m in sorted(by_month_counter, reverse=True)
        ],
        "clusters": clusters_out,
        "science_orgs": {
            "total": len(science_orgs),
            "items": science_orgs,
            "note": "Вузы и НИИ среди источников новостей (по org_name из скрапа).",
        },
        "filter_orgs": filter_orgs,
        "index": index,
        "note": "Поток «Наука · Новости»: кластеры пресс-релизов вузов/НИИ/компаний ТЭК (UMAP/HDBSCAN).",
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "ok",
        "method": method,
        "n_articles": len(index),
        "n_clusters": len(clusters_out),
        "n_subclusters": report["n_subclusters"],
        "noise": report["noise"],
        "report": str(REPORT_PATH),
    }


def run_science_news_cluster_pipeline(
    *,
    force_embeddings: bool = False,
    local_embeddings: bool = True,
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    oilgas_min_hits: int = 1,
    n_clusters: int | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    client = llm or LLMClient(settings)
    emb = ensure_embeddings(
        force=force_embeddings,
        local=local_embeddings,
        llm=client,
        oilgas_min_hits=oilgas_min_hits,
    )
    cluster = run_cluster(
        settings=settings,
        llm=client,
        oilgas_min_hits=oilgas_min_hits,
        n_clusters=n_clusters,
    )
    return {"embeddings": emb, "cluster": cluster}


def _current_month() -> str:
    from datetime import date as date_cls

    return date_cls.today().isoformat()[:7]


def _filter_news_index(index: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Живой отсев мусора / оффтопика + будущих дат без пересборки кластеров."""
    from datetime import date as date_cls

    today = date_cls.today().isoformat()
    out: list[dict[str, Any]] = []
    for item in index:
        title = str(item.get("title") or "")
        abstract = str(item.get("abstract") or "")
        day = str(item.get("date_norm") or item.get("date") or "")[:10]
        if is_junk_news(title=title, text=abstract, date=day, today=today):
            continue
        if not is_oilgas_relevant(title, abstract, min_hits=1):
            continue
        out.append(item)
    return out


def _recount_months(index: list[dict[str, Any]]) -> list[dict[str, int]]:
    """Месяцы только до текущего (включительно)."""
    cap = _current_month()
    counter: Counter[str] = Counter()
    for item in index:
        month = (item.get("date_norm") or item.get("date") or "")[:7]
        if len(month) == 7 and month <= cap:
            counter[month] += 1
    return [{"month": m, "count": counter[m]} for m in sorted(counter, reverse=True)]


def science_news_flow_payload() -> dict[str, Any]:
    """Тот же контракт, что science_flow_payload (патенты), но по новостям."""
    if not REPORT_PATH.exists():
        return {
            "source": "science_news_clusters",
            "mode": "news",
            "articles": 0,
            "patents": {"total": 0, "members": 0, "clustered": 0, "noise": 0},
            "n_clusters": 0,
            "n_subclusters": 0,
            "by_month": [],
            "clusters": [],
            "science_orgs": {"total": 0, "items": [], "note": ""},
            "filter_orgs": [],
            "index": [],
            "note": "Нет clusters_report.json — сначала: python scripts/cluster_science_news.py",
        }
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    filtered = _filter_news_index(list(report.get("index") or []))
    # пересчёт org / month по очищенному индексу; кластеры не трогаем
    org_counter: Counter[str] = Counter()
    for item in filtered:
        for name in item.get("org_names") or []:
            if name:
                org_counter[name] += 1
    filter_orgs = [
        {"name": name, "patent_count": count}
        for name, count in sorted(org_counter.items(), key=lambda p: (-p[1], p[0].lower()))
    ]
    # member_count в карточке кластера — по отфильтрованной выборке
    by_cluster: Counter[str] = Counter()
    for item in filtered:
        cid = item.get("cluster_id")
        if cid:
            by_cluster[str(cid)] += 1
    clusters = []
    for c in report.get("clusters") or []:
        cid = str(c.get("id") or "")
        n = int(by_cluster.get(cid) or 0)
        if n <= 0:
            continue
        row = dict(c)
        row["member_count"] = n
        clusters.append(row)

    slim_index = []
    for item in filtered:
        slim = dict(item)
        slim.pop("abstract", None)
        slim_index.append(slim)

    report["index"] = slim_index
    report["clusters"] = clusters
    report["filter_orgs"] = filter_orgs
    report["by_month"] = _recount_months(filtered)
    report["n_clusters"] = len(clusters)
    report["articles"] = len(slim_index)
    report["patents"] = {
        "total": len(slim_index),
        "members": len(slim_index),
        "clustered": sum(1 for i in slim_index if not i.get("is_noise")),
        "noise": sum(1 for i in slim_index if i.get("is_noise")),
    }
    report["mode"] = "news"
    report["note"] = (
        "Поток «Наука · Новости»: пресс-релизы вузов/НИИ/компаний ТЭК. "
        "Бытовой и битый контент отфильтрован; будущие месяцы скрыты."
    )
    return report


def science_news_detail(article_id: str) -> dict[str, Any] | None:
    if not REPORT_PATH.exists():
        return None
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    for item in report.get("index") or []:
        if item.get("article_id") == article_id or item.get("patent_id") == article_id:
            if is_junk_news(
                title=str(item.get("title") or ""),
                text=str(item.get("abstract") or ""),
                date=str(item.get("date") or ""),
            ):
                return None
            orgs = [{"name": n} for n in (item.get("org_names") or [])]
            return {
                "patent_id": item.get("patent_id") or article_id,
                "article_id": item.get("article_id") or article_id,
                "identity": item.get("identity") or item.get("source") or "",
                "title": item.get("title") or "",
                "abstract": item.get("abstract") or "",
                "date": item.get("date") or "",
                "patentee": item.get("patentee") or "",
                "link": item.get("link") or "",
                "ipc": "",
                "cluster_id": item.get("cluster_id"),
                "cluster_title": item.get("cluster_title"),
                "sub_cluster_id": item.get("sub_cluster_id"),
                "sub_cluster_title": item.get("sub_cluster_title"),
                "sub_local_id": item.get("sub_local_id"),
                "orgs": orgs,
                "kind": "news",
            }
    return None
