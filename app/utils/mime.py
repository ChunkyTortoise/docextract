from __future__ import annotations

from pathlib import Path

import filetype

ALLOWED_MIME_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".eml": "message/rfc822",
    ".msg": "application/vnd.ms-outlook",
}

_ALLOWED_MIME_SET = set(ALLOWED_MIME_TYPES.values())


def detect_mime_type(data: bytes) -> str:
    """Detect MIME type from file bytes using magic byte sniffing."""
    kind = filetype.guess(data)
    if kind:
        return kind.mime
    # Fallback: OLE Compound Document (MSG files)
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "application/vnd.ms-outlook"
    # Fallback: EML (RFC 822 email — plain text with headers)
    if b"Content-Type:" in data[:512] or data[:5] in (b"From ", b"Date:"):
        return "message/rfc822"
    return "application/octet-stream"


def get_extension_mime(filename: str) -> str | None:
    """Get MIME type from file extension."""
    ext = Path(filename).suffix.lower()
    return ALLOWED_MIME_TYPES.get(ext)


def is_allowed_mime_type(mime_type: str) -> bool:
    """Check if a MIME type is in the allowed set."""
    return mime_type in _ALLOWED_MIME_SET
