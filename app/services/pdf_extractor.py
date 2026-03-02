"""PDF text and table extraction using PyMuPDF and pdfplumber."""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field

import fitz  # PyMuPDF
import pdfplumber

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ExtractedContent:
    """Container for extracted document content."""

    text: str
    metadata: dict = field(default_factory=dict)
    page_count: int = 1


def extract_pdf(data: bytes) -> ExtractedContent:
    """Extract text and tables from a PDF.

    Uses PyMuPDF for text extraction, falls back to pdfplumber for tables.
    Scanned pages (no text blocks) are rendered to images at 300 DPI for OCR.

    Args:
        data: Raw PDF bytes

    Returns:
        ExtractedContent with concatenated page text and metadata

    Raises:
        ValueError: If PDF is corrupt or encrypted
    """
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except fitz.FitzError as exc:
        raise ValueError(f"Corrupt or unreadable PDF: {exc}") from exc

    if doc.is_encrypted:
        doc.close()
        raise ValueError("PDF is encrypted")

    max_pages = settings.max_pages
    total_pages = min(doc.page_count, max_pages)
    has_tables = False
    page_texts: list[str] = []

    for page_num in range(total_pages):
        page = doc[page_num]
        blocks = page.get_text("blocks")

        if blocks:
            # Text-native page — extract text from blocks
            page_text = "\n".join(
                block[4] for block in blocks if block[6] == 0  # type 0 = text
            )
        else:
            # Scanned page — render to image for OCR
            from app.services.image_extractor import extract_image
            from app.services.preprocessor import preprocess_image

            pixmap = page.get_pixmap(dpi=300)
            import numpy as np

            img_array = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                pixmap.height, pixmap.width, pixmap.n
            )
            preprocessed = preprocess_image(img_array)
            result = extract_image(preprocessed, engine=settings.ocr_engine)
            page_text = result.text

        page_texts.append(page_text)

    doc.close()

    # Extract tables via pdfplumber
    table_texts: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page_num, page in enumerate(pdf.pages[:total_pages]):
                tables = page.extract_tables()
                if tables:
                    has_tables = True
                    for table in tables:
                        table_texts.append(_table_to_markdown(table))
    except Exception:
        logger.warning("pdfplumber table extraction failed", exc_info=True)

    # Combine page texts with markers
    combined_parts: list[str] = []
    for i, text in enumerate(page_texts):
        if i > 0:
            combined_parts.append(f"\n---PAGE {i + 1}---\n")
        combined_parts.append(text.strip())

    # Append table content if found
    if table_texts:
        combined_parts.append("\n\n--- TABLES ---\n")
        combined_parts.extend(table_texts)

    combined_text = "\n".join(combined_parts)

    return ExtractedContent(
        text=combined_text,
        metadata={
            "page_count": total_pages,
            "total_pages_in_pdf": doc.page_count if not doc.is_closed else total_pages,
            "has_tables": has_tables,
            "truncated": doc.page_count > max_pages if not doc.is_closed else False,
        },
        page_count=total_pages,
    )


def _table_to_markdown(table: list[list[str | None]]) -> str:
    """Convert a pdfplumber table to markdown format."""
    if not table:
        return ""

    rows: list[str] = []
    for row in table:
        cells = [str(cell) if cell is not None else "" for cell in row]
        rows.append("| " + " | ".join(cells) + " |")

        # Add header separator after first row
        if len(rows) == 1:
            rows.append("| " + " | ".join("---" for _ in cells) + " |")

    return "\n".join(rows)
