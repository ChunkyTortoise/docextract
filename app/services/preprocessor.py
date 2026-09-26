"""Image preprocessing pipeline using OpenCV.
No app.* imports - standalone module.
"""
import struct

import cv2
import numpy as np


class ParserBudgetError(ValueError):
    """Raised when input exceeds an explicit decoded-resource budget."""


def image_size_from_header(data: bytes) -> tuple[int, int] | None:
    """Read declared (width, height) from PNG/JPEG/GIF/BMP headers without decoding."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
            width, height = struct.unpack(">II", data[16:24])
            return width, height
        if data[:3] == b"\xff\xd8\xff":  # JPEG: walk markers to the SOF frame
            offset = 2
            while offset + 9 < len(data):
                if data[offset] != 0xFF:
                    offset += 1
                    continue
                marker = data[offset + 1]
                if marker in (
                    0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                    0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
                ):
                    height, width = struct.unpack(">HH", data[offset + 5 : offset + 9])
                    return width, height
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    offset += 2
                    continue
                seg_len = struct.unpack(">H", data[offset + 2 : offset + 4])[0]
                offset += 2 + seg_len
        if data[:6] in (b"GIF87a", b"GIF89a"):
            width, height = struct.unpack("<HH", data[6:10])
            return width, height
        if data[:2] == b"BM":
            width, height = struct.unpack("<ii", data[18:26])
            return width, abs(height)
    except (struct.error, IndexError):
        return None
    return None


def preprocess_image(image: np.ndarray) -> np.ndarray:
    """Full preprocessing pipeline: grayscale -> deskew -> adaptive threshold -> CLAHE.

    Args:
        image: BGR or grayscale numpy array from cv2.imread or in-memory decode

    Returns:
        Preprocessed grayscale numpy array
    """
    # Step 1: Convert to grayscale
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    # Step 2: Deskew
    deskewed = _deskew(gray)

    # Step 3: Adaptive threshold (binarization)
    binary = cv2.adaptiveThreshold(  # noqa: F841
        deskewed,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        11,
        2,
    )

    # Step 4: CLAHE (Contrast Limited Adaptive Histogram Equalization)
    # Apply to original gray (not binary) for better OCR
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(deskewed)

    return enhanced


def _deskew(gray: np.ndarray) -> np.ndarray:
    """Compute skew angle and rotate to deskew."""
    if gray.shape[0] < 10 or gray.shape[1] < 10:
        return gray

    # Invert for better line detection (text = white on black)
    inverted = cv2.bitwise_not(gray)

    # Find non-zero pixels
    coords = np.column_stack(np.where(inverted > 0))
    if len(coords) < 10:
        return gray

    angle = cv2.minAreaRect(coords)[-1]

    # Normalize angle
    if angle < -45:
        angle = 90 + angle

    # Only deskew if angle is significant (>0.5 degrees)
    if abs(angle) < 0.5:
        return gray

    h, w = gray.shape
    center = (w // 2, h // 2)
    rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(
        gray,
        rotation_matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return rotated


def preprocess_bytes(image_bytes: bytes, max_pixels: int | None = None) -> np.ndarray:
    """Preprocess image from raw bytes.

    When max_pixels is set, the declared header dimensions are checked before
    decoding so an oversized image fails fast instead of allocating first.
    """
    size = image_size_from_header(image_bytes)
    if max_pixels is not None and size is not None:
        width, height = size
        if width * height > max_pixels:
            raise ParserBudgetError(
                f"Image dimensions {width}x{height} exceed decoded-pixel budget {max_pixels}"
            )
    arr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode image bytes")
    if max_pixels is not None and image.shape[0] * image.shape[1] > max_pixels:
        raise ParserBudgetError(
            f"Decoded image {image.shape[1]}x{image.shape[0]} exceeds pixel budget {max_pixels}"
        )
    return preprocess_image(image)
