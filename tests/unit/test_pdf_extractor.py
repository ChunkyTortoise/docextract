"""Tests for PDF extractor with mocked fitz/pdfplumber."""
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from app.services.pdf_extractor import extract_pdf, ExtractedContent


def _make_mock_page(text_blocks: list[tuple] | None = None) -> MagicMock:
    """Create a mock fitz page."""
    page = MagicMock()
    if text_blocks is None:
        # Default: one text block
        text_blocks = [
            (0, 0, 100, 20, "Sample text on page", 0, 0),
        ]
    page.get_text.return_value = text_blocks
    return page


def _make_mock_doc(
    pages: list[MagicMock] | None = None,
    page_count: int = 1,
    encrypted: bool = False,
) -> MagicMock:
    """Create a mock fitz document."""
    doc = MagicMock()
    doc.is_encrypted = encrypted
    doc.page_count = page_count
    doc.is_closed = False

    if pages is None:
        pages = [_make_mock_page() for _ in range(page_count)]

    doc.__getitem__ = lambda self, idx: pages[idx]
    return doc


@patch("app.services.pdf_extractor.pdfplumber")
@patch("app.services.pdf_extractor.fitz")
def test_extract_pdf_normal(mock_fitz: MagicMock, mock_pdfplumber: MagicMock) -> None:
    """Normal PDF extraction returns ExtractedContent."""
    mock_doc = _make_mock_doc()
    mock_fitz.open.return_value = mock_doc

    # pdfplumber returns no tables
    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_page.extract_tables.return_value = []
    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__ = lambda self: mock_pdf
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdfplumber.open.return_value = mock_pdf

    result = extract_pdf(b"fake-pdf-bytes")

    assert isinstance(result, ExtractedContent)
    assert "Sample text on page" in result.text
    assert result.metadata["page_count"] == 1
    assert result.page_count == 1


@patch("app.services.pdf_extractor.fitz")
def test_extract_pdf_corrupt(mock_fitz: MagicMock) -> None:
    """Corrupt PDF raises ValueError."""
    import fitz as real_fitz

    mock_fitz.FitzError = real_fitz.FitzError if hasattr(real_fitz, "FitzError") else Exception
    mock_fitz.open.side_effect = mock_fitz.FitzError("corrupt")

    with pytest.raises(ValueError, match="Corrupt"):
        extract_pdf(b"not-a-pdf")


@patch("app.services.pdf_extractor.fitz")
def test_extract_pdf_encrypted(mock_fitz: MagicMock) -> None:
    """Encrypted PDF raises ValueError."""
    mock_doc = _make_mock_doc(encrypted=True)
    mock_fitz.open.return_value = mock_doc

    with pytest.raises(ValueError, match="encrypted"):
        extract_pdf(b"encrypted-pdf-bytes")


@patch("app.services.pdf_extractor.pdfplumber")
@patch("app.services.pdf_extractor.fitz")
def test_extract_pdf_page_markers(mock_fitz: MagicMock, mock_pdfplumber: MagicMock) -> None:
    """Multi-page PDFs include page markers."""
    pages = [
        _make_mock_page([(0, 0, 100, 20, "Page one text", 0, 0)]),
        _make_mock_page([(0, 0, 100, 20, "Page two text", 0, 0)]),
    ]
    mock_doc = _make_mock_doc(pages=pages, page_count=2)
    mock_fitz.open.return_value = mock_doc

    mock_pdf = MagicMock()
    mock_p1 = MagicMock()
    mock_p1.extract_tables.return_value = []
    mock_p2 = MagicMock()
    mock_p2.extract_tables.return_value = []
    mock_pdf.pages = [mock_p1, mock_p2]
    mock_pdf.__enter__ = lambda self: mock_pdf
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdfplumber.open.return_value = mock_pdf

    result = extract_pdf(b"multi-page-pdf")

    assert "---PAGE 2---" in result.text
    assert "Page one text" in result.text
    assert "Page two text" in result.text
    assert result.page_count == 2


@patch("app.services.pdf_extractor.settings")
@patch("app.services.pdf_extractor.pdfplumber")
@patch("app.services.pdf_extractor.fitz")
def test_extract_pdf_max_pages_truncation(
    mock_fitz: MagicMock,
    mock_pdfplumber: MagicMock,
    mock_settings: MagicMock,
) -> None:
    """PDFs exceeding MAX_PAGES are truncated."""
    mock_settings.max_pages = 2
    mock_settings.ocr_engine = "tesseract"

    pages = [_make_mock_page() for _ in range(5)]
    mock_doc = _make_mock_doc(pages=pages, page_count=5)
    mock_fitz.open.return_value = mock_doc

    mock_pdf = MagicMock()
    mock_p = MagicMock()
    mock_p.extract_tables.return_value = []
    mock_pdf.pages = [mock_p, mock_p]
    mock_pdf.__enter__ = lambda self: mock_pdf
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdfplumber.open.return_value = mock_pdf

    result = extract_pdf(b"big-pdf")

    assert result.page_count == 2
    assert result.metadata["truncated"] is True
