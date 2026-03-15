from __future__ import annotations

import time
import uuid

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_db, get_redis
from app.models.api_key import APIKey
from app.utils.hashing import hash_api_key

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
ROLE_RANK = {"viewer": 1, "operator": 2, "admin": 3}

# Sentinel object returned for demo-mode auth bypass
_DEMO_KEY = APIKey(
    id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
    name="demo",
    key_hash="demo",
    is_active=True,
    rate_limit_per_minute=30,
)


async def get_api_key(
    request: Request,
    api_key: str | None = Security(api_key_header),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> APIKey:
    if not api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required")

    # Demo mode bypass
    if settings.demo_mode and api_key == settings.demo_api_key:
        request.state.demo = True
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            raise HTTPException(status_code=403, detail="Demo mode is read-only")
        return _DEMO_KEY

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

    request.state.demo = False
    return db_key


def require_roles(*roles: str):
    """FastAPI dependency factory for role-based authorization."""
    allowed = set(roles)

    async def _require(
        api_key: APIKey = Depends(get_api_key),
    ) -> APIKey:
        current_role = getattr(api_key, "role", "admin") or "admin"
        if current_role not in ROLE_RANK:
            raise HTTPException(status_code=403, detail="Unknown API key role")
        if current_role in allowed:
            return api_key

        current_rank = ROLE_RANK[current_role]
        min_allowed_rank = min(ROLE_RANK[r] for r in allowed if r in ROLE_RANK)
        if current_rank >= min_allowed_rank:
            return api_key
        raise HTTPException(status_code=403, detail="Insufficient role permissions")

    return _require
