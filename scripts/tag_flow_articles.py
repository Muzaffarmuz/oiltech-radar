"""LLM-разметка статей метками потоков → data/runs/flow_tags/*.json.

Пайплайн (gartner.pipeline.tag_flows) импортирует эти файлы в articles.flow_tags_json.
Портал /api/flows/* читает уже из БД после merge + tag_flows.

Запуск из корня Oil radar 4. По умолчанию — статьи 2026 года,
с Интерфакса одна новость на день:

    python scripts/tag_flow_articles.py

Короткий срез: --limit 30. Все годы: --year 0. Весь Интерфакс: --interfax-per-day 0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gartner.flow_tags import DIGITAL_RULE, DIGITAL_TAG, FLOW_TAGS, normalize_flow_tags
from gartner.llm import LLMClient

DEFAULT_INPUTS = [
    ROOT / "data" / "manual_sources" / "cbr_news.json",
    ROOT / "data" / "manual_sources" / "interfax_news.json",
    ROOT / "data" / "manual_sources" / "prav_tatarstan_news.json",
    ROOT / "data" / "manual_sources" / "rosenergo_news.json",
]
DEFAULT_OUT = ROOT / "data" / "runs" / "flow_tags" / "tagged.json"
DEFAULT_CACHE = ROOT / "data" / "cache" / "flow_tags_cache.json"
TEXT_LIMIT = 5000
CHECKPOINT_EVERY = 50

PROMPT = """Ты размечаешь одну уже скачанную статью метками потоков OilTech Radar.
У статьи может быть несколько меток. Если ни одна не подходит, верни пустой список.
Статью не выбрасывай и не пересказывай.

Потоки:
{flows}

Дополнительная метка, её ставят вместе с потоками, а не вместо них:
- {digital}: {digital_rule}

Верни только JSON:
{{
  "tags": ["news", "policy"],
  "reasons": {{
    "news": "одна короткая фраза, почему эта метка",
    "policy": "одна короткая фраза, почему эта метка"
  }}
}}
В tags только коды из списка выше. В reasons только те коды, которые попали в tags.
Ничего не придумывай: если в тексте нет основания, метку не ставь.
""".format(
    flows="\n".join(f"- {code}: {text}" for code, text in FLOW_TAGS.items()),
    digital=DIGITAL_TAG,
    digital_rule=DIGITAL_RULE,
)


def log(message: str) -> None:
    print(message, file=sys.stderr)


def load_articles(paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"{path} должен быть JSON-массивом статей")
        for item in payload:
            link = str(item.get("link") or "").strip()
            title = str(item.get("title") or "").strip()
            if not title or not link or link in seen:
                continue
            seen.add(link)
            rows.append(
                {
                    "title": title,
                    "text": str(item.get("text") or ""),
                    "datatime": str(item.get("datatime") or ""),
                    "source": str(item.get("source") or ""),
                    "link": link,
                }
            )
    return rows


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


def append_llm_backup(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def load_llm_backup(path: Path) -> dict[str, dict]:
    found: dict[str, dict] = {}
    if not path.exists():
        return found
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = str(item.get("key") or "")
        tags = item.get("flow_tags")
        if not key or not isinstance(tags, list):
            continue
        found[key] = {
            "flow_tags": tags,
            "tag_reasons": item.get("tag_reasons") or {},
            "llm_raw": item.get("llm_raw"),
        }
    return found


def tags_only(entry: dict) -> dict:
    return {
        "flow_tags": entry.get("flow_tags") or [],
        "tag_reasons": entry.get("tag_reasons") or {},
    }


def parse_tags(raw: dict) -> tuple[list[str], dict[str, str]]:
    tags = raw.get("tags") or []
    if not isinstance(tags, list):
        raise ValueError("tags должен быть списком")
    cleaned = normalize_flow_tags([str(tag).strip() for tag in tags if str(tag).strip()])
    reasons_raw = raw.get("reasons") or {}
    reasons: dict[str, str] = {}
    if isinstance(reasons_raw, dict):
        for tag in cleaned:
            reason = str(reasons_raw.get(tag) or "").strip()
            if reason:
                reasons[tag] = reason
    return cleaned, reasons


def request_article(client: LLMClient, article: dict) -> dict:
    text = article["text"]
    if len(text) > TEXT_LIMIT:
        text = text[:TEXT_LIMIT]
    return client.json_call(
        PROMPT,
        {
            "title": article["title"],
            "source": article["source"],
            "datatime": article["datatime"],
            "text": text,
        },
    )


def is_interfax(article: dict) -> bool:
    source = str(article.get("source") or "").lower().removeprefix("www.")
    return source == "interfax.ru"


def one_interfax_per_day(articles: list[dict], per_day: int) -> list[dict]:
    """Оставляет первые per_day статей Интерфакса на каждую дату. Остальные источники не трогает."""
    if per_day <= 0:
        return articles
    kept_on_day: Counter[str] = Counter()
    kept: list[dict] = []
    for row in articles:
        if not is_interfax(row):
            kept.append(row)
            continue
        day = str(row.get("datatime") or "")[:10]
        if kept_on_day[day] >= per_day:
            continue
        kept_on_day[day] += 1
        kept.append(row)
    return kept


def summarize(rows: list[dict]) -> dict:
    counts: Counter[str] = Counter()
    by_source: dict[str, Counter[str]] = {}
    multi = 0
    unlabeled = 0
    errors = 0
    for row in rows:
        tags = row.get("flow_tags") or []
        source = row.get("source") or "(без источника)"
        by_source.setdefault(source, Counter())
        if row.get("tag_error"):
            errors += 1
        if not tags:
            unlabeled += 1
            by_source[source]["(без потока)"] += 1
        else:
            if len(tags) > 1:
                multi += 1
            for tag in tags:
                counts[tag] += 1
                by_source[source][tag] += 1
    return {
        "articles": len(rows),
        "unlabeled": unlabeled,
        "multi_tag": multi,
        "errors": errors,
        "by_tag": dict(counts),
        "by_source": {source: dict(counter) for source, counter in sorted(by_source.items())},
    }


def write_checkpoint(out_path: Path, rows: list[dict]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = out_path.with_suffix(out_path.suffix + ".tmp")
    temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(out_path)
    report_path = out_path.with_name(out_path.stem + "_report.json")
    report_tmp = report_path.with_suffix(report_path.suffix + ".tmp")
    report_tmp.write_text(json.dumps(summarize(rows), ensure_ascii=False, indent=2), encoding="utf-8")
    report_tmp.replace(report_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Поставить статьям метки потоков через LLM.")
    parser.add_argument("--input", action="append", default=[], help="JSON со статьями. Можно указать несколько раз.")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--cache", default=str(DEFAULT_CACHE))
    parser.add_argument("--year", type=int, default=2026, help="Брать статьи только этого года. 0 — все годы.")
    parser.add_argument("--interfax-per-day", type=int, default=1, help="Сколько новостей Интерфакса оставлять на один день. 0 — все.")
    parser.add_argument("--limit", type=int, default=0, help="Сколько статей отправить в модель после фильтров. 0 — все отобранные.")
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--checkpoint-every", type=int, default=CHECKPOINT_EVERY, help="Как часто записывать файл со всеми метками.")
    args = parser.parse_args()

    paths = [Path(item) for item in args.input] if args.input else list(DEFAULT_INPUTS)
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        print("Нет файла: " + "; ".join(missing), file=sys.stderr)
        return 2

    articles = load_articles(paths)
    if args.year > 0:
        prefix = f"{args.year}-"
        before = len(articles)
        articles = [row for row in articles if str(row.get("datatime") or "").startswith(prefix)]
        log(f"Год {args.year}: {len(articles)} из {before}")
    before_interfax = sum(1 for row in articles if is_interfax(row))
    articles = one_interfax_per_day(articles, args.interfax_per_day)
    if args.interfax_per_day > 0:
        after_interfax = sum(1 for row in articles if is_interfax(row))
        log(f"Интерфакс: {after_interfax} из {before_interfax}, не больше {args.interfax_per_day} за день")
    if args.limit > 0:
        articles = articles[: args.limit]
    if not articles:
        print("Нет статей для разметки", file=sys.stderr)
        return 1

    client = LLMClient()
    if not client.enabled:
        print("Модель выключена: проверьте API_KEY в .env и FORCE_HEURISTIC=0", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    backup_path = out_path.with_name("llm_responses.jsonl")
    cache_path = Path(args.cache)
    cache = load_cache(cache_path)
    restored = 0
    for key, entry in load_llm_backup(backup_path).items():
        if key not in cache:
            cache[key] = entry
            restored += 1
    if restored:
        log(f"Из бэкапа ответов восстановлено {restored}")

    tagged: list[dict] = []
    try:
        for index, article in enumerate(articles, start=1):
            key = cache_key(article["title"], article["text"])
            row = dict(article)
            if key in cache:
                row.update(tags_only(cache[key]))
                log(f"{index}/{len(articles)} cache {row.get('flow_tags')} {article['link']}")
            else:
                try:
                    raw = request_article(client, article)
                    try:
                        tags, reasons = parse_tags(raw)
                    except Exception as exc:
                        append_llm_backup(
                            backup_path,
                            {
                                "key": key,
                                "link": article["link"],
                                "title": article["title"],
                                "source": article["source"],
                                "datatime": article["datatime"],
                                "llm_raw": raw,
                                "parse_error": str(exc),
                            },
                        )
                        raise
                    result = {"flow_tags": tags, "tag_reasons": reasons, "llm_raw": raw}
                    cache[key] = result
                    row.update(tags_only(result))
                    append_llm_backup(
                        backup_path,
                        {
                            "key": key,
                            "link": article["link"],
                            "title": article["title"],
                            "source": article["source"],
                            "datatime": article["datatime"],
                            "llm_raw": raw,
                            "flow_tags": tags,
                            "tag_reasons": reasons,
                        },
                    )
                    log(f"{index}/{len(articles)} keep {tags or '(без потока)'} {article['link']}")
                except Exception as exc:
                    row["flow_tags"] = []
                    row["tag_reasons"] = {}
                    row["tag_error"] = str(exc)
                    log(f"{index}/{len(articles)} error {article['link']}: {exc}")
                if args.delay:
                    time.sleep(args.delay)
            tagged.append(row)
            if args.checkpoint_every > 0 and index % args.checkpoint_every == 0:
                save_cache(cache_path, cache)
                write_checkpoint(out_path, tagged)
                log(f"Снимок {index}/{len(articles)} -> {out_path}")
    finally:
        if tagged:
            save_cache(cache_path, cache)
            write_checkpoint(out_path, tagged)

    report = summarize(tagged)
    print(f"Saved {len(tagged)} items -> {out_path}")
    print(f"LLM backup -> {backup_path}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
