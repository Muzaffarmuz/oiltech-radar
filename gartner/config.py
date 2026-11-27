"""Конфигурация OilTech Radar 3.0."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
MANUAL_SOURCES_DIR = DATA_DIR / "manual_sources"
CACHE_DIR = DATA_DIR / "cache"
RUNS_DIR = DATA_DIR / "runs"
PORTAL_DIR = DATA_DIR / "portal"
SEED_DIR = DATA_DIR / "seed"
FLOW_TAGS_DIR = RUNS_DIR / "flow_tags"
DB_PATH = DATA_DIR / "radar.db"
LEGACY_SCRAPERS = ROOT / "legacy_scrapers"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: str = Field(default="", alias="API_KEY")
    base_url: str = Field(default="https://api.proxyapi.ru/openai/v1", alias="BASE_URL")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    embedding_model: str = Field(default="text-embedding-3-large", alias="EMBEDDING_MODEL")

    update_mode: Literal["weekly", "daily", "manual"] = Field(default="weekly", alias="UPDATE_MODE")
    update_cron: str = Field(default="0 9 * * 1", alias="UPDATE_CRON")
    scheduler_run_on_start: int = Field(default=0, alias="SCHEDULER_RUN_ON_START")

    scrape_days: int = Field(default=7, alias="SCRAPE_DAYS")
    backfill_months: int = Field(default=12, alias="BACKFILL_MONTHS")

    cluster_view: str = Field(default="topic_plus_summary", alias="CLUSTER_VIEW")
    assign_similarity_threshold: float = Field(default=0.72, alias="ASSIGN_SIMILARITY_THRESHOLD")
    umap_n_neighbors: int = Field(default=10, alias="UMAP_N_NEIGHBORS")
    umap_min_dist: float = Field(default=0.0, alias="UMAP_MIN_DIST")
    umap_n_components: int = Field(default=10, alias="UMAP_N_COMPONENTS")
    hdbscan_min_cluster_size: int = Field(default=8, alias="HDBSCAN_MIN_CLUSTER_SIZE")
    hdbscan_min_samples: int = Field(default=2, alias="HDBSCAN_MIN_SAMPLES")

    # подкластеры (логика pt.3.7, пороги адаптированы под меньший корпус)
    subcluster_min_parent_size: int = Field(default=12, alias="SUBCLUSTER_MIN_PARENT_SIZE")
    subcluster_min_size: int = Field(default=4, alias="SUBCLUSTER_MIN_SIZE")
    subcluster_min_entropy: float = Field(default=1.0, alias="SUBCLUSTER_MIN_ENTROPY")

    host: str = Field(default="127.0.0.1", alias="HOST")
    port: int = Field(default=8080, alias="PORT")
    force_heuristic: int = Field(default=0, alias="FORCE_HEURISTIC")
    # На графике науки показываем патенты только за последние N месяцев от max(publication_date)
    patent_chart_months: int = Field(default=6, alias="PATENT_CHART_MONTHS")

    # Firecrawl — запасной загрузчик для custom sources (пусто = выключен)
    firecrawl_api_url: str = Field(default="", alias="FIRECRAWL_API_URL")
    firecrawl_api_key: str = Field(default="", alias="FIRECRAWL_API_KEY")
    firecrawl_timeout_ms: int = Field(default=45000, alias="FIRECRAWL_TIMEOUT_MS")
    firecrawl_max_pages: int = Field(default=40, alias="FIRECRAWL_MAX_PAGES")

    @property
    def llm_enabled(self) -> bool:
        if self.force_heuristic:
            return False
        key = (self.api_key or "").strip()
        if not key:
            return False
        if key.lower().startswith(("your-", "example", "test-", "replace-", "changeme", "<")):
            return False
        return True


@lru_cache
def get_settings() -> Settings:
    return Settings()


def ensure_dirs() -> None:
    for path in (DATA_DIR, RAW_DIR, MANUAL_SOURCES_DIR, CACHE_DIR, RUNS_DIR, FLOW_TAGS_DIR, PORTAL_DIR, SEED_DIR):
        path.mkdir(parents=True, exist_ok=True)
