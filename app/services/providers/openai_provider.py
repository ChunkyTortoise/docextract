"""OpenAI provider for LLM judge and classification tasks (eval-time only).

Wraps the OpenAI async client with a minimal interface matching the Anthropic
response structure used by LLMJudge — enough for the judge to stay
provider-agnostic. Not wired into hot-path extraction unless explicitly enabled.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_JUDGE_MODEL = "gpt-4o-mini"


class OpenAIResponse:
    """Minimal response wrapper that mirrors anthropic.types.Message for judge use."""

    def __init__(self, text: str) -> None:
        self._text = text

    @property
    def content(self) -> list[Any]:
        block = type("TextBlock", (), {"type": "text", "text": self._text})()
        return [block]


class OpenAIJudgeClient:
    """Lightweight async client for OpenAI chat completions (judge/classification only).

    Uses the OpenAI async interface. Raises on 4xx/5xx so callers can fall back.
    """

    def __init__(self, api_key: str, model: str = DEFAULT_JUDGE_MODEL) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def generate(self, prompt: str, max_tokens: int = 512) -> OpenAIResponse:
        """Generate text from a prompt. Raises on API errors."""
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content or ""
        return OpenAIResponse(text)
