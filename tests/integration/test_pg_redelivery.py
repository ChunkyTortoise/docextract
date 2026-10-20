"""Real PostgreSQL lock acceptance, adapted from PR57.

Opt in with DOCEXTRACT_TEST_DATABASE_URL pointing to a dedicated local
postgresql+asyncpg database named docextract_test_*. Its schema must already
match the current application models. This test never creates schemas or runs
migrations; it inserts and removes only its UUID-tagged rows. Redis and storage
remain controlled boundaries, so this is not an ARQ retry test.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

DATABASE_URL = os.environ.get("DOCEXTRACT_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="requires a dedicated DOCEXTRACT_TEST_DATABASE_URL",
)


async def test_concurrent_redelivery_waits_for_committed_terminal_state():
    """A second worker cannot reprocess a job while its first worker commits."""
    from app.models.document import Document
    from app.models.job import ExtractionJob
    from app.models.record import ExtractedRecord
    from worker.tasks import _process

    url = make_url(DATABASE_URL)
    assert url.drivername == "postgresql+asyncpg"
    assert url.host in {"localhost", "127.0.0.1", "::1"}
    assert url.database and url.database.startswith("docextract_test_")
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    first = AsyncSession(engine, expire_on_commit=False)
    second = AsyncSession(engine, expire_on_commit=False)
    doc_id, job_id, record_id = (uuid.uuid4() for _ in range(3))
    task = None
    try:
        first.add(Document(
            id=doc_id, original_filename="race.txt", stored_path="race.txt",
            file_size_bytes=4, mime_type="text/plain", sha256_hash=doc_id.hex * 2,
        ))
        await first.flush()
        first.add(ExtractionJob(id=job_id, document_id=doc_id, status="queued"))
        await first.commit()
        job = (await first.execute(
            select(ExtractionJob).where(ExtractionJob.id == job_id).with_for_update()
        )).scalar_one()
        first_pid = (await first.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        second_pid = (await second.execute(text("SELECT pg_backend_pid()"))).scalar_one()

        with patch("app.dependencies.get_storage", new_callable=AsyncMock) as storage:
            storage.side_effect = AssertionError("redelivery must not start extraction")
            task = asyncio.create_task(_process(second, AsyncMock(), str(job_id)))
            async with engine.connect() as observer:
                for _ in range(300):
                    if task.done():
                        await task  # surface a premature pipeline entry
                        pytest.fail("redelivery did not wait for the in-flight transaction")
                    # Read live lock-manager state, not a transaction-cached stats view.
                    blockers = (await observer.execute(text(
                        "SELECT pg_blocking_pids(:pid)"
                    ), {"pid": second_pid})).scalar_one()
                    if first_pid in blockers:
                        break
                    await asyncio.sleep(0.01)
                else:
                    pytest.fail("second worker never waited on the job lock")

            job.status = "completed"
            first.add(ExtractedRecord(
                id=record_id, job_id=job_id, document_id=doc_id,
                document_type="invoice", extracted_data={}, confidence_score=0.9,
                validation_status="passed",
            ))
            await first.commit()
            result = await asyncio.wait_for(task, timeout=5)
            assert result["status"] == "duplicate_ignored"
            assert result["record_id"] == str(record_id)
            storage.assert_not_awaited()
            assert (await second.execute(
                select(ExtractionJob.status).where(ExtractionJob.id == job_id)
            )).scalar_one() == "completed"
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await second.close()
        await first.close()
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM extracted_records WHERE job_id = :id"), {"id": job_id})
            await conn.execute(text("DELETE FROM extraction_jobs WHERE id = :id"), {"id": job_id})
            await conn.execute(text("DELETE FROM documents WHERE id = :id"), {"id": doc_id})
        await engine.dispose()
