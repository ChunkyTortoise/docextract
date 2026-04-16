"""Tests for classifier service."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.classifier import CLASSIFY_TOOL, DOCUMENT_TYPES, ClassificationResult, classify


def _make_mock_response(doc_type: str, confidence: float, reasoning: str) -> MagicMock:
    """Build a mock Anthropic API response."""
    content_block = MagicMock()
    content_block.text = json.dumps({
        "document_type": doc_type,
        "confidence": confidence,
        "reasoning": reasoning,
    })
    response = MagicMock()
    response.content = [content_block]
    return response


class TestClassifySuccess:
    @patch("app.services.classifier.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_high_confidence_invoice(self, mock_anthropic_cls):
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        client.messages.create = AsyncMock(return_value=_make_mock_response(
            "invoice", 0.95, "Contains invoice number and line items"
        ))

        result = await classify("Invoice #12345\nTotal: $500.00")

        assert isinstance(result, ClassificationResult)
        assert result.doc_type == "invoice"
        assert result.confidence == 0.95
        assert "invoice number" in result.reasoning

    @patch("app.services.classifier.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_receipt_classification(self, mock_anthropic_cls):
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        client.messages.create = AsyncMock(return_value=_make_mock_response(
            "receipt", 0.88, "Merchant name and payment method present"
        ))

        result = await classify("Merchant: Coffee Shop\nTotal: $5.50\nVisa ***1234")
        assert result.doc_type == "receipt"
        assert result.confidence == 0.88


class TestClassifyLowConfidence:
    @patch("app.services.classifier.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_low_confidence_falls_back_to_unknown(self, mock_anthropic_cls):
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        client.messages.create = AsyncMock(return_value=_make_mock_response(
            "invoice", 0.4, "Unclear document"
        ))

        result = await classify("Some ambiguous text")
        assert result.doc_type == "unknown"
        assert result.confidence == 0.4

    @patch("app.services.classifier.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_exactly_threshold_stays_unknown(self, mock_anthropic_cls):
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        client.messages.create = AsyncMock(return_value=_make_mock_response(
            "bank_statement", 0.59, "Borderline"
        ))

        result = await classify("text")
        assert result.doc_type == "unknown"


class TestClassifyErrors:
    @patch("app.services.classifier.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_api_error_returns_unknown(self, mock_anthropic_cls):
        import anthropic

        client = MagicMock()
        mock_anthropic_cls.return_value = client
        client.messages.create = AsyncMock(
            side_effect=anthropic.APIConnectionError(request=MagicMock())
        )

        result = await classify("Some text")
        assert result.doc_type == "unknown"
        assert result.confidence == 0.0

    @patch("app.services.classifier.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_json_parse_error_returns_unknown(self, mock_anthropic_cls):
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        content_block = MagicMock()
        content_block.text = "not valid json {{"
        response = MagicMock()
        response.content = [content_block]
        client.messages.create = AsyncMock(return_value=response)

        result = await classify("Some text")
        assert result.doc_type == "unknown"
        assert result.confidence == 0.0

    @patch("app.services.classifier.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_empty_content_returns_unknown(self, mock_anthropic_cls):
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        client.messages.create = AsyncMock(
            side_effect=IndexError("list index out of range")
        )

        result = await classify("Some text")
        assert result.doc_type == "unknown"


class TestClassifyUsesFirst2000Chars:
    @patch("app.services.classifier.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_text_truncated(self, mock_anthropic_cls):
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        client.messages.create = AsyncMock(return_value=_make_mock_response(
            "invoice", 0.9, "Invoice detected"
        ))

        long_text = "x" * 5000
        await classify(long_text)

        call_args = client.messages.create.call_args
        prompt_content = call_args.kwargs["messages"][0]["content"]
        # The prompt includes the first 2000 chars of the text
        assert "x" * 2000 in prompt_content
        assert "x" * 2001 not in prompt_content


class TestDocumentTypes:
    def test_all_expected_types(self):
        expected = {
            "invoice", "purchase_order", "receipt",
            "bank_statement", "identity_document", "medical_record", "unknown",
        }
        assert set(DOCUMENT_TYPES) == expected


class TestClassifyTool:
    def test_classify_tool_has_required_fields(self):
        assert "name" in CLASSIFY_TOOL
        assert "input_schema" in CLASSIFY_TOOL
        assert CLASSIFY_TOOL["name"] == "classify_document"

    def test_classify_tool_schema_has_document_types(self):
        props = CLASSIFY_TOOL["input_schema"]["properties"]
        assert "document_type" in props
        assert "confidence" in props


class TestClassifyToolUse:
    """Tests for tool_use based classification."""

    def _make_tool_use_response(self, doc_type: str, confidence: float, reasoning: str) -> MagicMock:
        """Build a mock response with tool_use block."""
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "classify_document"
        tool_block.input = {
            "document_type": doc_type,
            "confidence": confidence,
            "reasoning": reasoning,
        }
        response = MagicMock()
        response.content = [tool_block]
        return response

    @patch("app.services.classifier.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_tool_use_response_parsed(self, mock_anthropic_cls):
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        client.messages.create = AsyncMock(return_value=self._make_tool_use_response(
            "invoice", 0.92, "Contains invoice number"
        ))
        result = await classify("Invoice #001")
        assert result.doc_type == "invoice"
        assert result.confidence == 0.92

    @patch("app.services.classifier.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_tool_choice_passed_to_api(self, mock_anthropic_cls):
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        client.messages.create = AsyncMock(return_value=self._make_tool_use_response(
            "receipt", 0.9, "Receipt"
        ))
        await classify("some text")
        call_kwargs = client.messages.create.call_args.kwargs
        assert "tools" in call_kwargs
        assert "tool_choice" in call_kwargs
        assert call_kwargs["tool_choice"]["name"] == "classify_document"

    @patch("app.services.classifier.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_legacy_text_fallback(self, mock_anthropic_cls):
        """If no tool_use block, falls back to text parsing."""
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = json.dumps({
            "document_type": "bank_statement",
            "confidence": 0.88,
            "reasoning": "Legacy format",
        })
        response = MagicMock()
        response.content = [text_block]
        client.messages.create = AsyncMock(return_value=response)
        result = await classify("some text")
        assert result.doc_type == "bank_statement"

    @patch("app.services.classifier.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_classify_with_db_none(self, mock_anthropic_cls):
        """db=None (default) should work without DB."""
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        client.messages.create = AsyncMock(return_value=self._make_tool_use_response(
            "invoice", 0.95, "Invoice"
        ))
        result = await classify("Invoice text", db=None)
        assert result.doc_type == "invoice"

    @patch("app.services.classifier.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_classify_records_in_memory_trace(self, mock_anthropic_cls):
        from app.services.llm_tracer import clear_in_memory_traces, get_in_memory_traces
        clear_in_memory_traces()
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        client.messages.create = AsyncMock(return_value=self._make_tool_use_response(
            "invoice", 0.9, "Invoice"
        ))
        await classify("Invoice text", db=None)
        traces = get_in_memory_traces()
        assert len(traces) >= 1
        assert any(t["operation"] == "classify" for t in traces)
        clear_in_memory_traces()
