"""Health check endpoints -- no auth required."""
from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.dependencies import get_db, get_redis, get_storage
from app.schemas.responses import HealthResponse
from app.storage.base import StorageBackend

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    storage: StorageBackend = Depends(get_storage),
) -> HealthResponse:
    """Check system health: DB, Redis, and storage connectivity."""
    db_ok = False
    redis_ok = False
    storage_ok = False

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

    try:
        probe_key = f"_health_probe/{uuid.uuid4()}"
        await asyncio.wait_for(storage.upload(probe_key, b"\x00"), timeout=5.0)
        await asyncio.wait_for(storage.delete(probe_key), timeout=5.0)
        storage_ok = True
    except Exception:
        pass

    # DB + Redis are the critical path; storage degradation doesn't block traffic
    all_ok = db_ok and redis_ok
    status = "healthy" if all_ok else "degraded"
    return HealthResponse(status=status, db_ok=db_ok, redis_ok=redis_ok, storage_ok=storage_ok)
