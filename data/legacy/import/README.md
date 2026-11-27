# Как подставить настоящие CSV старого gartner

Скопируйте файлы в эту папку, затем:

```powershell
cd C:\Users\Муз\Desktop\ГАРТНЕР\gartner_3.0
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe -m gartner.pipeline.import_legacy
```

Ожидаемые имена:

- `pt._1.2_filtr_extract_meta.csv`
- `pt._3.4_best_clusters_topic_plus_summary.csv` (или другой view)
- `pt._3.5_cluster_profiles_*.csv` (опционально)
