"""Tests for ingestion router — mocks all extractors."""
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.services.ingestion import UnsupportedMimeType, ingest
from app.services.pdf_extractor import ExtractedContent


def _mock_result(text: str = "extracted text") -> ExtractedContent:
    return ExtractedContent(text=text, metadata={}, page_count=1)


@pytest.mark.asyncio
@patch("app.services.ingestion.extract_pdf")
async def test_pdf_routing(mock_extract: MagicMock) -> None:
    """PDF MIME type routes to extract_pdf (via asyncio.to_thread)."""
    mock_extract.return_value = _mock_result("pdf text")

    result = await ingest(b"pdf-bytes", "application/pdf", "doc.pdf")

    mock_extract.assert_called_once_with(b"pdf-bytes")
    assert result.text == "pdf text"


@pytest.mark.asyncio
@patch("app.services.ingestion.extract_image")
@patch("app.services.ingestion.preprocess_bytes")
async def test_jpeg_routing(
    mock_preprocess: MagicMock, mock_extract: MagicMock
) -> None:
    """JPEG MIME type routes through preprocess_bytes + extract_image."""
    mock_preprocess.return_value = np.zeros((100, 100), dtype=np.uint8)
    mock_extract.return_value = _mock_result("image text")

    result = await ingest(b"jpeg-bytes", "image/jpeg", "photo.jpg")

    mock_preprocess.assert_called_once_with(b"jpeg-bytes")
    mock_extract.assert_called_once()
    assert result.text == "image text"


@pytest.mark.asyncio
@patch("app.services.ingestion.extract_image")
@patch("app.services.ingestion.preprocess_bytes")
async def test_png_routing(
    mock_preprocess: MagicMock, mock_extract: MagicMock
) -> None:
    """PNG MIME type routes through preprocess_bytes + extract_image."""
    mock_preprocess.return_value = np.zeros((100, 100), dtype=np.uint8)
    mock_extract.return_value = _mock_result("png text")

    result = await ingest(b"png-bytes", "image/png", "scan.png")

    mock_preprocess.assert_called_once()
    assert result.text == "png text"


@pytest.mark.asyncio
@patch("app.services.ingestion.extract_eml")
async def test_eml_routing(mock_extract: MagicMock) -> None:
    """EML MIME type routes to extract_eml."""
    mock_extract.return_value = _mock_result("email text")

    result = await ingest(b"eml-bytes", "message/rfc822", "mail.eml")

    mock_extract.assert_called_once_with(b"eml-bytes")
    assert result.text == "email text"


@pytest.mark.asyncio
@patch("app.services.ingestion.extract_msg_file")
async def test_msg_routing(mock_extract: MagicMock) -> None:
    """MSG MIME type routes to extract_msg_file."""
    mock_extract.return_value = _mock_result("msg text")

    result = await ingest(b"msg-bytes", "application/vnd.ms-outlook", "mail.msg")

    mock_extract.assert_called_once_with(b"msg-bytes")
    assert result.text == "msg text"


@pytest.mark.asyncio
async def test_unsupported_mime_raises() -> None:
    """Unsupported MIME type raises UnsupportedMimeType."""
    with pytest.raises(UnsupportedMimeType, match="Unsupported MIME type"):
        await ingest(b"data", "application/xml", "data.xml")


@pytest.mark.asyncio
@patch("app.services.ingestion.extract_pdf")
async def test_timing_logged(
    mock_extract: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """Ingestion logs timing metadata."""
    import logging

    mock_extract.return_value = _mock_result()

    with caplog.at_level(logging.INFO):
        await ingest(b"pdf-data", "application/pdf", "timed.pdf")

    assert "Ingestion complete" in caplog.text
