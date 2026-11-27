"""Схема и валидация правил извлечения (конфиг, не произвольный код)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator


class PaginationRules(BaseModel):
    """Стратегии листания ленты. Пока реализуем next_link и page_query; остальные — задел."""

    strategy: str = "none"  # none | next_link | page_query | offset | load_more
    next_selector: str | None = None
    page_param: str | None = None  # ?page=2 / ?PAGEN_1=2
    page_start: int = 1
    page_step: int = 1
    offset_param: str | None = None  # ?offset=20
    offset_step: int = 20
    load_more_selector: str | None = None  # кнопка «ещё» (нужен JS — задел)
    max_pages: int = Field(default=5, ge=1, le=30)

    @field_validator("strategy")
    @classmethod
    def _known_strategy(cls, value: str) -> str:
        allowed = {"none", "next_link", "page_query", "offset", "load_more"}
        text = (value or "none").strip().lower() or "none"
        if text not in allowed:
            return "none"
        return text


class ListRules(BaseModel):
    article_link_selector: str = Field(min_length=1)
    link_attr: str = "href"
    pagination: PaginationRules = Field(default_factory=PaginationRules)


class ArticleRules(BaseModel):
    title_selector: str = Field(min_length=1)
    date_selector: str | None = None
    date_attr: str | None = None
    text_selector: str = Field(min_length=1)
    remove_selectors: list[str] = Field(default_factory=lambda: ["script", "style", "noscript"])


class ScrapeRules(BaseModel):
    """Правила схемы A для одного источника."""

    list_url: str
    list: ListRules
    article: ArticleRules
    source_name: str = Field(min_length=1)
    version: int = 1
    theme: str | None = None  # oilgas | mixed | other
    feeds: list[str] = Field(default_factory=list)
    protection: str | None = None  # none | js_cookie | tls_odd | unknown

    @field_validator("list_url")
    @classmethod
    def _http_list_url(cls, value: str) -> str:
        return normalize_start_url(value)

    @model_validator(mode="after")
    def _source_nonempty(self) -> "ScrapeRules":
        if not self.source_name.strip():
            raise ValueError("source_name пустой")
        return self


def normalize_start_url(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        raise ValueError("URL пустой")
    lowered = text.lower()
    if lowered.startswith(("file:", "javascript:", "data:", "about:")):
        raise ValueError("URL должен быть http(s)")
    if not text.startswith(("http://", "https://")):
        text = "https://" + text
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL должен быть http(s)")
    if not parsed.netloc:
        raise ValueError("В URL нет домена")
    host = parsed.hostname or ""
    if host in {"localhost", "127.0.0.1", "0.0.0.0"} or host.endswith(".local"):
        raise ValueError("Локальные URL не поддерживаются")
    return text


def domain_from_url(url: str) -> str:
    host = urlparse(normalize_start_url(url)).hostname or ""
    return host.lower().removeprefix("www.")


def validate_rules_dict(data: dict[str, Any]) -> ScrapeRules:
    return ScrapeRules.model_validate(data)


def rules_to_dict(rules: ScrapeRules) -> dict[str, Any]:
    return rules.model_dump()
