"""Tests for auth middleware — API key validation and rate limiting."""
from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from app.models.api_key import APIKey


@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def valid_api_key():
    key = MagicMock(spec=APIKey)
    key.id = uuid.uuid4()
    key.name = "test"
    key.key_hash = "hashed"
    key.is_active = True
    key.rate_limit_per_minute = 5
    return key


@pytest.fixture
def mock_db(valid_api_key):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = valid_api_key
    db.execute = AsyncMock(return_value=result)
    return db


class TestGetApiKey:
    """Tests for the get_api_key dependency."""

    @pytest.mark.asyncio
    async def test_missing_header_raises_401(self, fake_redis):
        from app.auth.middleware import get_api_key

        mock_db = AsyncMock()
        with pytest.raises(Exception) as exc_info:
            await get_api_key(api_key=None, db=mock_db, redis=fake_redis)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_key_raises_403(self, fake_redis):
        from app.auth.middleware import get_api_key

        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result)

        with pytest.raises(Exception) as exc_info:
            await get_api_key(api_key="bad-key", db=mock_db, redis=fake_redis)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_valid_key_returns_api_key(self, fake_redis, mock_db, valid_api_key):
        from app.auth.middleware import get_api_key

        with patch("app.auth.middleware.hash_api_key", return_value="hashed"):
            result = await get_api_key(api_key="good-key", db=mock_db, redis=fake_redis)

        assert result is valid_api_key

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_raises_429(self, fake_redis, mock_db, valid_api_key):
        from app.auth.middleware import get_api_key

        valid_api_key.rate_limit_per_minute = 3

        with patch("app.auth.middleware.hash_api_key", return_value="hashed"):
            # Make requests up to the limit (3) + 1 to trigger 429
            for _ in range(3):
                await get_api_key(api_key="good-key", db=mock_db, redis=fake_redis)

            with pytest.raises(Exception) as exc_info:
                await get_api_key(api_key="good-key", db=mock_db, redis=fake_redis)

        assert exc_info.value.status_code == 429
        assert "Rate limit" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_rate_limit_headers_on_429(self, fake_redis, mock_db, valid_api_key):
        from app.auth.middleware import get_api_key

        valid_api_key.rate_limit_per_minute = 1

        with patch("app.auth.middleware.hash_api_key", return_value="hashed"):
            await get_api_key(api_key="good-key", db=mock_db, redis=fake_redis)

            with pytest.raises(Exception) as exc_info:
                await get_api_key(api_key="good-key", db=mock_db, redis=fake_redis)

        headers = exc_info.value.headers
        assert "Retry-After" in headers
        assert "X-RateLimit-Limit" in headers
        assert headers["X-RateLimit-Remaining"] == "0"

    @pytest.mark.asyncio
    async def test_rate_limit_window_expires(self, fake_redis, mock_db, valid_api_key):
        from app.auth.middleware import get_api_key

        valid_api_key.rate_limit_per_minute = 2

        with patch("app.auth.middleware.hash_api_key", return_value="hashed"):
            # Use up the limit
            for _ in range(2):
                await get_api_key(api_key="good-key", db=mock_db, redis=fake_redis)

            # Clear the rate limit window (simulating time passage)
            window_key = f"ratelimit:{valid_api_key.id}"
            await fake_redis.delete(window_key)

            # Should succeed again
            result = await get_api_key(api_key="good-key", db=mock_db, redis=fake_redis)
            assert result is valid_api_key


class TestAPIKeyModel:
    """Tests for the APIKey model defaults."""

    def test_rate_limit_default(self):
        """rate_limit_per_minute column has default=60."""
        from sqlalchemy import inspect as sa_inspect

        col = APIKey.__table__.columns["rate_limit_per_minute"]
        assert col.default.arg == 60
