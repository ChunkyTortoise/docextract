from __future__ import annotations

from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


_redis_pool: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_pool


_storage = None


async def get_storage():
    global _storage
    if _storage is None:
        from app.storage.base import StorageBackend

        if settings.storage_backend == "r2":
            from app.storage.r2 import R2StorageBackend

            _storage = R2StorageBackend()
        else:
            from app.storage.local import LocalStorageBackend

            _storage = LocalStorageBackend()
    return _storage
