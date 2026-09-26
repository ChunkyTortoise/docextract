"""ARQ worker configuration and startup."""
from __future__ import annotations

import asyncio
import logging
import signal
from datetime import UTC, datetime, timedelta

import redis.asyncio as aioredis
from arq.connections import RedisSettings
from arq.cron import cron

from app.config import settings
from worker.judge_tasks import judge_extraction_sample
from worker.tasks import process_document
from worker.webhook_tasks import deliver_webhook

logger = logging.getLogger(__name__)

_shutdown_event = asyncio.Event()


def handle_sigterm(*args: object) -> None:
    logger.info("SIGTERM received — initiating graceful shutdown")
    _shutdown_event.set()


signal.signal(signal.SIGTERM, handle_sigterm)


async def startup(ctx: dict) -> None:
    """Called when worker starts.

    ARQ seeds ctx["redis"] with its enqueue-capable pool before this runs;
    keep that client (a plain redis client has no enqueue_job).
    """
    logger.info("Worker started. Queue: %s", settings.worker_queue)
    await recover_stale_jobs(ctx["redis"])


async def shutdown(ctx: dict) -> None:
    """Called when worker stops."""
    if "redis" in ctx:
        await ctx["redis"].aclose()
    logger.info("Worker shut down cleanly")


# In-flight pipeline states: a worker owns the job right now.
IN_FLIGHT_STATUSES = (
    "preprocessing",
    "extracting_text",
    "classifying",
    "extracting_data",
    "extracting_page",
    "validating",
    "embedding",
)


async def recover_stale_jobs(redis: aioredis.Redis) -> None:
    """Requeue stale in-flight jobs and re-enqueue recoverable queued work.

    Two failure modes are recovered (lane B B5):
    - a job stuck in an in-flight state longer than job_timeout (worker died);
    - a job committed to the DB but never (or no longer) in the queue, e.g.
      when the enqueue at upload time failed after the commit.

    Re-enqueueing is idempotent: ARQ dedupes on _job_id, so a job already
    pending in the queue is not scheduled twice.
    """
    from sqlalchemy import select

    from app.models.database import AsyncSessionLocal
    from app.models.job import ExtractionJob

    stale_cutoff = datetime.now(UTC) - timedelta(seconds=settings.job_timeout_seconds)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ExtractionJob).where(
                ExtractionJob.status.in_(IN_FLIGHT_STATUSES),
                ExtractionJob.started_at < stale_cutoff,
            )
        )
        stale_jobs = list(result.scalars().all())

        for job in stale_jobs:
            job.status = "queued"
            job.started_at = None
            job.error_message = "Requeued: stale processing state on startup"
            logger.warning("Requeued stale job: %s", job.id)

        # Committed but stranded: sitting in "queued" past the timeout with no
        # worker pickup (e.g. a failed enqueue at upload time). Recoverable
        # work, never dropped on the floor.
        stranded_result = await db.execute(
            select(ExtractionJob).where(
                ExtractionJob.status == "queued",
                ExtractionJob.queued_at < stale_cutoff,
            )
        )
        stranded_jobs = list(stranded_result.scalars().all())

        if stale_jobs or stranded_jobs:
            await db.commit()
            logger.info(
                "Recovered %d stale jobs; re-enqueueing %d",
                len(stale_jobs),
                len(stale_jobs) + len(stranded_jobs),
            )

        for job in [*stale_jobs, *stranded_jobs]:
            try:
                await redis.enqueue_job(
                    "process_document",
                    str(job.id),
                    _queue_name=settings.worker_queue,
                    _job_id=str(job.id),
                )
            except Exception as exc:
                logger.warning("Could not re-enqueue job %s: %s", job.id, exc)


async def recover_stale_jobs_cron(ctx: dict) -> None:
    """Cron wrapper: recover stale jobs every 10 minutes."""
    redis: aioredis.Redis = ctx["redis"]
    await recover_stale_jobs(redis)


class WorkerSettings:
    functions = [process_document, judge_extraction_sample, deliver_webhook]
    cron_jobs = [cron(recover_stale_jobs_cron, minute={0, 10, 20, 30, 40, 50})]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = settings.worker_queue
    max_jobs = settings.worker_max_jobs
    job_timeout = settings.job_timeout_seconds
    health_check_interval = 30
