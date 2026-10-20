"""Real ARQ startup/shutdown acceptance using a host-owned Redis Unix socket.

SQL and extraction/provider boundaries are controlled. Production startup,
shutdown, extraction wrapper, registration and Redis queue are real. Cron is
omitted. Run separately with --noconftest and DOCEXTRACT_TEST_REDIS_SOCKET.
No service lifecycle, SQL connection, provider request or shared Redis flush.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from arq.connections import RedisSettings, create_pool
from arq.constants import (
    in_progress_key_prefix,
    job_key_prefix,
    result_key_prefix,
    retry_key_prefix,
)
from arq.worker import Worker

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
async def test_production_startup_preserves_enqueue_pool_and_processes_job(monkeypatch):
    socket = os.environ.get("DOCEXTRACT_TEST_REDIS_SOCKET")
    if not socket:
        pytest.skip("requires host-owned DOCEXTRACT_TEST_REDIS_SOCKET")
    assert Path(socket).is_socket()

    from app.models import database
    from worker import main, tasks

    assert Path(main.__file__).resolve() == ROOT / "worker/main.py"
    assert Path(tasks.__file__).resolve() == ROOT / "worker/tasks.py"
    db = AsyncMock()
    db.execute.return_value.scalars = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = []

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(database, "AsyncSessionLocal", session)
    monkeypatch.setattr(tasks, "AsyncSessionLocal", session)
    monkeypatch.setattr(tasks, "_start_task_span", lambda job_id: None)
    token = uuid.uuid4().hex
    queue = f"docextract-test-startup:{token}"
    job_id = f"docextract-test-startup-{token}"
    pool = await create_pool(RedisSettings(unix_socket_path=socket), default_queue_name=queue)
    processed = []
    jobs = []
    lifecycle = []

    async def process(db, redis, received_job_id):
        assert redis is pool
        processed.append(received_job_id)
        return {"status": "completed", "record_id": "startup-record"}

    async def startup(ctx):
        await main.WorkerSettings.on_startup(ctx)
        assert ctx["redis"] is pool
        lifecycle.append("startup")
        jobs.append(await ctx["redis"].enqueue_job("process_document", job_id, _job_id=job_id))

    async def shutdown(ctx):
        assert ctx["redis"] is pool
        await main.WorkerSettings.on_shutdown(ctx)
        lifecycle.append("shutdown")

    monkeypatch.setattr(tasks, "_process", process)
    worker = Worker(
        functions=main.WorkerSettings.functions, redis_pool=pool, queue_name=queue,
        on_startup=startup, on_shutdown=shutdown, burst=True, max_jobs=1,
        poll_delay=0.01, handle_signals=False, keep_result=60,
    )
    try:
        await asyncio.wait_for(worker.async_run(), timeout=10)
        assert len(jobs) == 1 and jobs[0] is not None
        info = await jobs[0].result_info()
        assert info is not None and info.success is True
        assert info.result == {"status": "completed", "record_id": "startup-record"}
        assert processed == [job_id]
        assert (worker.jobs_complete, worker.jobs_failed, worker.jobs_retried) == (1, 0, 0)
        assert await pool.zcard(queue) == 0
        db.execute.assert_awaited_once()  # real stale recovery ran against empty controlled SQL result
        db.commit.assert_not_awaited()
    finally:
        try:
            await worker.close()
        finally:
            # Close the injected pool even if a startup/shutdown assertion fails.
            await pool.aclose()
            # Only UUID-scoped keys, using a separate cleanup client after shutdown.
            cleanup = await create_pool(RedisSettings(unix_socket_path=socket))
            try:
                await cleanup.delete(
                    queue, worker.health_check_key, job_key_prefix + job_id,
                    result_key_prefix + job_id, retry_key_prefix + job_id,
                    in_progress_key_prefix + job_id,
                )
            finally:
                await cleanup.aclose()
    assert lifecycle == ["startup", "shutdown"]
