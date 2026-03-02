"""Health check endpoints -- no auth required."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.dependencies import get_db, get_redis
from app.schemas.responses import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> HealthResponse:
    """Check system health: DB and Redis connectivity."""
    db_ok = False
    redis_ok = False

    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    try:
        await redis.ping()
        redis_ok = True
    except Exception:
        pass

    status = "healthy" if (db_ok and redis_ok) else "degraded"
    return HealthResponse(status=status, db_ok=db_ok, redis_ok=redis_ok)
