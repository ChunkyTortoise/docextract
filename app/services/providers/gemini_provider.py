"""Gemini provider for LLM judge and classification tasks.

Wraps google.genai with a minimal interface that matches the Anthropic
response structure used by LLMJudge — enough for the judge to stay
provider-agnostic.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_JUDGE_MODEL = "gemini-2.5-flash"


class GeminiResponse:
    """Minimal response wrapper that mirrors anthropic.types.Message for judge use."""

    def __init__(self, text: str) -> None:
        self._text = text

    @property
    def content(self) -> list[Any]:
        block = type("TextBlock", (), {"type": "text", "text": self._text})()
        return [block]


class GeminiJudgeClient:
    """Lightweight async client for Gemini text generation (judge/classification only).

    Uses google.genai async interface. Raises on 4xx/5xx so the judge can
    fall back to Claude.
    """

    def __init__(self, api_key: str, model: str = DEFAULT_JUDGE_MODEL) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def generate(self, prompt: str, max_tokens: int = 512) -> GeminiResponse:
        """Generate text from a prompt. Raises on API errors."""
        from google.genai import types as genai_types

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                max_output_tokens=max_tokens,
                temperature=0.0,
            ),
        )
        text = response.text or ""
        return GeminiResponse(text)
