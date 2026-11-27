# Чеклист реализации OilTech Radar 3.0

Проверено по плану из созвона / внутренней спецификации.

| # | Требование | Статус | Где |
|---|---|---|---|
| 0 | Отдельная папка продукта | ✅ | `C:\Users\Муз\Desktop\ГАРТНЕР\gartner_3.0` |
| 0 | CIO vs Audit разведены | ✅ | `/` и `/audit` |
| 1.1 | Один venv + `.env.example` без секретов | ✅ | `requirements.txt`, `.env.example` |
| 1.2 | Оркестратор со стадиями и манифестом | ✅ | `gartner/pipeline/run.py`, `data/runs/` |
| 1.3 | SQLite: articles/events/clusters/snapshots | ✅ | `gartner/db.py` |
| 2.1 | 6 источников, уникальные prefix | ✅ | `legacy_scrapers/` + `pipeline/scrape.py` |
| 2.2 | Merge + dedup | ✅ | `pipeline/merge.py` |
| 2.3 | Инкремент scrape days / seen links | ✅ | `SCRAPE_DAYS`, upsert по link |
| 3.1 | LLM extract только новых | ✅ | `articles.processed=0` |
| 3.2 | Midstream | ✅ | `extract.py` META_PROMPT |
| 3.3 | Нормализация компаний | ✅ | `company.py` |
| 3.4 | Не Deep Agent | ✅ | только трендовый портал |
| 4.1 | Один боевой cluster-контур | ✅ | `cluster.py` (без сетки 324) |
| 4.2 | Гибрид ML + LLM имена | ✅ | cluster + enrich |
| 4.3 | Стабильные имена | ✅ | enrich не переименовывает без нужды |
| 4.4 | Поиск юзкейса «бурение» | ✅ | UI search |
| 5 | Сценарии развития | ✅ | `forecast.py` + карточка темы |
| 6.1–6.4 | CIO dashboard | ✅ | `portal/static/` |
| 6.5 | FastAPI backend | ✅ | `portal/app.py` |
| 7 | Кнопка + weekly/daily/manual | ✅ | refresh + update-mode API |
| 8 | Snapshots / diff | ✅ | `snapshot.py` |
| 9 | QA | ✅ | `qa.py` → `data/runs/qa_latest.md` |
| 10 | Fallback без ключа | ✅ | heuristic extract/embed/forecast |
| 11 | Seed DoD smoke | ✅ | `--seed-only` → topics≥1, portal 200 |

## Smoke (факт прогона)

- merge: 18 статей
- extract: 17 событий
- cluster: 2 темы (umap_hdbscan)
- portal: http://127.0.0.1:8080 → 200
- audit: http://127.0.0.1:8080/audit → 200
