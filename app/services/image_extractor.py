"""Image OCR extraction using pytesseract (default) or PaddleOCR (opt-in)."""
from __future__ import annotations

import logging

import numpy as np

try:
    import pytesseract
    from pytesseract import Output

    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

try:
    from paddleocr import PaddleOCR

    HAS_PADDLE = True
except ImportError:
    HAS_PADDLE = False

from app.services.pdf_extractor import ExtractedContent

logger = logging.getLogger(__name__)

# Lazy-initialized PaddleOCR instance (heavy model load)
_paddle_instance: PaddleOCR | None = None


def _get_paddle_ocr() -> PaddleOCR:
    """Get or create PaddleOCR instance (singleton)."""
    global _paddle_instance
    if _paddle_instance is None:
        _paddle_instance = PaddleOCR(use_angle_cls=True, lang="en")
    return _paddle_instance


def extract_image(
    image: np.ndarray, engine: str = "tesseract"
) -> ExtractedContent:
    """Extract text from a preprocessed image using OCR.

    Args:
        image: Preprocessed grayscale numpy array
        engine: OCR engine — "tesseract" (default) or "paddle"

    Returns:
        ExtractedContent with extracted text and engine metadata

    Raises:
        RuntimeError: If the requested engine is not installed
    """
    if engine == "paddle" and HAS_PADDLE:
        text = _extract_with_paddle(image)
    elif engine == "paddle" and not HAS_PADDLE:
        logger.warning("PaddleOCR not installed, falling back to tesseract")
        text = _extract_with_tesseract(image)
    elif HAS_TESSERACT:
        text = _extract_with_tesseract(image)
    else:
        raise RuntimeError(
            "No OCR engine available. Install pytesseract or paddleocr."
        )

    actual_engine = engine if (engine == "paddle" and HAS_PADDLE) else "tesseract"

    return ExtractedContent(
        text=text,
        metadata={"engine": actual_engine},
        page_count=1,
    )


def _extract_with_tesseract(image: np.ndarray) -> str:
    """Extract text using pytesseract with reading-order reconstruction."""
    data = pytesseract.image_to_data(image, output_type=Output.DICT)

    # Build word entries with positions for reading-order sorting
    entries: list[tuple[int, int, str]] = []
    n_items = len(data["text"])
    for i in range(n_items):
        text = data["text"][i].strip()
        if not text:
            continue
        top = data["top"][i]
        left = data["left"][i]
        entries.append((top, left, text))

    # Sort top-to-bottom, then left-to-right for reading order
    entries.sort(key=lambda e: (e[0], e[1]))

    # Group words into lines (words within 10px vertical distance)
    if not entries:
        return ""

    lines: list[list[str]] = []
    current_line: list[str] = [entries[0][2]]
    current_top = entries[0][0]

    for top, _left, text in entries[1:]:
        if abs(top - current_top) <= 10:
            current_line.append(text)
        else:
            lines.append(current_line)
            current_line = [text]
            current_top = top

    lines.append(current_line)

    return "\n".join(" ".join(line) for line in lines)


def _extract_with_paddle(image: np.ndarray) -> str:
    """Extract text using PaddleOCR with spatial reading-order reconstruction."""
    ocr = _get_paddle_ocr()
    results = ocr.ocr(image, cls=True)

    if not results or not results[0]:
        return ""

    # Each result entry: [bbox_coords, (text, confidence)]
    entries: list[tuple[float, float, str]] = []
    for line in results[0]:
        bbox = line[0]
        text = line[1][0]
        # Use top-left corner for ordering
        top = bbox[0][1]
        left = bbox[0][0]
        entries.append((top, left, text))

    # Sort top-to-bottom, then left-to-right
    entries.sort(key=lambda e: (e[0], e[1]))

    return "\n".join(entry[2] for entry in entries)
