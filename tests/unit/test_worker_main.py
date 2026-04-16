"""Tests for worker/main.py — startup, shutdown, stale job recovery, cron."""
from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# Stub heavy optional dependencies
def _ensure_stub(module_name: str) -> None:
    if module_name not in sys.modules:
        sys.modules[module_name] = MagicMock()


for _mod in [
    "fitz", "pdfplumber", "pytesseract", "paddleocr", "cv2",
    "sentence_transformers", "magic", "anthropic", "pgvector", "pgvector.sqlalchemy",
]:
    _ensure_stub(_mod)


# Stub arq if not installed — create realistic mock classes
if "arq" not in sys.modules:
    arq_mod = MagicMock()

    class _FakeRedisSettings:
        @classmethod
        def from_dsn(cls, url: str) -> _FakeRedisSettings:
            return cls()

    class _FakeCronResult:
        """Mimics arq.cron.CronJob so tests can inspect attributes."""
        def __init__(self, coroutine, *, minute=None, **kwargs):
            self.coroutine = coroutine
            self.minute = minute

    def _fake_cron(func, *, minute=None, **kwargs):
        return _FakeCronResult(func, minute=minute)

    arq_connections = MagicMock()
    arq_connections.RedisSettings = _FakeRedisSettings
    arq_cron = MagicMock()
    arq_cron.cron = _fake_cron

    sys.modules["arq"] = arq_mod
    sys.modules["arq.connections"] = arq_connections
    sys.modules["arq.cron"] = arq_cron

# Force re-import of worker.main in case it was cached with a bad arq import
for _k in list(sys.modules):
    if _k.startswith("worker."):
        del sys.modules[_k]


class TestWorkerSettings:
    """Verify WorkerSettings configuration."""

    def test_cron_jobs_configured(self):
        from worker.main import WorkerSettings
        assert hasattr(WorkerSettings, "cron_jobs")
        assert len(WorkerSettings.cron_jobs) >= 1

    def test_cron_runs_every_10_minutes(self):
        from worker.main import WorkerSettings
        cron_entry = WorkerSettings.cron_jobs[0]
        assert cron_entry.minute == {0, 10, 20, 30, 40, 50}

    def test_cron_function_is_recover_stale(self):
        from worker.main import WorkerSettings, recover_stale_jobs_cron
        cron_entry = WorkerSettings.cron_jobs[0]
        assert cron_entry.coroutine is recover_stale_jobs_cron

    def test_functions_include_process_document(self):
        from worker.main import WorkerSettings
        from worker.tasks import process_document
        assert process_document in WorkerSettings.functions


class TestRecoverStaleJobsCron:
    """Tests for the cron wrapper."""

    @pytest.mark.asyncio
    async def test_cron_calls_recover_stale_jobs(self):
        from worker.main import recover_stale_jobs_cron

        mock_redis = AsyncMock()
        ctx = {"redis": mock_redis}

        with patch("worker.main.recover_stale_jobs", new_callable=AsyncMock) as mock_recover:
            await recover_stale_jobs_cron(ctx)
            mock_recover.assert_called_once_with(mock_redis)


class TestRecoverStaleJobs:
    """Tests for the stale job recovery logic."""

    @pytest.mark.asyncio
    async def test_requeues_stale_processing_jobs(self):
        from worker.main import recover_stale_jobs

        stale_job = MagicMock()
        stale_job.id = uuid.uuid4()
        stale_job.status = "processing"
        stale_job.started_at = datetime.now(UTC) - timedelta(seconds=600)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [stale_job]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        mock_session_cls = MagicMock()
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_redis = AsyncMock()

        with patch("app.models.database.AsyncSessionLocal", mock_session_cls):
            await recover_stale_jobs(mock_redis)

        assert stale_job.status == "queued"
        assert stale_job.started_at is None
        assert "Requeued" in stale_job.error_message
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_stale_jobs_skips_commit(self):
        from worker.main import recover_stale_jobs

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_session_cls = MagicMock()
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_redis = AsyncMock()

        with patch("app.models.database.AsyncSessionLocal", mock_session_cls):
            await recover_stale_jobs(mock_redis)

        mock_db.commit.assert_not_called()


class TestStartupShutdown:
    @pytest.mark.asyncio
    async def test_startup_initializes_redis_and_recovers(self):
        from worker.main import startup

        ctx: dict = {}

        with patch("worker.main.recover_stale_jobs", new_callable=AsyncMock) as mock_recover:
            with patch("worker.main.aioredis") as mock_aioredis:
                mock_redis_instance = AsyncMock()
                mock_aioredis.from_url.return_value = mock_redis_instance
                await startup(ctx)

        assert "redis" in ctx
        mock_recover.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_closes_redis(self):
        from worker.main import shutdown

        mock_redis = AsyncMock()
        ctx = {"redis": mock_redis}

        await shutdown(ctx)
        mock_redis.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_without_redis(self):
        from worker.main import shutdown

        ctx: dict = {}
        await shutdown(ctx)  # Should not raise
