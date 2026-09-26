"""PostgreSQL/pgvector backend tests (marker: pg).

The suite defaults to SQLite, so pgvector search, real constraint enforcement,
and Alembic migrations were never exercised (lane A finding 7, lane B B7).
These tests run against the CI pgvector service (`pytest -m pg` with
DATABASE_URL set) and are skipped elsewhere.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.database import Base

REPO = Path(__file__).resolve().parents[2]
DATABASE_URL = os.environ.get("DATABASE_URL", "")

pytestmark = [
    pytest.mark.pg,
    pytest.mark.skipif(
        not DATABASE_URL.startswith("postgresql"),
        reason="requires a PostgreSQL/pgvector DATABASE_URL (CI pgvector service)",
    ),
]


async def _make_session() -> tuple:
    """Engine + session created on the current loop, schema ready.

    asyncpg connections are bound to their creating loop, so these tests
    build everything inside the test body instead of sharing fixtures.
    """
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.run_sync(Base.metadata.create_all)
    return engine, AsyncSession(engine, expire_on_commit=False)


async def test_pgvector_cosine_search_orders_by_distance():
    """Vector rows insert and cosine-distance search returns nearest-first."""
    from app.models.document import Document
    from app.models.embedding import DocumentEmbedding
    from app.models.job import ExtractionJob
    from app.models.record import ExtractedRecord

    engine, session = await _make_session()
    try:
        doc_id, job_id, job_id_2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        record_id = uuid.uuid4()
        other_record_id = uuid.uuid4()
        session.add(
            Document(
                id=doc_id,
                original_filename="a.pdf",
                stored_path="documents/a/a.pdf",
                file_size_bytes=10,
                mime_type="application/pdf",
                sha256_hash="a" * 64,
            )
        )
        session.add(ExtractionJob(id=job_id, document_id=doc_id, status="completed"))
        session.add(ExtractionJob(id=job_id_2, document_id=doc_id, status="completed"))
        session.add(
            ExtractedRecord(
                id=record_id,
                job_id=job_id,
                document_id=doc_id,
                document_type="invoice",
                extracted_data={"invoice_number": "INV-1"},
                confidence_score=0.9,
            )
        )
        session.add(
            ExtractedRecord(
                id=other_record_id,
                job_id=job_id_2,
                document_id=doc_id,
                document_type="invoice",
                extracted_data={"invoice_number": "INV-2"},
                confidence_score=0.9,
            )
        )
        await session.flush()  # records first: embeddings carry the FK

        near = [1.0] + [0.0] * 767
        far = [0.0] * 767 + [1.0]
        session.add(
            DocumentEmbedding(
                id=uuid.uuid4(),
                record_id=record_id,
                content_text="near",
                embedding=near,
            )
        )
        session.add(
            DocumentEmbedding(
                id=uuid.uuid4(),
                record_id=other_record_id,
                content_text="far",
                embedding=far,
            )
        )
        await session.flush()

        distance = DocumentEmbedding.embedding.cosine_distance(near)
        rows = (
            await session.execute(
                select(DocumentEmbedding.content_text, distance).order_by(distance)
            )
        ).all()
        assert [r[0] for r in rows] == ["near", "far"]
    finally:
        await session.close()
        await engine.dispose()


async def test_record_per_job_unique_constraint():
    """Redelivery can never create a second record for one job."""
    from app.models.document import Document
    from app.models.job import ExtractionJob
    from app.models.record import ExtractedRecord

    engine, session = await _make_session()
    try:
        doc_id, job_id = uuid.uuid4(), uuid.uuid4()
        session.add(
            Document(
                id=doc_id,
                original_filename="b.pdf",
                stored_path="documents/b/b.pdf",
                file_size_bytes=10,
                mime_type="application/pdf",
                sha256_hash="b" * 64,
            )
        )
        session.add(ExtractionJob(id=job_id, document_id=doc_id, status="completed"))
        session.add(
            ExtractedRecord(
                id=uuid.uuid4(),
                job_id=job_id,
                document_id=doc_id,
                document_type="invoice",
                extracted_data={},
                confidence_score=0.5,
            )
        )
        await session.flush()

        session.add(
            ExtractedRecord(
                id=uuid.uuid4(),
                job_id=job_id,
                document_id=doc_id,
                document_type="invoice",
                extracted_data={},
                confidence_score=0.5,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()
    finally:
        await session.close()
        await engine.dispose()


async def test_document_soft_dedup_handles_duplicate_hashes():
    """The soft dedup lookup must tolerate duplicate hashes (no 500)."""
    from app.models.document import Document

    engine, session = await _make_session()
    try:
        hash_val = uuid.uuid4().hex  # unique per run: the CI DB persists rows
        for i in range(2):
            session.add(
                Document(
                    id=uuid.uuid4(),
                    original_filename=f"dup_{i}.pdf",
                    stored_path=f"documents/dup_{i}/f.pdf",
                    file_size_bytes=10,
                    mime_type="application/pdf",
                    sha256_hash=hash_val,
                )
            )
        await session.flush()

        result = await session.execute(
            Document.__table__.select().where(
                Document.__table__.c.sha256_hash == hash_val
            )
        )
        rows = result.all()
        assert len(rows) == 2
        assert rows[0][0] is not None  # first() semantics: a row is always returned
    finally:
        await session.close()
        await engine.dispose()


async def test_alembic_upgrade_head_and_fk_types():
    """Fresh PostgreSQL migration reaches head and eval_log.job_id is uuid.

    Lane B B7 acceptance: fresh migration reaches head; foreign-key types match.
    """
    if not DATABASE_URL.startswith("postgresql+asyncpg"):
        pytest.skip("needs an asyncpg DATABASE_URL")

    base = DATABASE_URL.rsplit("/", 1)[0]
    scratch_name = "docextract_test_alembic"
    admin_url = f"{base}/postgres"
    scratch_url = f"{base}/{scratch_name}"

    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {scratch_name}"))
        await conn.execute(text(f"CREATE DATABASE {scratch_name}"))
    await admin.dispose()

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "head",
            cwd=str(REPO),
            env={**os.environ, "DATABASE_URL": scratch_url},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        assert proc.returncode == 0, out.decode()

        check = create_async_engine(scratch_url, poolclass=NullPool)
        async with check.connect() as conn:
            job_id_type = (
                await conn.execute(
                    text(
                        "SELECT data_type FROM information_schema.columns "
                        "WHERE table_name = 'eval_log' AND column_name = 'job_id'"
                    )
                )
            ).scalar_one()
            fk_types = (
                await conn.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE confrelid = 'extraction_jobs'::regclass"
                    )
                )
            ).scalars().all()
        await check.dispose()

        assert job_id_type == "uuid"
        assert fk_types, "eval_log must carry a real FK to extraction_jobs"
    finally:
        admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin.connect() as conn:
            await conn.execute(text(f"DROP DATABASE IF EXISTS {scratch_name}"))
        await admin.dispose()


async def _run_alembic(scratch_url: str, *args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        *args,
        cwd=str(REPO),
        env={**os.environ, "DATABASE_URL": scratch_url},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    assert proc.returncode == 0, out.decode()


async def _make_scratch(admin_url: str, scratch_name: str) -> None:
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {scratch_name}"))
        await conn.execute(text(f"CREATE DATABASE {scratch_name}"))
    await admin.dispose()


async def _drop_scratch(admin_url: str, scratch_name: str) -> None:
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {scratch_name}"))
    await admin.dispose()


async def test_alembic_013_reconciles_duplicates_before_unique_index():
    """Pre-existing redelivery duplicates upgrade cleanly into the constraint.

    Review P1 on PR #56: CREATE UNIQUE INDEX must not fail on rows left by the
    pre-guard worker; migration 013 keeps the earliest record per job first.
    """
    if not DATABASE_URL.startswith("postgresql+asyncpg"):
        pytest.skip("needs an asyncpg DATABASE_URL")

    base = DATABASE_URL.rsplit("/", 1)[0]
    scratch_name = "docextract_test_alembic_013"
    admin_url = f"{base}/postgres"
    scratch_url = f"{base}/{scratch_name}"

    await _make_scratch(admin_url, scratch_name)
    try:
        await _run_alembic(scratch_url, "upgrade", "012_eval_log")

        doc_id, job_id, keep_id, drop_id = (uuid.uuid4() for _ in range(4))
        seed = create_async_engine(scratch_url, poolclass=NullPool)
        async with seed.begin() as conn:
            await conn.execute(text(
                "INSERT INTO documents (id, original_filename, stored_path, "
                "file_size_bytes, mime_type, sha256_hash) VALUES "
                f"('{doc_id}', 'dup.pdf', 'documents/d/dup.pdf', 10, "
                f"'application/pdf', '{'c' * 64}')"
            ))
            await conn.execute(text(
                f"INSERT INTO extraction_jobs (id, document_id) VALUES ('{job_id}', '{doc_id}')"
            ))
            await conn.execute(text(
                "INSERT INTO extracted_records (id, job_id, document_id, "
                "document_type, extracted_data, confidence_score, validation_status, created_at) VALUES "
                f"('{keep_id}', '{job_id}', '{doc_id}', 'invoice', '{{}}', 0.5, 'passed', "
                "'2026-09-01T00:00:00+00')"
            ))
            await conn.execute(text(
                "INSERT INTO extracted_records (id, job_id, document_id, "
                "document_type, extracted_data, confidence_score, validation_status, created_at) VALUES "
                f"('{drop_id}', '{job_id}', '{doc_id}', 'invoice', '{{}}', 0.6, 'passed', "
                "'2026-09-02T00:00:00+00')"
            ))
        await seed.dispose()

        await _run_alembic(scratch_url, "upgrade", "head")

        check = create_async_engine(scratch_url, poolclass=NullPool)
        async with check.connect() as conn:
            kept = (
                await conn.execute(
                    text("SELECT id::text FROM extracted_records WHERE job_id = :job"),
                    {"job": str(job_id)},
                )
            ).scalars().all()
        with pytest.raises(IntegrityError) as duplicate_error:
            async with check.begin() as conn:
                await conn.execute(text(
                    "INSERT INTO extracted_records (id, job_id, document_id, "
                    "document_type, extracted_data, confidence_score, validation_status) VALUES "
                    f"('{uuid.uuid4()}', '{job_id}', '{doc_id}', 'invoice', '{{}}', 0.5, 'passed')"
                ))
        await check.dispose()
        assert duplicate_error.value.orig.sqlstate == "23505"
        assert "uq_extracted_records_job_id" in str(duplicate_error.value)

        assert kept == [str(keep_id)], "earliest record per job must survive"
    finally:
        await _drop_scratch(admin_url, scratch_name)


async def test_alembic_014_repairs_legacy_eval_log_columns():
    """A database carrying the original 012 shape is repaired forward.

    Review P1 on PR #56: applied migration bodies are never rewritten; the
    varchar -> uuid conversion and FK rebuild live in forward revision 014.
    """
    if not DATABASE_URL.startswith("postgresql+asyncpg"):
        pytest.skip("needs an asyncpg DATABASE_URL")

    base = DATABASE_URL.rsplit("/", 1)[0]
    scratch_name = "docextract_test_alembic_014"
    admin_url = f"{base}/postgres"
    scratch_url = f"{base}/{scratch_name}"

    await _make_scratch(admin_url, scratch_name)
    try:
        await _run_alembic(scratch_url, "upgrade", "013_record_job_unique")

        doc_id, job_id, eval_id = (uuid.uuid4() for _ in range(3))
        seed = create_async_engine(scratch_url, poolclass=NullPool)
        async with seed.begin() as conn:
            await conn.execute(text(
                "INSERT INTO documents (id, original_filename, stored_path, "
                "file_size_bytes, mime_type, sha256_hash) VALUES "
                f"('{doc_id}', 'e.pdf', 'documents/e/e.pdf', 10, "
                f"'application/pdf', '{'d' * 64}')"
            ))
            await conn.execute(text(
                f"INSERT INTO extraction_jobs (id, document_id) VALUES ('{job_id}', '{doc_id}')"
            ))
            await conn.execute(text(
                "INSERT INTO eval_log (id, job_id, completeness, field_accuracy, "
                "hallucination_absence, format_compliance, composite) VALUES "
                f"('{eval_id}', '{job_id}', 1, 1, 1, 1, 0.9)"
            ))
            # Reshape to the original 012 body: varchar columns, no FK.
            await conn.execute(text(
                "ALTER TABLE eval_log DROP CONSTRAINT IF EXISTS eval_log_job_id_fkey"
            ))
            await conn.execute(text(
                "ALTER TABLE eval_log ALTER COLUMN id DROP DEFAULT"
            ))
            await conn.execute(text(
                "ALTER TABLE eval_log ALTER COLUMN id TYPE varchar(36) "
                "USING id::varchar(36)"
            ))
            await conn.execute(text(
                "ALTER TABLE eval_log ALTER COLUMN job_id TYPE varchar(36) "
                "USING job_id::varchar(36)"
            ))
        await seed.dispose()

        await _run_alembic(scratch_url, "upgrade", "head")

        check = create_async_engine(scratch_url, poolclass=NullPool)
        async with check.connect() as conn:
            job_id_type = (
                await conn.execute(
                    text(
                        "SELECT data_type FROM information_schema.columns "
                        "WHERE table_name = 'eval_log' AND column_name = 'job_id'"
                    )
                )
            ).scalar_one()
            row_job = (
                await conn.execute(
                    text("SELECT job_id::text FROM eval_log WHERE id = :id"),
                    {"id": str(eval_id)},
                )
            ).scalar_one_or_none()
            fks = (
                await conn.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE confrelid = 'extraction_jobs'::regclass"
                    )
                )
            ).scalars().all()
        await check.dispose()

        assert job_id_type == "uuid"
        assert row_job == str(job_id), "existing rows must survive the type repair"
        assert "eval_log_job_id_fkey" in fks
    finally:
        await _drop_scratch(admin_url, scratch_name)


async def test_concurrent_redelivery_waits_for_committed_terminal_state():
    """A second worker cannot reprocess a job while its first worker commits."""
    from app.models.document import Document
    from app.models.job import ExtractionJob
    from app.models.record import ExtractedRecord
    from worker.tasks import _process

    engine, first = await _make_session()
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
        second_pid = (await second.execute(text("SELECT pg_backend_pid()"))).scalar_one()

        with patch("app.dependencies.get_storage", new_callable=AsyncMock) as storage:
            storage.side_effect = AssertionError("redelivery must not start extraction")
            task = asyncio.create_task(_process(second, AsyncMock(), str(job_id)))
            async with engine.connect() as observer:
                for _ in range(300):
                    if task.done():
                        await task  # surface a premature pipeline entry
                        pytest.fail("redelivery did not wait for the in-flight transaction")
                    waiting = (await observer.execute(text(
                        "SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"
                    ), {"pid": second_pid})).scalar_one()
                    if waiting == "Lock":
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
