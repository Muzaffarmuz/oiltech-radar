"""Тесты точечных LLM-гейтов без сети."""

from __future__ import annotations

from gartner.custom_sources.article_extract import is_generic_title
from gartner.custom_sources.llm_gates import (
    LlmBudget,
    classify_kind_llm,
    is_ambiguous_kind,
    judge_article_keep,
    polish_title_llm,
    refine_theme_once,
)


class ScriptedLLM:
    enabled = True

    def __init__(self, answers: list[dict]) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def json_call(self, prompt: str, payload: dict, max_retries: int = 3) -> dict:
        self.prompts.append(prompt)
        if not self.answers:
            raise AssertionError("unexpected extra LLM call")
        return self.answers.pop(0)


def test_query_id_is_not_ambiguous() -> None:
    url = "https://www.novatek.ru/ru/press/releases/index.php?id_4=7882"
    assert not is_ambiguous_kind(url, heuristic="hub", articleish_n=8)
    assert not is_ambiguous_kind(url, heuristic="article", articleish_n=1)


def test_ambiguous_listing_without_id() -> None:
    assert is_ambiguous_kind("https://x.ru/press/releases/index.php", heuristic="article", articleish_n=6)


def test_index_without_id_is_ambiguous_article() -> None:
    assert is_ambiguous_kind("https://x.ru/press/index.php", heuristic="article", articleish_n=0)


def test_clear_article_skips_kind_llm() -> None:
    llm = ScriptedLLM([{"kind": "hub"}])
    budget = LlmBudget()
    kind = classify_kind_llm(
        llm,
        url="https://x.ru/news/one-story",
        html="<html><h1>Релиз</h1><p>Текст</p></html>",
        heuristic="article",
        articleish_n=1,
        budget=budget,
    )
    assert kind is None
    assert budget.used["kind"] == 0
    assert llm.answers  # не вызывали


def test_kind_llm_on_ambiguous() -> None:
    llm = ScriptedLLM([{"kind": "hub", "reason": "лента"}])
    budget = LlmBudget()
    kind = classify_kind_llm(
        llm,
        url="https://x.ru/press/releases/index.php",
        html="<html><h1>Новости</h1><a href='/press/1'>1</a><a href='/press/2'>2</a></html>",
        heuristic="article",
        articleish_n=6,
        budget=budget,
    )
    assert kind == "hub"
    assert budget.used["kind"] == 1


def test_keep_drops_privacy() -> None:
    llm = ScriptedLLM([{"keep": False, "reason": "политика ПДн"}])
    budget = LlmBudget()
    keep = judge_article_keep(
        llm,
        url="https://kingpetro.ru/privacy",
        title="Политика обработки персональных данных",
        text="Настоящая политика определяет порядок обработки персональных данных пользователей сайта.",
        budget=budget,
    )
    assert keep is False
    assert budget.used["drop"] == 1


def test_title_llm_only_when_chrome() -> None:
    assert is_generic_title("Новости | Компания")
    llm = ScriptedLLM([{"title": "НОВАТЭК запустил станцию мониторинга парниковых газов"}])
    budget = LlmBudget()
    title = polish_title_llm(
        llm,
        title="Новости | Компания",
        text="НОВАТЭК запустил самую северную станцию мониторинга парниковых газов.",
        url="https://novatek.ru/press/1",
        budget=budget,
    )
    assert "НОВАТЭК" in (title or "")
    skipped = polish_title_llm(
        llm,
        title="НОВАТЭК запустил станцию мониторинга парниковых газов в Арктике",
        text="Подробности проекта.",
        url="https://novatek.ru/press/1",
        budget=budget,
    )
    assert skipped is None


def test_theme_once_per_budget() -> None:
    llm = ScriptedLLM(
        [
            {"theme": "oilgas", "accepted": True, "reason": "оператор"},
            {"theme": "other", "accepted": False, "reason": "не должен вызваться"},
        ]
    )
    budget = LlmBudget()
    first = refine_theme_once(
        llm,
        domain="example.ru",
        url="https://example.ru/",
        html="<html>офис консалтинг</html>",
        keyword_theme={"theme": "other", "hits": 0, "accepted": False},
        budget=budget,
    )
    second = refine_theme_once(
        llm,
        domain="example.ru",
        url="https://example.ru/",
        html="<html>офис консалтинг</html>",
        keyword_theme={"theme": "other", "hits": 0, "accepted": False},
        budget=budget,
    )
    assert first["theme"] == "oilgas"
    assert second["theme"] == "other"
    assert budget.used["theme"] == 1
    assert len(llm.answers) == 1
