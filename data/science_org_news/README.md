# Новости патентообладателей / НИИ (только поток «Наука»)

Сюда пишет `scripts/scrape_science_org_news.py`. Каталог **не** входит в merge ИТ (`data/raw`).

## Запуск

```bash
python scripts/scrape_science_org_news.py
```

Продолжение после обрыва — тот же командой (готовые источники пропускаются).

```bash
python scripts/scrape_science_org_news.py --retry-failed
python scripts/scrape_science_org_news.py --force
python scripts/scrape_science_org_news.py --limit 5
python scripts/scrape_science_org_news.py --rebuild-jsonl
```

По умолчанию: статьи с `datatime >= 2026-01-01`, LLM выключен.

## Файлы

| Путь | Назначение |
|------|------------|
| `progress.json` | Статус по каждому источнику |
| `sources/<id>.json` | Статьи + мета источника |
| `profiles/<id>.json` | Кэш discover (хабы/RSS) |
| `articles.jsonl` | Все статьи одним потоком |
| `manifest.json` | Краткая сводка |

Источник списка URL: `data/exports/org_sites_prompt/org_news_sources.json`.
