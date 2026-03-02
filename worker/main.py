"""ARQ worker configuration and startup."""
from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis

from app.config import settings
from worker.tasks import process_document

logger = logging.getLogger(__name__)

_shutdown_event = asyncio.Event()


def handle_sigterm(*args: object) -> None:
    logger.info("SIGTERM received — initiating graceful shutdown")
    _shutdown_event.set()


signal.signal(signal.SIGTERM, handle_sigterm)


async def startup(ctx: dict) -> None:
    """Called when worker starts."""
    ctx["redis"] = aioredis.from_url(settings.redis_url, decode_responses=True)
    logger.info("Worker started. Queue: %s", settings.worker_queue)
    await recover_stale_jobs(ctx["redis"])


async def shutdown(ctx: dict) -> None:
    """Called when worker stops."""
    if "redis" in ctx:
        await ctx["redis"].aclose()
    logger.info("Worker shut down cleanly")


async def recover_stale_jobs(redis: aioredis.Redis) -> None:
    """Requeue jobs stuck in PROCESSING longer than job_timeout."""
    from sqlalchemy import select

    from app.models.database import AsyncSessionLocal
    from app.models.job import ExtractionJob

    stale_cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.job_timeout_seconds)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ExtractionJob).where(
                ExtractionJob.status == "processing",
                ExtractionJob.started_at < stale_cutoff,
            )
        )
        stale_jobs = result.scalars().all()

        for job in stale_jobs:
            job.status = "queued"
            job.started_at = None
            job.error_message = "Requeued: stale processing state on startup"
            logger.warning("Requeued stale job: %s", job.id)

        if stale_jobs:
            await db.commit()
            logger.info("Recovered %d stale jobs", len(stale_jobs))


class WorkerSettings:
    functions = [process_document]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = None  # Set at runtime
    queue_name = settings.worker_queue
    max_jobs = settings.worker_max_jobs
    job_timeout = settings.job_timeout_seconds
    health_check_interval = 30
