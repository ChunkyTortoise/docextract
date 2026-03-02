"""Tests for image extractor with mocked OCR engines."""
from unittest.mock import MagicMock, patch, PropertyMock
import sys

import numpy as np
import pytest

from app.services.pdf_extractor import ExtractedContent


# Create a mock pytesseract module so the image_extractor can import it
_mock_pytesseract = MagicMock()
_mock_pytesseract.Output = MagicMock()
_mock_pytesseract.Output.DICT = "dict"


@pytest.fixture(autouse=True)
def _inject_pytesseract():
    """Inject mock pytesseract and force fresh image_extractor import for each test."""
    import app.services as _svc_pkg

    sys.modules["pytesseract"] = _mock_pytesseract
    # Remove module from sys.modules AND from the package namespace so that
    # both `from app.services import image_extractor` and
    # `from app.services.image_extractor import extract_image` resolve to the
    # same newly-imported module object.
    sys.modules.pop("app.services.image_extractor", None)
    _svc_pkg.__dict__.pop("image_extractor", None)
    # Reset mock call state between tests
    _mock_pytesseract.reset_mock()
    yield
    # Clean up: remove mock pytesseract and the freshly-imported module
    if sys.modules.get("pytesseract") is _mock_pytesseract:
        del sys.modules["pytesseract"]
    sys.modules.pop("app.services.image_extractor", None)
    _svc_pkg.__dict__.pop("image_extractor", None)


def test_extract_image_tesseract() -> None:
    """Tesseract extraction returns ExtractedContent."""
    from app.services.image_extractor import extract_image

    _mock_pytesseract.image_to_data.return_value = {
        "text": ["Hello", "World", "", "Second", "Line"],
        "top": [10, 10, 10, 30, 30],
        "left": [10, 60, 110, 10, 60],
    }

    image = np.zeros((100, 200), dtype=np.uint8)
    result = extract_image(image, engine="tesseract")

    assert isinstance(result, ExtractedContent)
    assert "Hello" in result.text
    assert "World" in result.text
    assert result.metadata["engine"] == "tesseract"


def test_extract_image_reading_order() -> None:
    """Words are sorted top-to-bottom, left-to-right."""
    from app.services.image_extractor import extract_image

    _mock_pytesseract.image_to_data.return_value = {
        "text": ["bottom", "top-right", "top-left"],
        "top": [50, 10, 10],
        "left": [10, 60, 10],
    }

    image = np.zeros((100, 200), dtype=np.uint8)
    result = extract_image(image, engine="tesseract")

    lines = result.text.strip().split("\n")
    assert "top-left" in lines[0]
    assert "top-right" in lines[0]
    assert "bottom" in lines[1]


def test_paddle_fallback_to_tesseract() -> None:
    """Falls back to tesseract when paddle is not installed."""
    from app.services import image_extractor
    from app.services.image_extractor import extract_image

    _mock_pytesseract.image_to_data.return_value = {
        "text": ["Fallback", "text"],
        "top": [10, 10],
        "left": [10, 60],
    }

    # Simulate paddle not available
    original_paddle = image_extractor.HAS_PADDLE
    image_extractor.HAS_PADDLE = False
    try:
        image = np.zeros((100, 200), dtype=np.uint8)
        result = extract_image(image, engine="paddle")

        assert "Fallback" in result.text
        assert result.metadata["engine"] == "tesseract"
    finally:
        image_extractor.HAS_PADDLE = original_paddle


def test_no_engine_raises() -> None:
    """Raises RuntimeError when no OCR engine is available."""
    from app.services import image_extractor

    original_tess = image_extractor.HAS_TESSERACT
    original_paddle = image_extractor.HAS_PADDLE
    image_extractor.HAS_TESSERACT = False
    image_extractor.HAS_PADDLE = False
    try:
        image = np.zeros((100, 200), dtype=np.uint8)
        with pytest.raises(RuntimeError, match="No OCR engine"):
            image_extractor.extract_image(image, engine="tesseract")
    finally:
        image_extractor.HAS_TESSERACT = original_tess
        image_extractor.HAS_PADDLE = original_paddle


def test_empty_image_returns_empty_text() -> None:
    """Empty image with no detected text returns empty string."""
    from app.services.image_extractor import extract_image

    _mock_pytesseract.image_to_data.return_value = {
        "text": ["", "", ""],
        "top": [0, 0, 0],
        "left": [0, 0, 0],
    }

    image = np.zeros((100, 200), dtype=np.uint8)
    result = extract_image(image, engine="tesseract")

    assert result.text == ""


def test_tesseract_not_found_returns_empty() -> None:
    """Gracefully returns empty text when Tesseract binary is missing at runtime.

    TesseractNotFoundError inherits from EnvironmentError (alias for OSError),
    so we simulate it with an EnvironmentError.
    """
    from app.services.image_extractor import extract_image

    _mock_pytesseract.image_to_data.side_effect = EnvironmentError("tesseract not found")

    image = np.zeros((100, 200), dtype=np.uint8)
    result = extract_image(image, engine="tesseract")

    assert result.text == ""
    assert result.metadata["engine"] == "tesseract"


def test_tesseract_oserror_returns_empty() -> None:
    """Gracefully returns empty text on OSError (e.g., broken tesseract install)."""
    from app.services.image_extractor import extract_image

    _mock_pytesseract.image_to_data.side_effect = OSError("tesseract crashed")

    image = np.zeros((100, 200), dtype=np.uint8)
    result = extract_image(image, engine="tesseract")

    assert result.text == ""
    assert result.metadata["engine"] == "tesseract"


def test_tesseract_file_not_found_returns_empty() -> None:
    """Gracefully returns empty text on FileNotFoundError."""
    from app.services.image_extractor import extract_image

    _mock_pytesseract.image_to_data.side_effect = FileNotFoundError("tesseract binary missing")

    image = np.zeros((100, 200), dtype=np.uint8)
    result = extract_image(image, engine="tesseract")

    assert result.text == ""
    assert result.metadata["engine"] == "tesseract"
