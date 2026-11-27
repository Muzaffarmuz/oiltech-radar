# OilTech Radar

Аналитическая платформа для мониторинга ИТ и автоматизации в нефтегазе. Система собирает отраслевые публикации, обрабатывает их пайплайнами на Python и LLM, кластеризует в темы и показывает динамику, компании и источники в веб-портале.

Отдельные потоки закрывают ИТ и автоматизацию, науку и патенты, инвестиции, регуляторный контур и новости крупных зарубежных компаний. Репозиторий демонстрирует полный цикл: от сбора данных до объяснимого интерфейса для анализа технологических сигналов.

## Стек

- Python 3.11+, FastAPI
- SQLite / JSON-отчёты пайплайнов
- LLM-гейты и кластеризация текстов
- Портал: HTML/JS + Plotly

## Быстрый старт

```powershell
cd oiltech-radar
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# заполните API_KEY (и при необходимости LAB_*) в .env
$env:PYTHONPATH = (Get-Location).Path
python -m portal.app
```

Откройте http://127.0.0.1:8085

Playwright нужен только для сложных сайтов:

```powershell
python -m playwright install chromium
```

## Основные экраны

| Путь | Назначение |
|------|------------|
| `/` | Обзор платформы |
| `/flows/news/digital` | ИТ и автоматизация |
| `/flows/science` | Наука и патенты |
| `/flows/investments` | Инвестиции и стартапы |
| `/flows/policy` | Политика и рынок |
| `/flows/foreign-companies` | Зарубежные компании · ИТ |

## Конфигурация

Секреты хранятся только в `.env` (файл в git не попадает). Шаблон — `.env.example`.

Скрипты `scripts/*_lab.py` читают Lab-креды через `LAB_API_KEY` / `LAB_BASE_URL` или общие `API_KEY` / `BASE_URL`.

## Тесты

```powershell
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = (Get-Location).Path
pytest -q
```

## Замечание по данным

Сырые выгрузки скраперов и промежуточные прогоны в git не включены. Для демонстрации UI в репозитории лежат снимки: `data/portal/portal_data.json` и отчёты потоков в `data/runs/` (наука, политика, инвестиции, зарубежные компании).
