"""Unit tests for vision extraction service."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestExtractVision:
    @pytest.mark.asyncio
    async def test_raises_on_non_image_mime(self):
        from app.services.vision_extractor import extract_vision
        with pytest.raises(ValueError, match="image MIME type"):
            await extract_vision(b"pdf data", "application/pdf")

    @pytest.mark.asyncio
    async def test_extracts_text_from_image(self):
        from app.services.vision_extractor import extract_vision

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"_raw_text": "Invoice #123", "_confidence": 0.95}')]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            result = await extract_vision(b"\xff\xd8\xff fake jpeg", "image/jpeg")

        assert result.text == "Invoice #123"
        assert result.metadata["extraction_method"] == "vision"
        assert result.metadata["mime_type"] == "image/jpeg"

    @pytest.mark.asyncio
    async def test_passes_doc_type_hint_in_prompt(self):
        from app.services.vision_extractor import extract_vision

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"_raw_text": "Receipt data"}')]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            await extract_vision(b"fake png", "image/png", doc_type="receipt")

        call_args = mock_client.messages.create.call_args
        messages = call_args.kwargs["messages"]
        text_content = next(
            c["text"] for c in messages[0]["content"] if c["type"] == "text"
        )
        assert "receipt" in text_content.lower()

    @pytest.mark.asyncio
    async def test_falls_back_to_full_response_on_non_json(self):
        from app.services.vision_extractor import extract_vision

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="This is a plain text invoice for $100")]
        mock_response.usage = MagicMock(input_tokens=50, output_tokens=30)

        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            result = await extract_vision(b"fake", "image/png")

        assert "invoice" in result.text.lower()

    @pytest.mark.asyncio
    async def test_returns_page_count_one(self):
        from app.services.vision_extractor import extract_vision

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="{}")]
        mock_response.usage = MagicMock(input_tokens=10, output_tokens=5)

        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            result = await extract_vision(b"fake", "image/webp")

        assert result.page_count == 1

    @pytest.mark.asyncio
    async def test_sends_base64_encoded_image(self):
        import base64
        from app.services.vision_extractor import extract_vision

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="{}")]
        mock_response.usage = MagicMock(input_tokens=10, output_tokens=5)

        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        image_bytes = b"\xff\xd8\xff test image bytes"
        expected_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            await extract_vision(image_bytes, "image/jpeg")

        call_args = mock_client.messages.create.call_args
        messages = call_args.kwargs["messages"]
        image_content = next(c for c in messages[0]["content"] if c["type"] == "image")
        assert image_content["source"]["data"] == expected_b64
        assert image_content["source"]["media_type"] == "image/jpeg"


class TestParseRawText:
    def test_extracts_raw_text_from_json(self):
        from app.services.vision_extractor import _parse_raw_text
        result = _parse_raw_text('{"_raw_text": "Invoice 123", "_confidence": 0.9}')
        assert result == "Invoice 123"

    def test_falls_back_on_plain_text(self):
        from app.services.vision_extractor import _parse_raw_text
        result = _parse_raw_text("plain text response")
        assert result == "plain text response"

    def test_handles_markdown_code_block(self):
        from app.services.vision_extractor import _parse_raw_text
        text = '```json\n{"_raw_text": "extracted text"}\n```'
        result = _parse_raw_text(text)
        assert result == "extracted text"
