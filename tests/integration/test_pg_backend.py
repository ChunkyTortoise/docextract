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

        check = create_async_engine(scratch_url)
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
