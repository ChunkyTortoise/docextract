"""Tests for classifier service."""
from unittest.mock import AsyncMock, MagicMock, patch
import json

import pytest

from app.services.classifier import ClassificationResult, classify, DOCUMENT_TYPES


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
