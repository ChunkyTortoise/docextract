"""MIME-type-based routing to appropriate extractor."""
from __future__ import annotations

import logging
import time

from app.config import settings
from app.services.email_extractor import extract_eml, extract_msg_file
from app.services.image_extractor import extract_image
from app.services.pdf_extractor import ExtractedContent, extract_pdf
from app.services.preprocessor import preprocess_bytes
from app.utils.mime import is_allowed_mime_type

logger = logging.getLogger(__name__)

IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/bmp",
    "image/gif",
    "image/webp",
}


class UnsupportedMimeType(Exception):
    pass


def ingest(file_bytes: bytes, mime_type: str, filename: str) -> ExtractedContent:
    """Route document to appropriate extractor based on MIME type.

    Args:
        file_bytes: Raw file content
        mime_type: Detected MIME type
        filename: Original filename (for logging)

    Returns:
        ExtractedContent with text and metadata

    Raises:
        UnsupportedMimeType: If MIME type is not supported
    """
    start = time.monotonic()

    if mime_type == "application/pdf":
        result = extract_pdf(file_bytes)
    elif mime_type in IMAGE_MIME_TYPES:
        image = preprocess_bytes(file_bytes)
        result = extract_image(image, engine=settings.ocr_engine)
    elif mime_type == "message/rfc822":
        result = extract_eml(file_bytes)
    elif mime_type == "application/vnd.ms-outlook":
        result = extract_msg_file(file_bytes)
    else:
        raise UnsupportedMimeType(f"Unsupported MIME type: {mime_type}")

    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "Ingestion complete",
        extra={
            "mime_type": mime_type,
            "doc_filename": filename,
            "file_size_bytes": len(file_bytes),
            "extraction_time_ms": elapsed_ms,
            "page_count": result.page_count,
        },
    )
    return result
