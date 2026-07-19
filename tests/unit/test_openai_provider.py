"""Tests for OpenAIJudgeClient and OpenAIResponse — no real API calls."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.providers.openai_provider import (
    DEFAULT_JUDGE_MODEL,
    OpenAIJudgeClient,
    OpenAIResponse,
)


class TestOpenAIResponse:
    def test_content_returns_single_text_block(self):
        resp = OpenAIResponse("hello")
        assert len(resp.content) == 1
        block = resp.content[0]
        assert block.type == "text"
        assert block.text == "hello"

    def test_content_empty_string(self):
        resp = OpenAIResponse("")
        assert resp.content[0].text == ""

    def test_content_returns_new_block_each_call(self):
        resp = OpenAIResponse("x")
        assert resp.content is not resp.content


class TestOpenAIJudgeClientInit:
    def test_default_model_constant(self):
        assert DEFAULT_JUDGE_MODEL == "gpt-4o-mini"

    def test_init_creates_openai_client_with_api_key(self):
        fake_openai_mod = MagicMock()
        fake_client_cls = MagicMock()
        fake_openai_mod.AsyncOpenAI = fake_client_cls

        with patch.dict("sys.modules", {"openai": fake_openai_mod}):
            client = OpenAIJudgeClient(api_key="my-api-key")

        fake_client_cls.assert_called_once_with(api_key="my-api-key")
        assert client._model == DEFAULT_JUDGE_MODEL

    def test_init_uses_provided_model(self):
        fake_openai_mod = MagicMock()
        fake_openai_mod.AsyncOpenAI = MagicMock()

        with patch.dict("sys.modules", {"openai": fake_openai_mod}):
            client = OpenAIJudgeClient(api_key="key", model="gpt-4o")

        assert client._model == "gpt-4o"


class TestOpenAIJudgeClientGenerate:
    @pytest.mark.asyncio
    async def test_generate_returns_openai_response(self):
        mock_message = MagicMock()
        mock_message.content = '{"verdict": "pass"}'
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        client = _build_client_with_mock_response(mock_response)
        result = await client.generate("is this a valid invoice?")

        assert isinstance(result, OpenAIResponse)
        assert result.content[0].text == '{"verdict": "pass"}'

    @pytest.mark.asyncio
    async def test_generate_passes_max_tokens_and_json_mode(self):
        mock_message = MagicMock()
        mock_message.content = "{}"
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        client = _build_client_with_mock_response(mock_response)
        await client.generate("prompt", max_tokens=256)

        call_kwargs = client._client.chat.completions.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == 256
        assert call_kwargs["temperature"] == 0.0
        assert call_kwargs["response_format"] == {"type": "json_object"}
        assert call_kwargs["messages"] == [{"role": "user", "content": "prompt"}]

    @pytest.mark.asyncio
    async def test_generate_passes_model(self):
        mock_message = MagicMock()
        mock_message.content = "ok"
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        client = _build_client_with_mock_response(mock_response, model="gpt-4o")
        await client.generate("prompt")

        call_kwargs = client._client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_generate_handles_none_response_content(self):
        mock_message = MagicMock()
        mock_message.content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        client = _build_client_with_mock_response(mock_response)
        result = await client.generate("prompt")

        assert result.content[0].text == ""

    @pytest.mark.asyncio
    async def test_generate_propagates_api_errors(self):
        client = OpenAIJudgeClient.__new__(OpenAIJudgeClient)
        client._model = DEFAULT_JUDGE_MODEL
        client._client = MagicMock()
        client._client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("API 503")
        )

        with pytest.raises(RuntimeError, match="API 503"):
            await client.generate("prompt")


def _build_client_with_mock_response(
    mock_api_response: MagicMock, model: str = DEFAULT_JUDGE_MODEL
) -> OpenAIJudgeClient:
    client = OpenAIJudgeClient.__new__(OpenAIJudgeClient)
    client._model = model
    client._client = MagicMock()
    client._client.chat.completions.create = AsyncMock(return_value=mock_api_response)
    return client
