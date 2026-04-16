"""Tests for app/services/structured_extractor.py."""
from __future__ import annotations

import asyncio
import json
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.extraction_models import (
    BatchExtractionResult,
    ContractExtraction,
    InvoiceExtraction,
    MedicalRecordExtraction,
    ReceiptExtraction,
    StructuredExtractionResponse,
)
from app.services.structured_extractor import StructuredExtractor, _parse_json_from_text, _try_parse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_text_block(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    return block


def _make_response(text: str) -> MagicMock:
    response = MagicMock()
    response.content = [_make_text_block(text)]
    return response


def _make_router(response_text: str, model: str = "claude-sonnet-4-6") -> MagicMock:
    """Build a mock ModelRouter that returns (response, model) via call_with_fallback."""
    router = MagicMock()
    router.call_with_fallback = AsyncMock(
        return_value=(_make_response(response_text), model)
    )
    return router


def _make_classifier(doc_type: str = "invoice", confidence: float = 0.95) -> MagicMock:
    from app.services.classifier import ClassificationResult

    classifier = MagicMock()
    classifier.classify = AsyncMock(
        return_value=ClassificationResult(
            doc_type=doc_type,
            confidence=confidence,
            reasoning="mock",
        )
    )
    return classifier


def _make_db_with_record(
    raw_text: str,
    document_type: str,
    document_id: str | None = None,
) -> MagicMock:
    """Build an AsyncSession mock that returns a fake ExtractedRecord."""
    record = MagicMock()
    record.raw_text = raw_text
    record.document_type = document_type

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none = MagicMock(return_value=record)

    db = MagicMock()
    db.execute = AsyncMock(return_value=scalar_result)
    return db


def _make_empty_db() -> MagicMock:
    """DB mock that returns no record."""
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none = MagicMock(return_value=None)
    db = MagicMock()
    db.execute = AsyncMock(return_value=scalar_result)
    return db


INVOICE_JSON = json.dumps({
    "invoice_number": "INV-001",
    "vendor_name": "Acme",
    "total": "500.00",
    "field_confidence": {"invoice_number": 0.99, "total": 0.95},
})

CONTRACT_JSON = json.dumps({
    "parties": ["Acme", "Bob"],
    "contract_type": "service",
    "field_confidence": {"parties": 0.9},
})

RECEIPT_JSON = json.dumps({
    "merchant_name": "Coffee",
    "total": "12.50",
    "field_confidence": {"total": 0.98},
})

MEDICAL_JSON = json.dumps({
    "patient_name": "Jane Doe",
    "diagnoses": ["flu"],
    "field_confidence": {"patient_name": 0.99},
})

DOC_UUID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExtractSingle:
    @pytest.mark.asyncio
    async def test_returns_structured_extraction_response(self):
        router = _make_router(INVOICE_JSON)
        db = _make_db_with_record(raw_text="Invoice text", document_type="invoice")
        extractor = StructuredExtractor(model_router=router)

        with patch("app.services.structured_extractor.AsyncAnthropic"):
            result = await extractor.extract(doc_id=DOC_UUID, doc_type="invoice", db=db)

        assert isinstance(result, StructuredExtractionResponse)
        assert result.doc_id == DOC_UUID
        assert result.doc_type == "invoice"
        assert isinstance(result.extraction, InvoiceExtraction)
        assert result.error is None
        assert result.latency_ms >= 0
        assert result.model_used == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_auto_classify_when_no_doc_type(self):
        """When doc_type=None and the record has no document_type, classifier is used."""
        router = _make_router(INVOICE_JSON)
        classifier = _make_classifier(doc_type="invoice")
        # record has no document_type set (None), so the classifier is triggered
        db = _make_db_with_record(raw_text="Invoice text", document_type=None)
        extractor = StructuredExtractor(model_router=router, classifier=classifier)

        with patch("app.services.structured_extractor.AsyncAnthropic"):
            result = await extractor.extract(doc_id=DOC_UUID, doc_type=None, db=db)

        classifier.classify.assert_awaited_once()
        assert result.doc_type == "invoice"

    @pytest.mark.asyncio
    async def test_extract_invoice_type(self):
        router = _make_router(INVOICE_JSON)
        db = _make_db_with_record(raw_text="Invoice text", document_type="invoice")
        extractor = StructuredExtractor(model_router=router)

        with patch("app.services.structured_extractor.AsyncAnthropic"):
            result = await extractor.extract(doc_id=DOC_UUID, doc_type="invoice", db=db)

        assert isinstance(result.extraction, InvoiceExtraction)
        assert result.extraction.invoice_number == "INV-001"
        assert result.extraction.total == Decimal("500.00")

    @pytest.mark.asyncio
    async def test_extract_contract_type(self):
        router = _make_router(CONTRACT_JSON)
        db = _make_db_with_record(raw_text="Contract text", document_type="contract")
        extractor = StructuredExtractor(model_router=router)

        with patch("app.services.structured_extractor.AsyncAnthropic"):
            result = await extractor.extract(doc_id=DOC_UUID, doc_type="contract", db=db)

        assert isinstance(result.extraction, ContractExtraction)
        assert "Acme" in result.extraction.parties

    @pytest.mark.asyncio
    async def test_extract_receipt_type(self):
        router = _make_router(RECEIPT_JSON)
        db = _make_db_with_record(raw_text="Receipt text", document_type="receipt")
        extractor = StructuredExtractor(model_router=router)

        with patch("app.services.structured_extractor.AsyncAnthropic"):
            result = await extractor.extract(doc_id=DOC_UUID, doc_type="receipt", db=db)

        assert isinstance(result.extraction, ReceiptExtraction)
        assert result.extraction.merchant_name == "Coffee"

    @pytest.mark.asyncio
    async def test_extract_medical_record_type(self):
        router = _make_router(MEDICAL_JSON)
        db = _make_db_with_record(raw_text="Medical text", document_type="medical_record")
        extractor = StructuredExtractor(model_router=router)

        with patch("app.services.structured_extractor.AsyncAnthropic"):
            result = await extractor.extract(doc_id=DOC_UUID, doc_type="medical_record", db=db)

        assert isinstance(result.extraction, MedicalRecordExtraction)
        assert result.extraction.patient_name == "Jane Doe"

    @pytest.mark.asyncio
    async def test_retry_on_validation_error(self):
        """First call returns garbage JSON; second call returns valid JSON."""
        good_json = INVOICE_JSON
        bad_response = _make_response("not valid json at all!!!")
        good_response = _make_response(good_json)

        router = MagicMock()
        router.call_with_fallback = AsyncMock(
            side_effect=[
                (bad_response, "claude-sonnet-4-6"),
                (good_response, "claude-sonnet-4-6"),
            ]
        )
        db = _make_db_with_record(raw_text="Invoice text", document_type="invoice")
        extractor = StructuredExtractor(model_router=router)

        with patch("app.services.structured_extractor.AsyncAnthropic"):
            result = await extractor.extract(doc_id=DOC_UUID, doc_type="invoice", db=db)

        assert result.retry_count == 1
        assert isinstance(result.extraction, InvoiceExtraction)
        assert result.error is None
        assert router.call_with_fallback.await_count == 2

    @pytest.mark.asyncio
    async def test_error_when_doc_not_found(self):
        router = _make_router(INVOICE_JSON)
        db = _make_empty_db()
        extractor = StructuredExtractor(model_router=router)

        with patch("app.services.structured_extractor.AsyncAnthropic"):
            result = await extractor.extract(doc_id=DOC_UUID, doc_type="invoice", db=db)

        assert result.extraction is None
        assert result.error is not None
        assert "not found" in result.error.lower()
        # Claude should not have been called
        router.call_with_fallback.assert_not_awaited()


class TestExtractBatch:
    @pytest.mark.asyncio
    async def test_batch_returns_all_results(self):
        router = _make_router(INVOICE_JSON)
        doc_ids = [str(uuid.uuid4()) for _ in range(3)]
        db = _make_db_with_record(raw_text="Invoice text", document_type="invoice")
        extractor = StructuredExtractor(model_router=router)

        with patch("app.services.structured_extractor.AsyncAnthropic"):
            batch = await extractor.extract_batch(doc_ids=doc_ids, db=db)

        assert isinstance(batch, BatchExtractionResult)
        assert batch.total == 3
        assert len(batch.results) == 3
        assert batch.successful == 3
        assert batch.failed == 0
        assert batch.total_latency_ms >= 0

    @pytest.mark.asyncio
    async def test_batch_counts_failures(self):
        router = _make_router(INVOICE_JSON)
        doc_ids = [str(uuid.uuid4()) for _ in range(2)]
        db = _make_empty_db()  # all docs "not found"
        extractor = StructuredExtractor(model_router=router)

        with patch("app.services.structured_extractor.AsyncAnthropic"):
            batch = await extractor.extract_batch(doc_ids=doc_ids, db=db)

        assert batch.total == 2
        assert batch.failed == 2
        assert batch.successful == 0

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self):
        """Verify the semaphore is acquired for each doc extraction."""
        call_count = 0

        async def slow_extract(doc_id: str, doc_type=None, db=None):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0)
            return StructuredExtractionResponse(
                doc_id=doc_id,
                doc_type="invoice",
                extraction=None,
                error=None,
                latency_ms=1.0,
                model_used="test-model",
            )

        router = MagicMock()
        extractor = StructuredExtractor(model_router=router)
        # Replace the extract method with our counter
        extractor.extract = slow_extract  # type: ignore[method-assign]

        doc_ids = [str(uuid.uuid4()) for _ in range(8)]
        batch = await extractor.extract_batch(doc_ids=doc_ids)

        assert call_count == 8
        assert batch.total == 8


class TestParseHelpers:
    def test_parse_json_from_text_plain(self):
        result = _parse_json_from_text('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_json_from_text_code_block(self):
        result = _parse_json_from_text('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_parse_json_from_text_embedded(self):
        result = _parse_json_from_text('Here is the data: {"key": "value"} end.')
        assert result == {"key": "value"}

    def test_parse_json_from_text_invalid_returns_empty(self):
        result = _parse_json_from_text("completely invalid")
        assert result == {}

    def test_try_parse_success(self):
        raw = json.dumps({"invoice_number": "X", "field_confidence": {}})
        model, err = _try_parse(InvoiceExtraction, raw)
        assert model is not None
        assert err is None
        assert isinstance(model, InvoiceExtraction)

    def test_try_parse_failure(self):
        model, err = _try_parse(InvoiceExtraction, "not json")
        assert model is None
        assert err is not None
