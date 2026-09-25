"""Deferred webhook delivery: retries are scheduled ARQ jobs, never inline sleeps.

Lane A P0 acceptance lives here: process_document schedules delivery instead of
awaiting it (see tests/unit/test_worker_tasks.py), and a chain of 4 failed
attempts reaches a DLQ entry while exercising real scheduling semantics
(each run performs one attempt; the next run is exactly what the previous one
enqueued with _defer_by) without patching asyncio.sleep to hide anything.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.services.webhook_sender import DLQ_KEY, MAX_ATTEMPTS, RETRY_DELAYS
from worker.webhook_tasks import deliver_webhook

URL = "https://example.com/hook"
PAYLOAD = {"event": "job.completed", "job_id": "j-1"}


class RecordingQueue:
    """Minimal stand-in for the ARQ-capable worker redis client."""

    def __init__(self) -> None:
        self.enqueued: list[tuple] = []
        self.lists: dict[str, list[str]] = {}

    async def enqueue_job(self, func: str, *args, **kwargs):
        self.enqueued.append((func, args, kwargs))
        return MagicMock()

    async def rpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])


def _failing_client() -> AsyncMock:
    client = AsyncMock()
    response = MagicMock()
    response.is_success = False
    response.status_code = 500
    client.post.return_value = response
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def _succeeding_client() -> AsyncMock:
    client = AsyncMock()
    response = MagicMock()
    response.is_success = True
    response.status_code = 200
    client.post.return_value = response
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
async def test_four_failed_attempts_drive_to_dlq_without_sleeping():
    """Lane A P0 acceptance: 4 failed attempts reach a DLQ entry.

    Each deliver_webhook run makes exactly one HTTP attempt, then the drive
    executes whatever was enqueued (the deferred job the ARQ scheduler would
    fire). asyncio.sleep is never patched for scheduling; a guard patch fails
    the test if anything tries to sleep inline.
    """
    queue = RecordingQueue()
    ctx = {"redis": queue}
    client = _failing_client()
    defer_schedule: list[int] = []

    with (
        patch("app.services.webhook_sender.httpx.AsyncClient", return_value=client),
        patch("asyncio.sleep", new_callable=AsyncMock) as sleep_mock,
    ):
        result = await deliver_webhook(ctx, URL, PAYLOAD, "secret", "wh-1", 1)
        runs = 1
        while result["status"] == "retry_scheduled":
            func, args, kwargs = queue.enqueued.pop(0)
            assert func == "deliver_webhook"
            assert kwargs["_queue_name"] == settings.worker_queue
            defer_schedule.append(kwargs["_defer_by"])
            # Scheduler fires the deferred job: run exactly what was enqueued.
            result = await deliver_webhook(ctx, *args)
            runs += 1

        sleep_mock.assert_not_called()

    assert runs == MAX_ATTEMPTS
    assert client.post.call_count == MAX_ATTEMPTS
    assert defer_schedule == RETRY_DELAYS[1:]  # 30s, 300s, 1800s
    assert result["status"] == "dead_lettered"
    assert result["attempt"] == MAX_ATTEMPTS

    entries = queue.lists[DLQ_KEY]
    assert len(entries) == 1
    entry = json.loads(entries[0])
    assert entry["endpoint"] == URL
    assert entry["payload"] == PAYLOAD
    assert entry["error"] == "HTTP 500"
    assert entry["webhook_id"] == "wh-1"
    assert "timestamp" in entry


@pytest.mark.asyncio
async def test_first_failure_schedules_second_attempt_thirty_seconds_out():
    queue = RecordingQueue()
    ctx = {"redis": queue}
    client = _failing_client()

    with patch("app.services.webhook_sender.httpx.AsyncClient", return_value=client):
        result = await deliver_webhook(ctx, URL, PAYLOAD, "secret", None, 1)

    assert result == {"status": "retry_scheduled", "attempt": 2, "defer_after_s": 30}
    assert len(queue.enqueued) == 1
    func, args, kwargs = queue.enqueued[0]
    assert func == "deliver_webhook"
    assert args == (URL, PAYLOAD, "secret", None, 2)
    assert kwargs == {"_defer_by": 30, "_queue_name": settings.worker_queue}
    # Nothing dead-lettered yet.
    assert queue.lists == {}


@pytest.mark.asyncio
async def test_successful_attempt_schedules_nothing():
    queue = RecordingQueue()
    ctx = {"redis": queue}
    client = _succeeding_client()

    with patch("app.services.webhook_sender.httpx.AsyncClient", return_value=client):
        result = await deliver_webhook(ctx, URL, PAYLOAD, "secret")

    assert result == {"status": "delivered", "attempt": 1}
    assert client.post.call_count == 1
    assert queue.enqueued == []
    assert queue.lists == {}


@pytest.mark.asyncio
async def test_retry_schedule_constant_matches_original_backoff():
    """The deferred schedule preserves the original 0/30/300/1800s policy."""
    assert RETRY_DELAYS == [0, 30, 300, 1800]
    assert MAX_ATTEMPTS == 4
