"""Фильтр корпуса Наука: ключи → Lab LLM (нефтегаз / бурение / геология).

Этапы:
  1) загрузка articles.jsonl
  2) эвристика (junk + oilgas keywords)
  3) LLM keep/drop по оставшимся
  4) запись articles_oilgas.jsonl (+ опционально --apply → articles.jsonl)

  python scripts/filter_science_org_news_lab.py
  python scripts/filter_science_org_news_lab.py --apply
  python scripts/filter_science_org_news_lab.py --resume --workers 6
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts._lab_credentials import lab_base_url, lab_api_key, lab_model, ensure_no_proxy
ensure_no_proxy()
# --- Lab LLM: явные креды ---
BASE_URL = lab_base_url()
API_KEY = lab_api_key()
MODEL_NAME = "qwen3-32b"
# -----------------------------


from gartner.config import Settings  # noqa: E402
from gartner.llm import LLMClient  # noqa: E402
from gartner.pipeline.science_news_cluster import (  # noqa: E402
    ARTICLES_JSONL,
    article_id_from_link,
    is_junk_news,
    is_oilgas_relevant,
)

OUT_DIR = ARTICLES_JSONL.parent
OUT_JSONL = OUT_DIR / "articles_oilgas.jsonl"
DECISIONS_PATH = OUT_DIR / "filter_oilgas_llm_decisions.jsonl"
SUMMARY_PATH = OUT_DIR / "filter_oilgas_summary.json"

FILTER_PROMPT = """
Ты — бинарный фильтр новостей для отраслевого радара нефтегаза РФ.
Область покрытия: добыча, бурение, геология и геофизика, переработка,
трубопроводы и транспорт углеводородов, СПГ, нефтесервис, отраслевая
наука и технологии ТЭК.

Задача: по заголовку и тексту новости решить, относится ли она
к этой области по СУТИ, а не по упоминанию слов.

================================================================
ФОРМАТ ОТВЕТА
================================================================
Верни ТОЛЬКО валидный JSON без markdown-обёртки, без пояснений
вне JSON:
{"keep": true | false, "reason": "<до 120 символов, по-русски>"}

Поле reason — короткое обоснование, а не пересказ новости.

================================================================
keep = true
================================================================
Новость по сути про одно или несколько из перечисленного:
- разведка, добыча, бурение, геология, геофизика, сейсмика;
- обустройство месторождений, промысловая инфраструктура;
- переработка нефти и газа, НПЗ, нефтехимия;
- магистральные и промысловые трубопроводы, транспорт УВ;
- СПГ: производство, сжижение, регазификация, терминалы, танкеры-газовозы;
- нефтесервис, буровые подрядчики, оборудование для отрасли;
- отраслевая наука, R&D, технологии и инновации для ТЭК;
- отраслевая экономика, регуляторика, санкции, цены, сделки M&A,
  кадры и подготовка специалистов — но привязанные к нефтегазу;
- аварии, ЧП, экология — если касаются объектов нефтегаза.

Критерий: если убрать из новости слово «нефть/газ», смысл
и отраслевая ценность сохранятся.

================================================================
keep = false
================================================================
Новость формально содержит отраслевые слова, но по сути не про отрасль:
- вузовские и корпоративные мероприятия без отраслевого содержания:
  студенческие конкурсы, дни открытых дверей, юбилеи кафедр,
  посвящение в студенты, КВН, спартакиады, субботники;
- спорт, культура, досуг, ЖКХ, благоустройство, земельные вопросы;
- общие новости вуза или холдинга, где нефтегаз — только в названии
  организации, в подвале сайта или в списке партнёров;
- кадровые назначения без отраслевой повестки
  (например, «избран новый декан факультета»);
- инфоповоды про награды, грамоты, благодарности, визиты делегаций
  без содержательной части про нефтегаз;
- пресс-релизы про социальные проекты, стипендии, гранты
  без технологической или производственной привязки;
- новости про другие отрасли, где нефтегаз упомянут лишь для сравнения
  или как общий фон.

Критерий: если убрать из новости отраслевые слова, останется
пустое место — значит, отраслевого содержания нет.

================================================================
ПОГРАНИЧНЫЕ СЛУЧАИ
================================================================
- Научная статья или вуз, но тема — бурение, геология, переработка,
  технологии ТЭК → keep = true.
- Вуз, но тема — студенческий фестиваль, спорт, культура → keep = false.
- Компания нефтегаза, но новость — про юбилей или награду
  без производственного содержания → keep = false.
- Компания не из нефтегаза, но новость — про поставку оборудования
  для бурения или переработки → keep = true.
- Общая новость про энергетику, но речь про ВИЭ, уголь, атом
  без связи с углеводородами → keep = false.
- Регуляторика и налоги в ТЭК → keep = true, если касается
  нефтегаза напрямую.

================================================================
ЖЁСТКИЕ ПРАВИЛА
================================================================
1. Решай по смыслу, а не по наличию ключевых слов.
2. Не додумывай контекст, которого нет в тексте.
3. Если новость на границе и сомневаешься — keep = false
   (радар должен отсекать шум).
4. Ответ — ровно один JSON-объект с двумя полями.
5. Никакого markdown, никаких ```json-обёрток, никаких комментариев
   до или после JSON.
6. reason — не длиннее 120 символов, по-русски, без точки в конце.

================================================================
ПРИМЕРЫ
================================================================

Вход: «На Ямале пробурили первую скважину на новом кластере
Восточно-Мессояхского месторождения».
Выход: {"keep": true, "reason": "бурение на месторождении, профильная новость"}

Вход: «Студенты нефтегазового вуза победили в КВН».
Выход: {"keep": false, "reason": "студенческое мероприятие без отраслевого содержания"}

Вход: «НПЗ в Нижегородской области модернизировал установку
каталитического крекинга».
Выход: {"keep": true, "reason": "модернизация переработки, профильная новость"}

Вход: «Делегация университета посетила партнёрский вуз в Китае».
Выход: {"keep": false, "reason": "вузовский визит без отраслевой повестки"}

Вход: «Газпром наградил лучших молодых специалистов грамотами».
Выход: {"keep": false, "reason": "корпоративная награда без производственного содержания"}

Вход: «Разработан отечественный буровой раствор для горизонтальных
скважин».
Выход: {"keep": true, "reason": "отраслевая технология для бурения"}

Вход: «В регионе благоустроили парк рядом с нефтеперекачивающей
станцией».
Выход: {"keep": false, "reason": "благоустройство, отраслевого содержания нет"}
""".strip()


def stage(msg: str) -> None:
    print(f"\n=== {msg} ===", flush=True)


def progress_line(prefix: str, i: int, total: int, extra: str = "") -> None:
    total = max(total, 1)
    pct = 100.0 * i / total
    bar_w = 24
    filled = int(bar_w * i / total)
    bar = "#" * filled + "-" * (bar_w - filled)
    line = f"\r{prefix} [{bar}] {i}/{total} ({pct:5.1f}%)"
    if extra:
        line += f"  {extra}"
    sys.stdout.write(line[:118])
    sys.stdout.flush()
    if i >= total:
        sys.stdout.write("\n")
        sys.stdout.flush()


def load_raw(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
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
            if not link or link in seen:
                continue
            seen.add(link)
            title = str(row.get("title") or "").strip()
            text = str(row.get("text") or "").strip()
            if len(text) < 80 and len(title) < 20:
                continue
            if not row.get("article_id"):
                row["article_id"] = article_id_from_link(link)
            rows.append(row)
    return rows


def load_decisions(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            aid = str(row.get("article_id") or "")
            if aid:
                out[aid] = row
    return out


def append_decision(path: Path, row: dict[str, Any], lock: threading.Lock) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def llm_judge(client: LLMClient, row: dict[str, Any]) -> dict[str, Any]:
    title = str(row.get("title") or "")
    text = str(row.get("text") or "")
    link = str(row.get("link") or "")
    aid = str(row.get("article_id") or article_id_from_link(link))
    try:
        named = client.json_call(
            FILTER_PROMPT,
            {
                "title": title[:300],
                "text_preview": text[:900],
                "url": link[:300],
                "org_name": str(row.get("org_name") or "")[:200],
            },
            max_retries=2,
        )
        keep = bool(named.get("keep"))
        reason = str(named.get("reason") or "").strip()
        return {
            "article_id": aid,
            "keep": keep,
            "reason": reason,
            "method": "llm",
            "title": title[:180],
        }
    except Exception as exc:
        # при сбое LLM не выкидываем статью молча — помечаем как keep по ключам
        return {
            "article_id": aid,
            "keep": True,
            "reason": f"llm_error_fallback_keep: {type(exc).__name__}: {exc}",
            "method": "llm_error",
            "title": title[:180],
        }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Фильтр science_org_news: keywords → Lab LLM")
    p.add_argument("--input", type=Path, default=ARTICLES_JSONL)
    p.add_argument("--output", type=Path, default=OUT_JSONL)
    p.add_argument(
        "--apply",
        action="store_true",
        help="Также перезаписать articles.jsonl отфильтрованным корпусом",
    )
    p.add_argument("--resume", action="store_true", help="Продолжить LLM по decisions-файлу")
    p.add_argument("--workers", type=int, default=4, help="Параллельных LLM-запросов")
    p.add_argument(
        "--oilgas-min-hits",
        type=int,
        default=1,
        help="Порог ключей на этапе 2 (как в кластеризации)",
    )
    p.add_argument(
        "--keywords-only",
        action="store_true",
        help="Только этап ключей, без LLM",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Ограничить число статей на LLM (отладка)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input.exists():
        print(f"Нет входного файла: {args.input}", file=sys.stderr)
        return 1

    settings = Settings(API_KEY=API_KEY, BASE_URL=BASE_URL, LLM_MODEL=MODEL_NAME)
    print(
        json.dumps(
            {
                "input": str(args.input),
                "output": str(args.output),
                "apply": bool(args.apply),
                "resume": bool(args.resume),
                "workers": max(1, int(args.workers)),
                "oilgas_min_hits": int(args.oilgas_min_hits),
                "keywords_only": bool(args.keywords_only),
                "llm": {"base_url": BASE_URL, "model": MODEL_NAME, "enabled": True},
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    # --- 1. load ---
    stage("ЭТАП 1/4 · загрузка корпуса")
    raw = load_raw(args.input)
    print(f"загружено уникальных статей: {len(raw)}", flush=True)

    # --- 2. keywords ---
    stage("ЭТАП 2/4 · фильтр по ключевым словам / junk")
    kw_keep: list[dict[str, Any]] = []
    dropped_junk = 0
    dropped_offtopic = 0
    for i, row in enumerate(raw, start=1):
        title = str(row.get("title") or "")
        text = str(row.get("text") or "")
        day = str(row.get("datatime") or "")[:10]
        if is_junk_news(title=title, text=text, date=day):
            dropped_junk += 1
        elif not is_oilgas_relevant(title, text, min_hits=int(args.oilgas_min_hits)):
            dropped_offtopic += 1
        else:
            kw_keep.append(row)
        if i % 200 == 0 or i == len(raw):
            progress_line(
                "keywords",
                i,
                len(raw),
                f"keep={len(kw_keep)} junk={dropped_junk} off={dropped_offtopic}",
            )
    print(
        f"после ключей: keep={len(kw_keep)} · junk={dropped_junk} · offtopic={dropped_offtopic}",
        flush=True,
    )

    final_rows = list(kw_keep)
    llm_stats = {"keep": 0, "drop": 0, "cached": 0, "errors_fallback_keep": 0}

    if not args.keywords_only:
        # --- 3. LLM ---
        stage("ЭТАП 3/4 · Lab LLM keep/drop")
        client = LLMClient(settings)
        if not client.enabled:
            print("LLM не включён — проверьте креды в скрипте", file=sys.stderr)
            return 1
        print(f"model={MODEL_NAME}  base={BASE_URL}  workers={max(1, args.workers)}", flush=True)

        prior = load_decisions(DECISIONS_PATH) if args.resume else {}
        if not args.resume and DECISIONS_PATH.exists():
            DECISIONS_PATH.unlink()
            prior = {}

        todo = list(kw_keep)
        if args.limit > 0:
            todo = todo[: int(args.limit)]

        decisions: dict[str, dict[str, Any]] = dict(prior)
        lock = threading.Lock()
        thread_local = threading.local()

        def client_for_thread() -> LLMClient:
            c = getattr(thread_local, "llm", None)
            if c is None:
                c = LLMClient(settings)
                thread_local.llm = c
            return c

        pending: list[dict[str, Any]] = []
        for row in todo:
            aid = str(row.get("article_id") or article_id_from_link(str(row.get("link") or "")))
            row = dict(row)
            row["article_id"] = aid
            cached = decisions.get(aid)
            if cached and "keep" in cached:
                llm_stats["cached"] += 1
                continue
            pending.append(row)

        print(
            f"к LLM: {len(pending)} · уже в decisions: {llm_stats['cached']} · всего после ключей: {len(todo)}",
            flush=True,
        )

        done_n = 0
        total_n = len(pending)
        t0 = time.time()

        def work(row: dict[str, Any]) -> dict[str, Any]:
            return llm_judge(client_for_thread(), row)

        if total_n == 0:
            progress_line("llm", 0, 1, "нечего слать")
        else:
            with ThreadPoolExecutor(max_workers=max(1, int(args.workers))) as pool:
                futs = {pool.submit(work, row): row for row in pending}
                for fut in as_completed(futs):
                    dec = fut.result()
                    aid = str(dec.get("article_id") or "")
                    decisions[aid] = dec
                    append_decision(DECISIONS_PATH, dec, lock)
                    if dec.get("method") == "llm_error":
                        llm_stats["errors_fallback_keep"] += 1
                        llm_stats["keep"] += 1
                    elif dec.get("keep"):
                        llm_stats["keep"] += 1
                    else:
                        llm_stats["drop"] += 1
                    done_n += 1
                    elapsed = max(time.time() - t0, 1e-6)
                    rate = done_n / elapsed
                    eta = int((total_n - done_n) / rate) if rate > 0 else 0
                    progress_line(
                        "llm",
                        done_n,
                        total_n,
                        f"keep={llm_stats['keep']} drop={llm_stats['drop']} ~{eta}s",
                    )

        # собрать финал: keyword survivors ∩ llm keep
        keep_ids = {
            aid
            for aid, dec in decisions.items()
            if dec.get("keep") is True
        }
        # статьи не из todo (limit) — если limit, оставляем только обработанные keep
        if args.limit > 0:
            final_rows = [
                r
                for r in todo
                if str(r.get("article_id") or "") in keep_ids
            ]
        else:
            final_rows = []
            for row in kw_keep:
                aid = str(row.get("article_id") or article_id_from_link(str(row.get("link") or "")))
                dec = decisions.get(aid)
                if dec is None:
                    # не должно случаться без --limit
                    final_rows.append(row)
                elif dec.get("keep"):
                    final_rows.append(row)
        print(
            f"после LLM: keep={len(final_rows)} · drop={llm_stats['drop']} · "
            f"cached={llm_stats['cached']} · llm_errors_keep={llm_stats['errors_fallback_keep']}",
            flush=True,
        )

    # --- 4. write ---
    stage("ЭТАП 4/4 · запись результата")
    write_jsonl(args.output, final_rows)
    print(f"записано: {args.output} · {len(final_rows)} статей", flush=True)
    if args.apply:
        write_jsonl(ARTICLES_JSONL, final_rows)
        print(f"применено: {ARTICLES_JSONL}", flush=True)

    summary = {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "input": str(args.input),
        "output": str(args.output),
        "apply": bool(args.apply),
        "raw": len(raw),
        "after_keywords": len(kw_keep),
        "dropped_junk": dropped_junk,
        "dropped_offtopic": dropped_offtopic,
        "after_llm": len(final_rows),
        "llm_stats": llm_stats,
        "keywords_only": bool(args.keywords_only),
        "lab": {"base_url": BASE_URL, "model": MODEL_NAME},
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"сводка: {SUMMARY_PATH}", flush=True)
    stage("ГОТОВО")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
