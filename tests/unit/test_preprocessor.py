import numpy as np
import pytest
from app.services.preprocessor import preprocess_image, preprocess_bytes


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
