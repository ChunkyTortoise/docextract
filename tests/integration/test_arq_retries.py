"""Opt-in real ARQ/Redis retry contract with controlled SQL/provider boundaries.

Run separately with --noconftest and DOCEXTRACT_TEST_REDIS_SOCKET pointing to a
host-owned disposable Redis Unix socket. Startup, shutdown and cron are omitted;
this proves queue scheduling and the extraction wrapper, not the SQL pipeline.
No shared Redis flush, database, provider request, or service lifecycle is used.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

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
@pytest.mark.parametrize("scenario", ["transient_once", "transient_exhausted", "permanent", "over_cap"])
async def test_extraction_queue_retry_contract(monkeypatch, scenario):
    socket = os.environ.get("DOCEXTRACT_TEST_REDIS_SOCKET")
    if not socket:
        pytest.skip("requires host-owned DOCEXTRACT_TEST_REDIS_SOCKET")
    assert Path(socket).is_socket(), "host must supply a running disposable Redis socket"

    from worker import tasks
    from worker.main import WorkerSettings

    assert Path(tasks.__file__).resolve() == ROOT / "worker/tasks.py"
    attempts = []
    failures = []
    observations = []

    @asynccontextmanager
    async def session():
        yield object()

    async def process(db, redis, job_id):
        # Capture whether a previous attempt incorrectly made the job terminal.
        observations.append(list(failures))
        attempts.append(job_id)
        if scenario == "permanent":
            raise ValueError("invalid document")
        if scenario == "transient_exhausted" or len(attempts) == 1:
            raise ConnectionError("temporary provider outage")
        return {"status": "completed", "record_id": "test-record"}

    async def fail(db, redis, job_id, error):
        failures.append((job_id, error))

    monkeypatch.setattr(tasks, "AsyncSessionLocal", session)
    monkeypatch.setattr(tasks, "_process", process)
    monkeypatch.setattr(tasks, "_fail_job", fail)
    monkeypatch.setattr(tasks, "_start_task_span", lambda job_id: None)
    token = uuid.uuid4().hex
    queue = f"docextract-test-retry:{token}"
    job_id = f"docextract-test-retry-{token}"
    pool = await create_pool(RedisSettings(unix_socket_path=socket), default_queue_name=queue)
    worker = Worker(
        functions=WorkerSettings.functions, redis_pool=pool, queue_name=queue,
        burst=True, max_jobs=1, poll_delay=0.01, handle_signals=False,
        keep_result=60,
    )
    try:
        job = await pool.enqueue_job(
            "process_document", job_id, _job_id=job_id,
            _job_try=4 if scenario == "over_cap" else None,
        )
        assert job is not None
        await asyncio.wait_for(worker.async_run(), timeout=20)
        info = await job.result_info()
        assert info is not None
        if scenario == "transient_once":
            assert attempts == [job_id, job_id]
            assert observations == [[], []]
            assert failures == []
            assert info.success is True
            assert info.result == {"status": "completed", "record_id": "test-record"}
            assert (worker.jobs_complete, worker.jobs_failed, worker.jobs_retried) == (1, 0, 1)
        elif scenario == "transient_exhausted":
            assert attempts == [job_id, job_id, job_id]
            assert observations == [[], [], []]
            assert failures == [(job_id, "temporary provider outage")]
            assert info.success is False
            assert isinstance(info.result, ConnectionError)
            assert (worker.jobs_complete, worker.jobs_failed, worker.jobs_retried) == (0, 1, 2)
        elif scenario == "permanent":
            assert attempts == [job_id]
            assert failures == [(job_id, "invalid document")]
            # Existing permanent-error result semantics stay unchanged.
            assert info.success is True
            assert info.result == {"status": "failed", "error": "invalid document"}
            assert (worker.jobs_complete, worker.jobs_failed, worker.jobs_retried) == (1, 0, 0)
        else:
            assert attempts == []
            assert failures == []
            assert info.success is False
            assert (worker.jobs_complete, worker.jobs_failed, worker.jobs_retried) == (0, 1, 0)
        assert await pool.zcard(queue) == 0
    finally:
        await worker.close()
        # Delete only this run's UUID-scoped keys, never FLUSHDB or a key scan.
        await pool.delete(
            queue, worker.health_check_key, job_key_prefix + job_id,
            result_key_prefix + job_id, retry_key_prefix + job_id,
            in_progress_key_prefix + job_id,
        )
        await pool.aclose()
