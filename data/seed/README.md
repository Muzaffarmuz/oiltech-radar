# Seed отключён

Демо/выдуманные статьи **не используются**.

Портал питается только из `data/raw/` после scrape реальных сайтов:

```powershell
python -m gartner.pipeline.run --reset --backfill --recluster
```
