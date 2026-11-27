"""Запуск legacy-парсеров с уникальными out-prefix и устойчивость к сбоям."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from gartner.config import LEGACY_SCRAPERS, RAW_DIR, Settings, ensure_dirs, get_settings

# Уникальные префиксы — чтобы neftegaz science/analisis не затирали друг друга
SOURCES: list[dict[str, Any]] = [
    {
        "id": "neftegaz_science",
        "script": "neftegaz_science_scrape.py",
        "out_prefix": "neftegaz_science",
        "extra": [],
    },
    {
        "id": "neftegaz_analisis",
        "script": "neftegaz_science_analisis.py",
        "out_prefix": "neftegaz_analisis",
        "extra": [],
    },
    {
        "id": "sectormedia",
        "script": "sectormedia_neft_gaz_scrape.py",
        "out_prefix": "sectormedia_neft_gaz",
        "extra": [],
    },
    {
        "id": "nprom_trends",
        "script": "nprom_trends_scrape.py",
        "out_prefix": "nprom_trends",
        "extra": [],
    },
    {
        "id": "nprom_market",
        "script": "nprom_market_scrape.py",
        "out_prefix": "nprom_market",
        "extra": [],
    },
    {
        "id": "nprom_digital",
        "script": "nprom_czifrovye_resheniya_scrape.py",
        "out_prefix": "nprom_czifrovye_resheniya",
        "extra": [],
    },
]


@dataclass
class ScrapeResult:
    source_id: str
    ok: bool
    path: str | None = None
    error: str | None = None
    count: int = 0


@dataclass
class ScrapeReport:
    results: list[ScrapeResult] = field(default_factory=list)

    @property
    def ok_sources(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def failed(self) -> list[ScrapeResult]:
        return [r for r in self.results if not r.ok]


def _months_from_days(days: int) -> int:
    return max(1, (days + 29) // 30)


def run_scrapers(
    *,
    settings: Settings | None = None,
    backfill: bool = False,
    python_exe: str | None = None,
) -> ScrapeReport:
    """Запускает все парсеры. Один упавший источник не валит весь пайплайн."""
    settings = settings or get_settings()
    ensure_dirs()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    months = settings.backfill_months if backfill else _months_from_days(settings.scrape_days)
    py = python_exe or sys.executable
    report = ScrapeReport()

    for src in SOURCES:
        script = LEGACY_SCRAPERS / src["script"]
        out_prefix = RAW_DIR / src["out_prefix"]
        cmd = [
            py,
            str(script),
            "--months",
            str(months),
            "--out-prefix",
            str(out_prefix),
            "--quiet",
        ]
        # TLS fallback для сайтов, где часто ломается корпоративный proxy/антивирус
        if "neftegaz" in src["id"] or "sectormedia" in src["id"]:
            cmd.append("--no-tls-verify")
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1200,
                check=False,
            )
            json_path = Path(f"{out_prefix}.json")
            csv_path = Path(f"{out_prefix}.csv")
            path = json_path if json_path.exists() else (csv_path if csv_path.exists() else None)
            if completed.returncode != 0 or path is None:
                err = (completed.stderr or completed.stdout or "unknown error")[:500]
                report.results.append(
                    ScrapeResult(source_id=src["id"], ok=False, error=err, path=str(path) if path else None)
                )
                continue
            count = _count_file(path)
            report.results.append(ScrapeResult(source_id=src["id"], ok=True, path=str(path), count=count))
        except Exception as exc:  # noqa: BLE001
            report.results.append(ScrapeResult(source_id=src["id"], ok=False, error=str(exc)))

    # Пользовательские источники (схема A)
    try:
        from gartner.custom_sources.service import scrape_all_custom_sources

        custom = scrape_all_custom_sources()
        for item in custom.get("results") or []:
            report.results.append(
                ScrapeResult(
                    source_id=str(item.get("source_id") or "custom"),
                    ok=bool(item.get("ok")),
                    path=item.get("path"),
                    error=item.get("error"),
                    count=int(item.get("count") or 0),
                )
            )
    except Exception as exc:  # noqa: BLE001
        report.results.append(ScrapeResult(source_id="custom_sources", ok=False, error=str(exc)))

    # манифест прогона
    manifest = {
        "date": date.today().isoformat(),
        "months": months,
        "backfill": backfill,
        "results": [r.__dict__ for r in report.results],
    }
    (RAW_DIR / "last_scrape_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def _count_file(path: Path) -> int:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict) and isinstance(data.get("signals"), list):
            return len(data["signals"])
        return 0
    # csv
    try:
        import pandas as pd

        return len(pd.read_csv(path, encoding="utf-8-sig"))
    except Exception:
        return 0
