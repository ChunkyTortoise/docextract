"""Tests for utility scripts."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("API_KEY_SECRET", "test-secret-key-that-is-32-chars!")


def test_seed_sample_docs_creates_files() -> None:
    """seed_sample_docs creates all expected fixture files."""
    from scripts.seed_sample_docs import create_fixtures

    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir)
        create_fixtures(output)

        expected = [
            "sample_invoice.pdf",
            "sample_receipt.png",
            "sample_email.eml",
            "sample_invoice_text.txt",
            "sample_receipt_text.txt",
            "sample_lead_capture_text.txt",
            "sample_extracted_invoice.json",
        ]
        for name in expected:
            filepath = output / name
            assert filepath.exists(), f"Missing fixture: {name}"
            assert filepath.stat().st_size > 0, f"Empty fixture: {name}"


def test_sample_pdf_has_valid_header() -> None:
    """The minimal PDF starts with %PDF header."""
    from scripts.seed_sample_docs import MINIMAL_PDF
    assert MINIMAL_PDF.startswith(b"%PDF-")


def test_sample_png_has_valid_header() -> None:
    """The minimal PNG starts with PNG magic bytes."""
    from scripts.seed_sample_docs import MINIMAL_PNG
    assert MINIMAL_PNG[:4] == b"\x89PNG"


def test_sample_eml_has_headers() -> None:
    """The minimal EML contains required email headers."""
    from scripts.seed_sample_docs import MINIMAL_EML
    text = MINIMAL_EML.decode("utf-8")
    assert "From:" in text
    assert "To:" in text
    assert "Subject:" in text


def test_sample_extracted_invoice_valid_json() -> None:
    """The sample extracted invoice has all required fields."""
    from scripts.seed_sample_docs import SAMPLE_EXTRACTED_INVOICE
    assert SAMPLE_EXTRACTED_INVOICE["document_type"] == "vendor_invoice"
    assert "invoice_number" in SAMPLE_EXTRACTED_INVOICE
    assert "line_items" in SAMPLE_EXTRACTED_INVOICE
    assert len(SAMPLE_EXTRACTED_INVOICE["line_items"]) == 3
    assert "confidence_score" in SAMPLE_EXTRACTED_INVOICE


def test_seed_api_key_module_imports() -> None:
    """seed_api_key module can be imported."""
    from scripts.seed_api_key import seed_api_key
    assert seed_api_key is not None


def test_cleanup_storage_module_imports() -> None:
    """cleanup_storage module can be imported."""
    from scripts.cleanup_storage import run_cleanup
    assert run_cleanup is not None


def test_fixture_json_is_parseable() -> None:
    """The generated JSON fixture file is valid JSON."""
    from scripts.seed_sample_docs import SAMPLE_EXTRACTED_INVOICE, create_fixtures

    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir)
        create_fixtures(output)

        json_file = output / "sample_extracted_invoice.json"
        data = json.loads(json_file.read_text())
        assert data["invoice_number"] == SAMPLE_EXTRACTED_INVOICE["invoice_number"]
