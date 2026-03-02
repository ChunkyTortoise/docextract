"""Tests for utility modules."""
from __future__ import annotations

import os

# Set required env vars before importing app modules
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("API_KEY_SECRET", "test-secret-key-that-is-32-chars!")

from app.utils.tokens import estimate_tokens


def test_estimate_tokens_empty() -> None:
    assert estimate_tokens("") == 0


def test_estimate_tokens_short() -> None:
    text = "Hello world"
    result = estimate_tokens(text)
    assert result == int(len(text) / 4 * 1.5)


def test_estimate_tokens_long() -> None:
    text = "a" * 1000
    assert estimate_tokens(text) == 375


def test_config_imports() -> None:
    from app.config import Settings
    assert Settings is not None


def test_hashing_imports() -> None:
    from app.utils.hashing import hash_file, hash_api_key, verify_api_key
    assert hash_file is not None
    assert hash_api_key is not None
    assert verify_api_key is not None


def test_hash_file() -> None:
    from app.utils.hashing import hash_file
    result = hash_file(b"test data")
    assert isinstance(result, str)
    assert len(result) == 64  # SHA-256 hex digest


def test_hash_api_key_deterministic() -> None:
    from app.utils.hashing import hash_api_key
    key = "dex_live_test123"
    assert hash_api_key(key) == hash_api_key(key)


def test_verify_api_key() -> None:
    from app.utils.hashing import hash_api_key, verify_api_key
    key = "dex_live_test123"
    hashed = hash_api_key(key)
    assert verify_api_key(key, hashed) is True
    assert verify_api_key("wrong_key", hashed) is False


def test_mime_imports() -> None:
    from app.utils.mime import (
        ALLOWED_MIME_TYPES,
        detect_mime_type,
        get_extension_mime,
        is_allowed_mime_type,
    )
    assert ALLOWED_MIME_TYPES is not None
    assert detect_mime_type is not None
    assert get_extension_mime is not None
    assert is_allowed_mime_type is not None


def test_allowed_mime_types() -> None:
    from app.utils.mime import is_allowed_mime_type
    assert is_allowed_mime_type("application/pdf") is True
    assert is_allowed_mime_type("image/jpeg") is True
    assert is_allowed_mime_type("text/plain") is False


def test_get_extension_mime() -> None:
    from app.utils.mime import get_extension_mime
    assert get_extension_mime("test.pdf") == "application/pdf"
    assert get_extension_mime("photo.jpg") == "image/jpeg"
    assert get_extension_mime("unknown.xyz") is None
