"""Tests for app.dependencies module."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGetDb:
    @pytest.mark.asyncio
    async def test_get_db_yields_session(self):
        """get_db yields a session and closes it after."""
        mock_session = AsyncMock()
        mock_session.close = AsyncMock()

        mock_session_local = MagicMock()
        mock_session_local.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_local.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.dependencies.AsyncSessionLocal", mock_session_local):
            from app.dependencies import get_db

            gen = get_db()
            session = await gen.__anext__()
            assert session is mock_session

            # Exhaust the generator
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()


class TestGetRedis:
    @pytest.mark.asyncio
    async def test_get_redis_creates_pool_once(self):
        """get_redis creates a Redis pool on first call and reuses it."""
        import app.dependencies as deps

        original_pool = deps._redis_pool
        try:
            deps._redis_pool = None

            mock_redis = MagicMock()
            with patch("app.dependencies.aioredis.from_url", return_value=mock_redis):
                result1 = await deps.get_redis()
                result2 = await deps.get_redis()

            assert result1 is mock_redis
            assert result2 is mock_redis
        finally:
            deps._redis_pool = original_pool

    @pytest.mark.asyncio
    async def test_get_redis_returns_existing_pool(self):
        """get_redis returns existing pool without creating a new one."""
        import app.dependencies as deps

        original_pool = deps._redis_pool
        try:
            sentinel = MagicMock()
            deps._redis_pool = sentinel

            result = await deps.get_redis()
            assert result is sentinel
        finally:
            deps._redis_pool = original_pool


class TestGetStorage:
    @pytest.mark.asyncio
    async def test_get_storage_local_backend(self):
        """get_storage returns LocalStorageBackend when storage_backend is 'local'."""
        import app.dependencies as deps

        original_storage = deps._storage
        try:
            deps._storage = None

            with patch("app.dependencies.settings") as mock_settings:
                mock_settings.storage_backend = "local"
                result = await deps.get_storage()

            from app.storage.local import LocalStorageBackend
            assert isinstance(result, LocalStorageBackend)
        finally:
            deps._storage = original_storage

    @pytest.mark.asyncio
    async def test_get_storage_r2_backend(self):
        """get_storage returns R2StorageBackend when storage_backend is 'r2'."""
        import app.dependencies as deps

        original_storage = deps._storage
        try:
            deps._storage = None

            with (
                patch("app.dependencies.settings") as mock_settings,
                patch("app.storage.r2.boto3"),
                patch("app.storage.r2.settings") as mock_r2_settings,
            ):
                mock_settings.storage_backend = "r2"
                mock_r2_settings.r2_account_id = "test"
                mock_r2_settings.r2_access_key_id = "key"
                mock_r2_settings.r2_secret_access_key = "secret"
                mock_r2_settings.r2_bucket_name = "bucket"
                result = await deps.get_storage()

            from app.storage.r2 import R2StorageBackend
            assert isinstance(result, R2StorageBackend)
        finally:
            deps._storage = original_storage

    @pytest.mark.asyncio
    async def test_get_storage_caches_instance(self):
        """get_storage returns the same instance on subsequent calls."""
        import app.dependencies as deps

        original_storage = deps._storage
        try:
            deps._storage = None

            with patch("app.dependencies.settings") as mock_settings:
                mock_settings.storage_backend = "local"
                result1 = await deps.get_storage()
                result2 = await deps.get_storage()

            assert result1 is result2
        finally:
            deps._storage = original_storage
