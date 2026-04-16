import numpy as np
import pytest

from app.services.preprocessor import preprocess_bytes, preprocess_image


def make_test_image(h: int = 100, w: int = 200, gray: bool = False) -> np.ndarray:
    """Create a synthetic test image."""
    if gray:
        return np.random.randint(0, 256, (h, w), dtype=np.uint8)
    return np.random.randint(0, 256, (h, w, 3), dtype=np.uint8)


def test_preprocess_bgr_image():
    img = make_test_image()
    result = preprocess_image(img)
    assert result.shape == (100, 200)  # grayscale


def test_preprocess_grayscale_image():
    img = make_test_image(gray=True)
    result = preprocess_image(img)
    assert len(result.shape) == 2


def test_preprocess_small_image():
    """Should not crash on small images."""
    img = make_test_image(h=5, w=5)
    result = preprocess_image(img)
    assert result is not None


def test_preprocess_white_image():
    """Pure white image should not crash."""
    img = np.full((100, 200, 3), 255, dtype=np.uint8)
    result = preprocess_image(img)
    assert result is not None


def test_preprocess_bytes():
    """Test preprocessing from encoded bytes."""
    import cv2

    img = make_test_image()
    _, encoded = cv2.imencode(".png", img)
    result = preprocess_bytes(encoded.tobytes())
    assert result is not None


def test_preprocess_bytes_invalid_data():
    """Invalid image bytes raise ValueError."""
    with pytest.raises(ValueError, match="Could not decode"):
        preprocess_bytes(b"not-an-image")


def test_preprocess_bytes_jpeg():
    """JPEG encoded bytes are preprocessed correctly."""
    import cv2

    img = make_test_image(h=50, w=80)
    _, encoded = cv2.imencode(".jpg", img)
    result = preprocess_bytes(encoded.tobytes())
    assert len(result.shape) == 2  # grayscale


def test_deskew_preserves_dimensions():
    """Deskew does not change image dimensions."""
    img = make_test_image(h=100, w=200)
    result = preprocess_image(img)
    assert result.shape == (100, 200)
