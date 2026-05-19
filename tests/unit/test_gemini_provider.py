"""Tests for GeminiJudgeClient and GeminiResponse — no real API calls."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.providers.gemini_provider import (
    DEFAULT_JUDGE_MODEL,
    GeminiJudgeClient,
    GeminiResponse,
)


class TestGeminiResponse:
    def test_content_returns_single_text_block(self):
        resp = GeminiResponse("hello")
        assert len(resp.content) == 1
        block = resp.content[0]
        assert block.type == "text"
        assert block.text == "hello"

    def test_content_empty_string(self):
        resp = GeminiResponse("")
        assert resp.content[0].text == ""

    def test_content_returns_new_block_each_call(self):
        resp = GeminiResponse("x")
        assert resp.content is not resp.content  # each access builds a new list


class TestGeminiJudgeClientInit:
    def test_default_model_constant(self):
        assert DEFAULT_JUDGE_MODEL == "gemini-2.5-flash"

    def test_init_creates_genai_client_with_api_key(self):
        fake_genai = MagicMock()
        fake_google = MagicMock()
        fake_google.genai = fake_genai

        with patch.dict("sys.modules", {"google": fake_google, "google.genai": fake_genai}):
            client = GeminiJudgeClient(api_key="my-api-key")

        fake_genai.Client.assert_called_once_with(api_key="my-api-key")
        assert client._model == DEFAULT_JUDGE_MODEL

    def test_init_uses_provided_model(self):
        fake_genai = MagicMock()
        fake_google = MagicMock()
        fake_google.genai = fake_genai

        with patch.dict("sys.modules", {"google": fake_google, "google.genai": fake_genai}):
            client = GeminiJudgeClient(api_key="key", model="gemini-1.5-pro")

        assert client._model == "gemini-1.5-pro"


class TestGeminiJudgeClientGenerate:
    @pytest.mark.asyncio
    async def test_generate_returns_gemini_response(self):
        mock_api_response = MagicMock()
        mock_api_response.text = "judge verdict here"

        client = _build_client_with_mock_response(mock_api_response)
        result = await client.generate("is this a valid invoice?")

        assert isinstance(result, GeminiResponse)
        assert result.content[0].text == "judge verdict here"

    @pytest.mark.asyncio
    async def test_generate_passes_max_tokens(self):
        mock_api_response = MagicMock()
        mock_api_response.text = "ok"

        client = _build_client_with_mock_response(mock_api_response)
        await client.generate("prompt", max_tokens=256)

        call_kwargs = client._client.aio.models.generate_content.call_args.kwargs
        config = call_kwargs["config"]
        assert config.max_output_tokens == 256

    @pytest.mark.asyncio
    async def test_generate_passes_prompt_as_contents(self):
        mock_api_response = MagicMock()
        mock_api_response.text = "result"

        client = _build_client_with_mock_response(mock_api_response)
        await client.generate("my prompt")

        call_kwargs = client._client.aio.models.generate_content.call_args.kwargs
        assert call_kwargs["contents"] == "my prompt"

    @pytest.mark.asyncio
    async def test_generate_passes_model(self):
        mock_api_response = MagicMock()
        mock_api_response.text = "ok"

        client = _build_client_with_mock_response(mock_api_response, model="gemini-1.5-pro")
        await client.generate("prompt")

        call_kwargs = client._client.aio.models.generate_content.call_args.kwargs
        assert call_kwargs["model"] == "gemini-1.5-pro"

    @pytest.mark.asyncio
    async def test_generate_handles_none_response_text(self):
        mock_api_response = MagicMock()
        mock_api_response.text = None

        client = _build_client_with_mock_response(mock_api_response)
        result = await client.generate("prompt")

        assert result.content[0].text == ""

    @pytest.mark.asyncio
    async def test_generate_propagates_api_errors(self):
        client = GeminiJudgeClient.__new__(GeminiJudgeClient)
        client._model = DEFAULT_JUDGE_MODEL
        client._client = MagicMock()
        client._client.aio.models.generate_content = AsyncMock(
            side_effect=RuntimeError("API 503")
        )

        with pytest.raises(RuntimeError, match="API 503"):
            await client.generate("prompt")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_client_with_mock_response(
    mock_api_response: MagicMock, model: str = DEFAULT_JUDGE_MODEL
) -> GeminiJudgeClient:
    client = GeminiJudgeClient.__new__(GeminiJudgeClient)
    client._model = model
    client._client = MagicMock()
    client._client.aio.models.generate_content = AsyncMock(return_value=mock_api_response)
    return client


