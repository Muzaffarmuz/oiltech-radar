"""Разметка science-статей направлениями (23 fine → 8 coarse).

Читает articles с flow-тегом science, пишет:
  - data/runs/science_directions/tagged.json
  - articles.science_directions_json

Запуск из корня Oil radar 4:

    python scripts/tag_science_directions.py
    python scripts/tag_science_directions.py --limit 5
    python scripts/tag_science_directions.py --heuristic-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gartner.db import connect, init_db, utc_now
from gartner.llm import LLMClient
from gartner.science_directions import (
    FINE_DIRECTIONS,
    FINE_TO_COARSE,
    aggregate_counts,
    build_direction_payload,
    heuristic_fine,
    normalize_fine,
    taxonomy_meta,
)

DEFAULT_OUT = ROOT / "data" / "runs" / "science_directions" / "tagged.json"
DEFAULT_CACHE = ROOT / "data" / "cache" / "science_directions_cache.json"
TEXT_LIMIT = 4500
CHECKPOINT_EVERY = 25

PROMPT = """Ты размечаешь одну научную/техническую статью нефтегазовой тематики.
Выбери 1–2 направления из списка ниже (точные названия, без синонимов).
Если тема про ИТ, цифровизацию, ИИ, роботов, датчики данных — ставь «ИТ и автоматизация».
Если ничего не подходит уверенно — один ближайший лейбл.

Направления:
{labels}

Верни только JSON:
{{
  "fine": ["Бурение"],
  "reason": "короткая фраза по тексту"
}}
В fine только названия из списка. Не выдумывай факты.
""".format(labels="\n".join(f"- {name}" for name in FINE_DIRECTIONS))


def log(message: str) -> None:
    print(message, file=sys.stderr)


def cache_key(title: str, text: str) -> str:
    digest = hashlib.sha256()
    digest.update(PROMPT.encode("utf-8"))
    digest.update(b"\0")
    digest.update(title.encode("utf-8"))
    digest.update(b"\0")
    digest.update(text[:TEXT_LIMIT].encode("utf-8"))
    return digest.hexdigest()


def load_cache(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def save_cache(path: Path, cache: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_science_articles(*, only_untagged: bool) -> list[dict]:
    init_db()
    rows: list[dict] = []
    with connect() as conn:
        sql = """
            SELECT article_id, title, text, datatime, source, link, flow_tags_json, science_directions_json
            FROM articles
            WHERE flow_tags_json IS NOT NULL AND flow_tags_json != '' AND flow_tags_json != '[]'
        """
        for row in conn.execute(sql).fetchall():
            try:
                tags = json.loads(row["flow_tags_json"] or "[]")
            except json.JSONDecodeError:
                continue
            if not isinstance(tags, list) or "science" not in tags:
                continue
            if only_untagged and row["science_directions_json"]:
                continue
            rows.append(
                {
                    "article_id": row["article_id"],
                    "title": str(row["title"] or ""),
                    "text": str(row["text"] or ""),
                    "datatime": str(row["datatime"] or ""),
                    "source": str(row["source"] or ""),
                    "link": str(row["link"] or ""),
                }
            )
    rows.sort(key=lambda item: (1 if item["datatime"] else 0, item["datatime"]), reverse=True)
    return rows


def parse_llm(raw: dict) -> tuple[list[str], str]:
    fine = normalize_fine(raw.get("fine") if isinstance(raw.get("fine"), list) else [])
    reason = str(raw.get("reason") or "").strip()
    return fine, reason


def request_article(client: LLMClient, article: dict) -> dict:
    return client.json_call(
        PROMPT,
        {
            "title": article["title"],
            "text": (article.get("text") or "")[:TEXT_LIMIT],
            "source": article.get("source") or "",
        },
    )


def write_checkpoint(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    report = {
        "articles": len(rows),
        "with_directions": sum(1 for row in rows if (row.get("directions") or {}).get("fine")),
        "by_coarse": {
            item["name"]: item["count"]
            for item in aggregate_counts(
                [{"directions": row.get("directions")} for row in rows], "coarse"
            )
        },
        "by_fine": {
            item["name"]: item["count"]
            for item in aggregate_counts(
                [{"directions": row.get("directions")} for row in rows], "fine"
            )
        },
        "taxonomy": taxonomy_meta(),
        "errors": sum(1 for row in rows if row.get("tag_error")),
    }
    report_path = path.with_name(path.stem + "_report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_to_db(rows: list[dict]) -> dict[str, int]:
    init_db()
    updated = 0
    skipped = 0
    now = utc_now()
    with connect() as conn:
        for row in rows:
            directions = row.get("directions")
            link = row.get("link") or ""
            if not directions or not link:
                skipped += 1
                continue
            payload = json.dumps(directions, ensure_ascii=False)
            cur = conn.execute(
                """
                UPDATE articles
                SET science_directions_json=?, science_dir_tagged_at=?
                WHERE link=?
                """,
                (payload, now, link),
            )
            updated += cur.rowcount
    return {"updated": updated, "skipped": skipped}


def summarize(rows: list[dict]) -> dict:
    fine_counter: Counter[str] = Counter()
    coarse_counter: Counter[str] = Counter()
    for row in rows:
        dirs = row.get("directions") or {}
        for label in dirs.get("fine") or []:
            fine_counter[label] += 1
        for label in dirs.get("coarse") or []:
            coarse_counter[label] += 1
    return {
        "articles": len(rows),
        "fine_top": fine_counter.most_common(15),
        "coarse": coarse_counter.most_common(),
        "errors": sum(1 for row in rows if row.get("tag_error")),
        "mapping_size": len(FINE_TO_COARSE),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Направления для science-статей (23→8).")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--cache", default=str(DEFAULT_CACHE))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--delay", type=float, default=0.15)
    parser.add_argument("--checkpoint-every", type=int, default=CHECKPOINT_EVERY)
    parser.add_argument("--only-untagged", action="store_true", help="Только без science_directions_json")
    parser.add_argument("--heuristic-only", action="store_true", help="Без LLM, только ключевые слова")
    parser.add_argument("--no-db", action="store_true", help="Не писать в articles")
    args = parser.parse_args()

    articles = load_science_articles(only_untagged=args.only_untagged)
    if args.limit > 0:
        articles = articles[: args.limit]
    if not articles:
        print("Нет science-статей для разметки", file=sys.stderr)
        return 1

    client: LLMClient | None = None
    use_llm = not args.heuristic_only
    if use_llm:
        client = LLMClient()
        if not client.enabled:
            log("LLM выключен — переключаюсь на эвристику")
            use_llm = False

    out_path = Path(args.out)
    cache_path = Path(args.cache)
    cache = load_cache(cache_path)
    tagged: list[dict] = []

    try:
        for index, article in enumerate(articles, start=1):
            key = cache_key(article["title"], article["text"])
            row = {
                "title": article["title"],
                "datatime": article["datatime"],
                "source": article["source"],
                "link": article["link"],
                "article_id": article["article_id"],
            }
            if key in cache and (cache[key].get("directions") or {}).get("fine"):
                row["directions"] = build_direction_payload(
                    cache[key]["directions"].get("fine") or [],
                    cache[key]["directions"].get("reason") or "",
                )
                log(f"{index}/{len(articles)} cache {row['directions']['fine']} {article['link']}")
            elif use_llm and client is not None:
                try:
                    raw = request_article(client, article)
                    fine, reason = parse_llm(raw)
                    if not fine:
                        fine = heuristic_fine(article["title"], article["text"])
                        reason = reason or "fallback: эвристика после пустого ответа"
                    directions = build_direction_payload(fine, reason)
                    cache[key] = {"directions": directions, "llm_raw": raw}
                    row["directions"] = directions
                    log(f"{index}/{len(articles)} llm {directions['fine']} → {directions['coarse']}")
                except Exception as exc:
                    fine = heuristic_fine(article["title"], article["text"])
                    directions = build_direction_payload(fine, f"heuristic after error: {exc}")
                    row["directions"] = directions
                    row["tag_error"] = str(exc)
                    log(f"{index}/{len(articles)} error→heuristic {fine}: {exc}")
                if args.delay:
                    time.sleep(args.delay)
            else:
                fine = heuristic_fine(article["title"], article["text"])
                directions = build_direction_payload(fine, "heuristic")
                row["directions"] = directions
                log(f"{index}/{len(articles)} heuristic {fine}")

            tagged.append(row)
            if args.checkpoint_every > 0 and index % args.checkpoint_every == 0:
                save_cache(cache_path, cache)
                write_checkpoint(out_path, tagged)
                log(f"Снимок {index}/{len(articles)}")
    finally:
        if tagged:
            save_cache(cache_path, cache)
            write_checkpoint(out_path, tagged)

    db_report = {"updated": 0, "skipped": 0}
    if not args.no_db:
        db_report = apply_to_db(tagged)

    report = summarize(tagged)
    report["db"] = db_report
    print(f"Saved {len(tagged)} -> {out_path}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
