# Legacy data

Папка для данных старого проекта `gartner`.

## Важно

В исходном репозитории **не было** `data/` с CSV (`pt._3.4_*`, `pt._1.2_*`) — они в `.gitignore` и на эту машину не попали.

Поэтому `python -m gartner.pipeline.import_legacy` загружает:

1. Если положите CSV в `data/legacy/import/` — импортирует их как есть.
2. Иначе — `reconstructed_corpus.json`: **12 тем** старого фокуса (двойники, LLM, ML бурения, midstream и т.д.) с событиями март 2025 – февраль 2026.

Ссылки вида `.../legacy/...` — **синтетические**, не живые страницы новостей.

## Как подставить настоящие CSV

Скопируйте в `import/`:

- `pt._1.2_filtr_extract_meta.csv` и/или
- `pt._3.4_best_clusters_*.csv`
- опционально `pt._3.5_cluster_profiles_*.csv`

Затем:

```powershell
python -m gartner.pipeline.import_legacy
```
