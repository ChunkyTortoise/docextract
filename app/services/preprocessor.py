"""Image preprocessing pipeline using OpenCV.
No app.* imports - standalone module.
"""
import cv2
import numpy as np


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


def preprocess_bytes(image_bytes: bytes) -> np.ndarray:
    """Preprocess image from raw bytes."""
    arr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode image bytes")
    return preprocess_image(image)
