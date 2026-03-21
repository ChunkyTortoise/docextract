"""Tests for Claude extractor service."""
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import json

import pytest
import anthropic

from app.services.claude_extractor import (
    ExtractionResult,
    apply_corrections,
    extract,
    _parse_json_response,
)


def _make_text_block(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _make_tool_use_block(name: str, input_data: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = input_data
    return block


def _make_response(content_blocks: list) -> MagicMock:
    response = MagicMock()
    response.content = content_blocks
    return response


class TestExtractPass1:
    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_successful_extraction(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client

        extracted_json = {
            "invoice_number": "INV-001",
            "total_amount": 500.0,
            "_confidence": 0.95,
        }
        client.messages.create = AsyncMock(return_value=_make_response(
            [_make_text_block(json.dumps(extracted_json))]
        ))

        result = await extract("Invoice #INV-001\nTotal: $500", "invoice")

        assert isinstance(result, ExtractionResult)
        assert result.data["invoice_number"] == "INV-001"
        assert result.confidence == 0.95
        assert not result.corrections_applied
        assert "_confidence" not in result.data

    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_uses_content_0_text(self, mock_cls):
        """Verify response.content[0].text is used (not response.content.text)."""
        client = MagicMock()
        mock_cls.return_value = client

        text_block = _make_text_block(json.dumps({"_confidence": 0.9}))
        # Use a MagicMock for content so .text raises AttributeError
        response = MagicMock()
        response.content = MagicMock()
        response.content.__getitem__ = MagicMock(return_value=text_block)
        # Make response.content.text raise AttributeError
        type(response.content).text = PropertyMock(side_effect=AttributeError("use content[0].text"))
        client.messages.create = AsyncMock(return_value=response)

        result = await extract("test", "invoice")
        assert result.confidence == 0.9

    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_default_confidence_when_missing(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        client.messages.create = AsyncMock(return_value=_make_response(
            [_make_text_block(json.dumps({"invoice_number": "X"}))]
        ))

        result = await extract("test", "invoice")
        assert result.confidence == 0.5


class TestExtractPass2Corrections:
    @patch("app.services.claude_extractor.settings")
    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_corrections_applied_on_low_confidence(self, mock_cls, mock_settings):
        mock_settings.anthropic_api_key = "test-key"
        mock_settings.extraction_confidence_threshold = 0.8
        mock_settings.confidence_thresholds = {}
        mock_settings.active_learning_enabled = False

        client = MagicMock()
        mock_cls.return_value = client

        # Pass 1: low confidence extraction
        pass1_data = {"invoice_number": "INV-001", "_confidence": 0.6}
        pass1_response = _make_response([_make_text_block(json.dumps(pass1_data))])

        # Pass 2: correction via tool_use
        correction_block = _make_tool_use_block(
            "apply_corrections",
            {"corrections": {"invoice_number": "INV-001-A"}, "reasoning": "Fixed typo"},
        )
        pass2_response = _make_response([correction_block])

        client.messages.create = AsyncMock(side_effect=[pass1_response, pass2_response])

        result = await extract("test doc", "invoice")
        assert result.corrections_applied is True
        assert result.data["invoice_number"] == "INV-001-A"

    @patch("app.services.claude_extractor.settings")
    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_no_corrections_when_high_confidence(self, mock_cls, mock_settings):
        mock_settings.anthropic_api_key = "test-key"
        mock_settings.extraction_confidence_threshold = 0.8
        mock_settings.confidence_thresholds = {}
        mock_settings.active_learning_enabled = False

        client = MagicMock()
        mock_cls.return_value = client

        pass1_data = {"invoice_number": "INV-001", "_confidence": 0.95}
        client.messages.create = AsyncMock(return_value=_make_response(
            [_make_text_block(json.dumps(pass1_data))]
        ))

        result = await extract("test doc", "invoice")
        assert result.corrections_applied is False
        # Only one API call (no correction pass)
        assert client.messages.create.call_count == 1


class TestApplyCorrections:
    def test_merge_corrections(self):
        original = {"a": 1, "b": 2, "c": 3}
        corrections = {"b": 20, "d": 4}
        result = apply_corrections(original, corrections)
        assert result == {"a": 1, "b": 20, "c": 3, "d": 4}

    def test_empty_corrections(self):
        original = {"a": 1}
        result = apply_corrections(original, {})
        assert result == {"a": 1}

    def test_does_not_mutate_original(self):
        original = {"a": 1}
        apply_corrections(original, {"a": 2})
        assert original == {"a": 1}


class TestParseJsonResponse:
    def test_direct_json(self):
        result = _parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_in_code_block(self):
        text = 'Some text\n```json\n{"key": "value"}\n```\nMore text'
        result = _parse_json_response(text)
        assert result == {"key": "value"}

    def test_json_in_generic_code_block(self):
        text = 'Text\n```\n{"key": "value"}\n```'
        result = _parse_json_response(text)
        assert result == {"key": "value"}

    def test_embedded_json_object(self):
        text = 'Here is the result: {"key": "value"} end.'
        result = _parse_json_response(text)
        assert result == {"key": "value"}

    def test_unparseable_returns_empty(self):
        result = _parse_json_response("no json here at all")
        assert result == {}


class TestExtractionResultSchemaValid:
    """Tests for schema_valid field on ExtractionResult."""

    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_schema_valid_field_exists(self, mock_anthropic_cls):
        """ExtractionResult should have schema_valid field."""
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"invoice_number": "INV-001", "_confidence": 0.9}')]
        client.messages.create = AsyncMock(return_value=mock_response)

        result = await extract("Invoice text", "invoice")
        assert hasattr(result, "schema_valid")

    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_schema_valid_true_for_valid_extraction(self, mock_anthropic_cls):
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"invoice_number": "INV-001", "_confidence": 0.9, "total_amount": 100.0}')]
        client.messages.create = AsyncMock(return_value=mock_response)

        result = await extract("Invoice text", "invoice")
        assert result.schema_valid is True

    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_validation_errors_field_exists(self, mock_anthropic_cls):
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"_confidence": 0.9}')]
        client.messages.create = AsyncMock(return_value=mock_response)

        result = await extract("text", "invoice")
        assert hasattr(result, "validation_errors")
        assert isinstance(result.validation_errors, list)

    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_extract_with_db_none(self, mock_anthropic_cls):
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"_confidence": 0.9}')]
        client.messages.create = AsyncMock(return_value=mock_response)

        result = await extract("text", "invoice", db=None)
        assert isinstance(result, ExtractionResult)

    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_extract_records_trace_in_memory(self, mock_anthropic_cls):
        from app.services.llm_tracer import get_in_memory_traces, clear_in_memory_traces
        clear_in_memory_traces()
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"_confidence": 0.9}')]
        client.messages.create = AsyncMock(return_value=mock_response)

        await extract("text", "invoice", db=None)
        traces = get_in_memory_traces()
        assert any(t["operation"] == "extract" for t in traces)
        clear_in_memory_traces()


class TestExtractErrorHandling:
    @patch("app.services.claude_extractor.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_rate_limit_retries_with_backoff(self, mock_cls, mock_sleep):
        """Rate limit retry uses exponential backoff (60s, 120s)."""
        client = MagicMock()
        mock_cls.return_value = client

        rate_limit_error = anthropic.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        success_response = _make_response(
            [_make_text_block(json.dumps({"_confidence": 0.9}))]
        )
        client.messages.create = AsyncMock(side_effect=[rate_limit_error, success_response])

        result = await extract("test", "invoice")
        assert result.confidence == 0.9
        mock_sleep.assert_called_once_with(60)

    @patch("app.services.claude_extractor.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_rate_limit_second_retry_doubles_wait(self, mock_cls, mock_sleep):
        """Second retry waits 120s (exponential backoff)."""
        client = MagicMock()
        mock_cls.return_value = client

        rate_limit_error = anthropic.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        success_response = _make_response(
            [_make_text_block(json.dumps({"_confidence": 0.85}))]
        )
        client.messages.create = AsyncMock(
            side_effect=[rate_limit_error, rate_limit_error, success_response]
        )

        result = await extract("test", "invoice")
        assert result.confidence == 0.85
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(60)
        mock_sleep.assert_any_call(120)

    @patch("app.services.claude_extractor.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_rate_limit_raises_after_3_failures(self, mock_cls, mock_sleep):
        """Raises RateLimitError after 3 consecutive failures (no infinite recursion)."""
        client = MagicMock()
        mock_cls.return_value = client

        rate_limit_error = anthropic.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        client.messages.create = AsyncMock(side_effect=rate_limit_error)

        with pytest.raises(anthropic.RateLimitError):
            await extract("test", "invoice")

        # Should have attempted 3 times, slept twice (after attempt 0 and 1)
        assert client.messages.create.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_4xx_error_re_raises(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client

        error = anthropic.BadRequestError(
            message="bad request",
            response=MagicMock(status_code=400, headers={}),
            body=None,
        )
        client.messages.create = AsyncMock(side_effect=error)

        with pytest.raises(anthropic.BadRequestError):
            await extract("test", "invoice")
