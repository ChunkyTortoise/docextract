from __future__ import annotations

import hashlib
import hmac

from app.config import settings


def hash_file(data: bytes) -> str:
    """Compute SHA-256 hash of file bytes."""
    return hashlib.sha256(data).hexdigest()


def hash_api_key(raw_key: str) -> str:
    """HMAC-SHA256 hash of API key using server secret."""
    return hmac.new(
        settings.api_key_secret.encode("utf-8"),
        raw_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_api_key(raw_key: str, stored_hash: str) -> bool:
    """Constant-time comparison of HMAC hashes."""
    expected = hash_api_key(raw_key)
    return hmac.compare_digest(expected, stored_hash)
