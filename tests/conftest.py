"""Pytest configuration and shared fixtures."""
from __future__ import annotations

import sqlite3
import uuid

import fakeredis.aioredis
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON, String
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Register UUID adapter so sqlite3 can bind uuid.UUID objects as strings
sqlite3.register_adapter(uuid.UUID, lambda u: str(u))

# Patch PG_UUID.bind_processor to handle string values in SQLite tests.
# Without this, SQLAlchemy calls value.hex on string UUIDs (retrieved from SQLite)
# causing AttributeError when tests share a session across test functions.
from sqlalchemy.dialects.postgresql import UUID as _PG_UUID  # noqa: E402

_orig_uuid_bind_processor = _PG_UUID.bind_processor


def _safe_uuid_bind_processor(self, dialect):  # type: ignore[override]
    orig_proc = _orig_uuid_bind_processor(self, dialect)

    def process(value):
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, uuid.UUID):
            return str(value)
        if orig_proc is not None:
            return orig_proc(value)
        return str(value)

    return process


_PG_UUID.bind_processor = _safe_uuid_bind_processor  # type: ignore[method-assign]

from datetime import UTC

from app.dependencies import get_arq_pool, get_db, get_redis, get_storage
from app.models import APIKey  # noqa: F401
from app.models.database import Base
from app.storage.base import StorageBackend
from app.utils.hashing import hash_api_key

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
TEST_API_KEY = "test-api-key-12345"


def _patch_pg_types_for_sqlite():
    """Replace PostgreSQL-specific column types with SQLite-compatible ones."""
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            # JSONB -> JSON
            if isinstance(col.type, JSONB):
                col.type = JSON()
            # UUID -> String(36)
            if isinstance(col.type, PG_UUID):
                col.type = String(36)
            # Replace PostgreSQL-specific server defaults
            if col.server_default is not None:
                try:
                    default_text = str(col.server_default.arg)
                except Exception:
                    default_text = ""
                if "gen_random_uuid" in default_text:
                    col.server_default = None
                elif "NOW()" in default_text.upper():
                    from sqlalchemy import text as sa_text
                    from sqlalchemy.schema import DefaultClause
                    col.server_default = DefaultClause(sa_text("CURRENT_TIMESTAMP"))

        # Strip PostgreSQL-specific indexes (using GIN, partial WHERE, etc.)
        indexes_to_remove = []
        for idx in list(table.indexes):
            dialect_opts = idx.dialect_options.get("postgresql", {})
            has_using = dialect_opts.get("using") is not None
            has_where = dialect_opts.get("where") is not None
            if has_using or has_where:
                indexes_to_remove.append(idx)
        for idx in indexes_to_remove:
            table.indexes.discard(idx)


class FakeStorageBackend(StorageBackend):
    """In-memory storage for tests."""

    def __init__(self):
        self._store: dict[str, bytes] = {}

    async def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self._store[key] = data
        return key

    async def download(self, key: str) -> bytes:
        return self._store[key]

    async def delete(self, key: str) -> bool:
        return self._store.pop(key, None) is not None

    async def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        return f"http://fake/{key}"

    async def list_keys(self, prefix: str = "") -> list[str]:
        return [k for k in self._store if k.startswith(prefix)]


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Create tables with SQLite-compatible DDL
    async with engine.begin() as conn:
        await conn.run_sync(_create_tables)

    yield engine
    await engine.dispose()


def _create_tables(conn):
    """Create tables, swapping out PostgreSQL types/defaults for SQLite."""
    _patch_pg_types_for_sqlite()

    # Clear mapper caches that reference old column defaults
    from sqlalchemy.orm import class_mapper

    for cls in Base.__subclasses__():
        try:
            mapper = class_mapper(cls)
            if "_insert_cols_as_none" in mapper.__dict__:
                del mapper.__dict__["_insert_cols_as_none"]
            if "_insert_cols_evaluating_none" in mapper.__dict__:
                del mapper.__dict__["_insert_cols_evaluating_none"]
        except Exception:
            pass

    Base.metadata.create_all(conn)


@pytest_asyncio.fixture
async def db_session(test_engine):
    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def test_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest_asyncio.fixture
async def fake_storage():
    return FakeStorageBackend()


@pytest_asyncio.fixture
async def fake_arq_pool():
    from unittest.mock import AsyncMock
    return AsyncMock()


@pytest_asyncio.fixture
async def client(db_session, test_redis, fake_storage, fake_arq_pool):
    from app.main import create_app

    app = create_app()

    async def override_get_db():
        yield db_session

    async def override_get_redis():
        return test_redis

    async def override_get_storage():
        return fake_storage

    async def override_get_arq_pool():
        return fake_arq_pool

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = override_get_redis
    app.dependency_overrides[get_storage] = override_get_storage
    app.dependency_overrides[get_arq_pool] = override_get_arq_pool

    # Ensure test API key exists (idempotent — key_hash is unique)
    from sqlalchemy import select

    key_hash = hash_api_key(TEST_API_KEY)
    existing = await db_session.execute(
        select(APIKey).where(APIKey.key_hash == key_hash)
    )
    if existing.scalar_one_or_none() is None:
        api_key = APIKey(
            id=str(uuid.uuid4()),
            name="test-key",
            role="admin",
            key_hash=key_hash,
            is_active=True,
            rate_limit_per_minute=1000,
        )
        db_session.add(api_key)
        await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": TEST_API_KEY},
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def demo_client(db_session, test_redis, fake_storage, fake_arq_pool):
    from app.config import settings
    from app.main import create_app

    original_demo_mode = settings.demo_mode
    settings.demo_mode = True
    try:
        app = create_app()

        async def override_get_db():
            yield db_session

        async def override_get_redis():
            return test_redis

        async def override_get_storage():
            return fake_storage

        async def override_get_arq_pool():
            return fake_arq_pool

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_redis] = override_get_redis
        app.dependency_overrides[get_storage] = override_get_storage
        app.dependency_overrides[get_arq_pool] = override_get_arq_pool

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": settings.demo_api_key},
        ) as ac:
            yield ac
    finally:
        settings.demo_mode = original_demo_mode


@pytest_asyncio.fixture
async def seed_stale_review_items(db_session):
    """Factory: creates n_stale (>24h old) + n_fresh records with needs_review=True."""
    import uuid
    from datetime import datetime, timedelta

    from app.models.document import Document
    from app.models.job import ExtractionJob
    from app.models.record import ExtractedRecord

    async def _seed(n_stale: int, n_fresh: int) -> list[str]:
        now = datetime.now(UTC)
        record_ids: list[str] = []

        for i in range(n_stale + n_fresh):
            doc_id = str(uuid.uuid4())
            job_id = str(uuid.uuid4())
            record_id = str(uuid.uuid4())
            is_stale = i < n_stale
            created = now - timedelta(hours=25) if is_stale else now

            db_session.add(Document(
                id=doc_id,
                original_filename=f"stale_{i}.pdf",
                stored_path=f"documents/{doc_id}/stale_{i}.pdf",
                mime_type="application/pdf",
                file_size_bytes=100,
                sha256_hash=uuid.uuid4().hex,
            ))
            db_session.add(ExtractionJob(
                id=job_id,
                document_id=doc_id,
                status="needs_review",
                priority="standard",
            ))
            db_session.add(ExtractedRecord(
                id=record_id,
                job_id=job_id,
                document_id=doc_id,
                document_type="invoice",
                extracted_data={"amount": "100.00"},
                confidence_score=0.6,
                needs_review=True,
                validation_status="pending_review",
                review_reason="low_confidence",
                created_at=created,
            ))
            record_ids.append(record_id)

        await db_session.commit()
        return record_ids

    return _seed
