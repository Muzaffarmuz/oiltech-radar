"""OpenAI-compatible LLM / embeddings клиент с fallback."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from gartner.config import Settings, get_settings


def extract_json_object(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    if not text:
        raise ValueError("Пустой ответ модели")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def get_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text)
    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                chunks.append(str(text))
    if chunks:
        return "\n".join(chunks).strip()
    # chat.completions fallback shape
    choices = getattr(response, "choices", None)
    if choices:
        message = choices[0].message
        content = getattr(message, "content", "")
        return str(content or "").strip()
    return ""


class LLMClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = None
        if self.settings.llm_enabled:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.settings.api_key, base_url=self.settings.base_url)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def json_call(self, prompt: str, payload: dict[str, Any], max_retries: int = 3) -> dict[str, Any]:
        if not self._client:
            raise RuntimeError("LLM disabled")
        body = json.dumps(payload, ensure_ascii=False)
        last_error: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                try:
                    response = self._client.responses.create(
                        model=self.settings.llm_model,
                        input=[
                            {"role": "system", "content": [{"type": "input_text", "text": prompt}]},
                            {"role": "user", "content": [{"type": "input_text", "text": body}]},
                        ],
                    )
                except Exception:
                    # gpt-6-astra и др. могут не принимать temperature/max_tokens
                    response = self._client.chat.completions.create(
                        model=self.settings.llm_model,
                        messages=[
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": body},
                        ],
                    )
                return extract_json_object(get_response_text(response))
            except Exception as exc:
                last_error = exc
                time.sleep(attempt)
        raise RuntimeError(f"LLM request failed: {last_error}") from last_error

    def embed(self, texts: list[str], batch_size: int = 32, max_retries: int = 5) -> list[list[float]]:
        if not self._client:
            raise RuntimeError("LLM disabled")
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            last_error: Exception | None = None
            for attempt in range(1, max_retries + 1):
                try:
                    response = self._client.embeddings.create(
                        model=self.settings.embedding_model, input=batch
                    )
                    batch_vecs = [item.embedding for item in response.data]
                    vectors.extend(batch_vecs)
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    # при таймауте пробуем батч пополам
                    if attempt == max_retries and len(batch) > 1:
                        mid = len(batch) // 2
                        vectors.extend(self.embed(batch[:mid], batch_size=max(1, mid), max_retries=max_retries))
                        vectors.extend(self.embed(batch[mid:], batch_size=max(1, len(batch) - mid), max_retries=max_retries))
                        last_error = None
                        break
                    time.sleep(min(20, attempt * 2))
            if last_error is not None:
                raise RuntimeError(f"Embedding failed at offset {start}: {last_error}") from last_error
            time.sleep(0.15)
        return vectors
