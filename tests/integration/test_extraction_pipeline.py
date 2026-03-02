"""Integration tests for the extraction pipeline."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.ingestion import UnsupportedMimeType, ingest
from app.services.pdf_extractor import ExtractedContent


def test_ingestion_routing_pdf():
    """PDF files route to pdf_extractor."""
    with patch("app.services.ingestion.extract_pdf") as mock_pdf:
        mock_pdf.return_value = ExtractedContent(text="Invoice content", page_count=1)

        result = ingest(b"%PDF-1.4", "application/pdf", "test.pdf")

        mock_pdf.assert_called_once()
        assert result.text == "Invoice content"


def test_ingestion_routing_unsupported():
    """Unsupported MIME raises UnsupportedMimeType."""
    with pytest.raises(UnsupportedMimeType):
        ingest(b"data", "application/zip", "test.zip")


def test_chunker_splits_long_text():
    """Long text with sentence boundaries is split into chunks."""
    from app.services.chunker import chunk_text

    # Create text with sentence boundaries so the chunker can split
    sentence = "This is a test sentence with enough words to be meaningful. "
    long_text = sentence * 1000  # ~60000 chars, well over MAX_CHUNK_TOKENS
    chunks = chunk_text(long_text)
    assert len(chunks) > 1


def test_chunker_empty_text():
    """Empty text returns empty list."""
    from app.services.chunker import chunk_text

    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_validator_invoice_total():
    """Invoice validation catches total mismatch."""
    from app.services.validator import validate

    result = validate(
        "invoice",
        {
            "subtotal": 100.0,
            "tax_amount": 10.0,
            "discount_amount": 0.0,
            "total_amount": 200.0,  # Should be 110
        },
    )

    assert not result.is_valid
    assert any(e.error_type == "CALCULATION_MISMATCH" for e in result.errors)


def test_validator_invoice_valid():
    """Valid invoice passes validation."""
    from app.services.validator import validate

    result = validate(
        "invoice",
        {
            "invoice_number": "INV-001",
            "subtotal": 100.0,
            "tax_amount": 10.0,
            "discount_amount": 0.0,
            "total_amount": 110.0,
        },
    )

    assert result.is_valid


def test_validator_unknown_type():
    """Unknown document type passes without errors."""
    from app.services.validator import validate

    result = validate("unknown_type", {"field": "value"})
    assert result.is_valid
