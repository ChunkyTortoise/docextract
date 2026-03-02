from __future__ import annotations

import time

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_redis
from app.models.api_key import APIKey
from app.utils.hashing import hash_api_key

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_api_key(
    api_key: str | None = Security(api_key_header),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> APIKey:
    if not api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required")

    key_hash = hash_api_key(api_key)
    result = await db.execute(
        select(APIKey).where(APIKey.key_hash == key_hash, APIKey.is_active == True)  # noqa: E712
    )
    db_key = result.scalar_one_or_none()

    if not db_key:
        raise HTTPException(status_code=403, detail="Invalid API key")

    # Redis sliding-window rate limit
    now = time.time()
    window_start = now - 60
    window_key = f"ratelimit:{db_key.id}"

    pipe = redis.pipeline()
    pipe.zremrangebyscore(window_key, 0, window_start)
    pipe.zadd(window_key, {str(now): now})
    pipe.zcard(window_key)
    pipe.expire(window_key, 60)
    results = await pipe.execute()

    request_count = results[2]
    if request_count > db_key.rate_limit_per_minute:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={
                "X-RateLimit-Limit": str(db_key.rate_limit_per_minute),
                "X-RateLimit-Remaining": "0",
                "Retry-After": "60",
            },
        )

    return db_key
