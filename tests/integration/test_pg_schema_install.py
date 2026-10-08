"""Opt-in fresh-install and synthetic legacy PostgreSQL acceptance.

DOCEXTRACT_SCHEMA_TEST_MANIFEST names a host-provisioned JSON mapping each
scenario below to an empty, dedicated loopback database. No database is created
or dropped here. Run with --noconftest; ORM/Alembic imports use fresh subprocesses
and neutral working directories so SQLite metadata patches and .env files cannot
supply the schema or connection settings.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
HEAD = "013_eval_log_uuid_repair"
SCENARIOS = (
    "metadata", "fresh", "upgrade_011", "legacy", "uuid", "missing_fk",
    "bad_uuid", "orphan", "collision",
)


@pytest.fixture(scope="module")
def manifest():
    filename = os.environ.get("DOCEXTRACT_SCHEMA_TEST_MANIFEST")
    if not filename:
        pytest.skip("requires host-provisioned DOCEXTRACT_SCHEMA_TEST_MANIFEST")
    urls = json.loads(Path(filename).read_text())
    assert set(urls) == set(SCENARIOS), "manifest must supply all nine scenarios"
    targets = set()
    for value in urls.values():
        url = make_url(value)
        assert url.drivername == "postgresql+asyncpg"
        assert url.host in {"127.0.0.1", "localhost", "::1"}
        assert url.database and url.database.startswith("docextract_test_")
        targets.add((url.port or 5432, url.database))
    assert len(targets) == len(SCENARIOS), "each scenario needs its own database"
    return urls


async def _sql(url, statement, parameters=None):
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(statement), parameters or {})
            return result.all() if result.returns_rows else []
    finally:
        await engine.dispose()


async def _empty(url):
    rows = await _sql(url, """
        SELECT relname FROM pg_class JOIN pg_namespace n ON n.oid = relnamespace
        WHERE n.nspname = 'public' AND relkind IN ('r', 'p', 'v', 'm', 'S')
    """)
    assert not rows, "host must provide an empty database; refusing existing tables"


async def _child(url, code):
    # Settings reads .env relative to cwd. Never launch from the repository or home.
    env = {**os.environ, "DATABASE_URL": url, "PYTHONPATH": str(ROOT),
           "PYTHONDONTWRITEBYTECODE": "1"}
    with tempfile.TemporaryDirectory(prefix="docextract-schema-cwd-") as cwd:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", code, cwd=cwd, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        try:
            output, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        except BaseException:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
            raise
    return proc.returncode, output.decode(errors="replace")


async def _alembic(url, target="head", operation="upgrade", succeeds=True):
    code = f"""
from alembic import command
from alembic.config import Config
config = Config({str(ROOT / 'alembic.ini')!r})
config.set_main_option('script_location', {str(ROOT / 'alembic')!r})
command.{operation}(config, {target!r})
"""
    returncode, output = await _child(url, code)
    if succeeds:
        assert returncode == 0, output
    else:
        assert returncode != 0, "invalid legacy data must reject the migration"
    return output


async def _shape(url, expected_revision=None):
    columns = dict(await _sql(url, """
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'eval_log'
        AND column_name IN ('id', 'job_id')
    """))
    assert columns == {"id": "uuid", "job_id": "uuid"}
    fks = await _sql(url, """
        SELECT c.confdeltype::text, a.attname, parent.attname FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
        JOIN pg_attribute parent
          ON parent.attrelid = c.confrelid AND parent.attnum = ANY(c.confkey)
        WHERE c.conrelid = 'eval_log'::regclass
        AND c.confrelid = 'extraction_jobs'::regclass AND c.contype = 'f'
    """)
    assert fks == [("n", "job_id", "id")], "exact job FK must use ON DELETE SET NULL"
    if expected_revision:
        assert await _sql(url, "SELECT version_num FROM alembic_version") == [(expected_revision,)]
        indexes = {row[0] for row in await _sql(
            url, "SELECT indexname FROM pg_indexes WHERE tablename = 'eval_log'",
        )}
        assert {"ix_eval_log_job_id", "ix_eval_log_created_at"} <= indexes


async def _seed(url):
    ids = {name: str(uuid.uuid4()) for name in ("doc", "job", "eval", "record")}
    await _sql(url, """
        INSERT INTO documents(id, original_filename, stored_path, file_size_bytes,
                              mime_type, sha256_hash)
        VALUES (CAST(:doc AS uuid), 'schema.txt', 'schema.txt', 4, 'text/plain', :doc)
    """, ids)
    await _sql(url, """
        INSERT INTO extraction_jobs(id, document_id)
        VALUES (CAST(:job AS uuid), CAST(:doc AS uuid))
    """, ids)
    return ids


async def _score(url, ids, nullable=False):
    await _sql(url, """
        INSERT INTO eval_log(id, job_id, completeness, field_accuracy,
                             hallucination_absence, format_compliance, composite)
        VALUES (:eval, :job, 1, 1, 1, 1, 1.0)
    """, {"eval": ids["eval"], "job": None if nullable else ids["job"]})


async def _rows(url):
    return await _sql(url, """
        SELECT id::text, job_id::text, completeness, field_accuracy,
               hallucination_absence, format_compliance, composite, created_at
        FROM eval_log ORDER BY id::text
    """)


async def _legacy(url):
    await _empty(url)
    await _alembic(url, "012_eval_log")
    # Synthetic compatibility fixture. Original012's incompatible FK could not
    # have installed successfully on this PostgreSQL schema.
    await _sql(url, "ALTER TABLE eval_log DROP CONSTRAINT eval_log_job_id_fkey")
    await _sql(url, "ALTER TABLE eval_log ALTER COLUMN id DROP DEFAULT")
    await _sql(url, "ALTER TABLE eval_log ALTER COLUMN id TYPE varchar(36) USING id::text")
    await _sql(url, "ALTER TABLE eval_log ALTER COLUMN job_id TYPE varchar(36) USING job_id::text")
    return await _seed(url)


async def test_fresh_orm_metadata_has_compatible_uuid_fk(manifest):
    url = manifest["metadata"]
    await _empty(url)
    code = """
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.models import *
from app.models.database import Base
async def main():
    engine = create_async_engine(os.environ['DATABASE_URL'])
    try:
        async with engine.begin() as conn:
            await conn.execute(text('CREATE EXTENSION IF NOT EXISTS vector'))
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()
asyncio.run(main())
"""
    returncode, output = await _child(url, code)
    assert returncode == 0, output
    await _shape(url)


async def test_fresh_alembic_install_and_fk_trigger_behavior(manifest):
    url = manifest["fresh"]
    await _empty(url)
    await _alembic(url)
    await _shape(url, HEAD)
    ids = await _seed(url)
    await _score(url, ids)
    await _sql(url, """
        INSERT INTO extracted_records(id, job_id, document_id, document_type,
                                      extracted_data, confidence_score, validation_status)
        VALUES (CAST(:record AS uuid), CAST(:job AS uuid), CAST(:doc AS uuid),
                'invoice', '{}', 1.0, 'passed')
    """, ids)
    for table, key in (("extraction_jobs", "job"), ("extracted_records", "record")):
        before = await _sql(url, f"SELECT updated_at FROM {table} WHERE id = CAST(:id AS uuid)", {"id": ids[key]})
        await _sql(url, f"UPDATE {table} SET updated_at = '2000-01-01' WHERE id = CAST(:id AS uuid)", {"id": ids[key]})
        after = await _sql(url, f"SELECT updated_at FROM {table} WHERE id = CAST(:id AS uuid)", {"id": ids[key]})
        assert after[0][0] > before[0][0], "updated_at trigger must overwrite the supplied timestamp"
    # The record FK also references this job; remove only this test's record first.
    await _sql(url, "DELETE FROM extracted_records WHERE id = CAST(:record AS uuid)", ids)
    await _sql(url, "DELETE FROM extraction_jobs WHERE id = CAST(:job AS uuid)", ids)
    assert (await _rows(url))[0][1] is None


async def test_existing_011_upgrade_preserves_job(manifest):
    url = manifest["upgrade_011"]
    await _empty(url)
    await _alembic(url, "011_feedback")
    ids = await _seed(url)
    await _alembic(url)
    await _shape(url, HEAD)
    assert await _sql(url, "SELECT id::text FROM extraction_jobs") == [(ids["job"],)]


async def test_synthetic_legacy_conversion_preserves_scores_and_null(manifest):
    url = manifest["legacy"]
    ids = await _legacy(url)
    await _score(url, ids)
    await _score(url, {**ids, "eval": str(uuid.uuid4())}, nullable=True)
    before = await _rows(url)
    await _alembic(url)
    await _shape(url, HEAD)
    assert await _rows(url) == before
    default = await _sql(url, """
        SELECT column_default FROM information_schema.columns
        WHERE table_name = 'eval_log' AND column_name = 'id'
    """)
    assert "gen_random_uuid" in default[0][0]


@pytest.mark.parametrize("scenario", ["uuid", "missing_fk"])
async def test_uuid_shape_preserves_scores_and_has_fk(manifest, scenario):
    url = manifest[scenario]
    await _empty(url)
    await _alembic(url, "012_eval_log")
    ids = await _seed(url)
    await _score(url, ids)
    if scenario == "missing_fk":
        await _sql(url, "ALTER TABLE eval_log DROP CONSTRAINT eval_log_job_id_fkey")
    before = await _rows(url)
    await _alembic(url)
    await _shape(url, HEAD)
    assert await _rows(url) == before


@pytest.mark.parametrize("scenario", ["bad_uuid", "orphan", "collision"])
async def test_invalid_legacy_upgrade_is_atomic(manifest, scenario):
    url = manifest[scenario]
    ids = await _legacy(url)
    if scenario == "bad_uuid":
        ids["eval"] = "not-a-uuid"
    elif scenario == "orphan":
        ids["job"] = str(uuid.uuid4())
    else:
        ids["eval"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    await _score(url, ids)
    if scenario == "collision":
        await _score(url, {**ids, "eval": ids["eval"].upper()})
    before = await _rows(url)
    output = await _alembic(url, succeeds=False)
    expected = {"bad_uuid": "invalid input syntax for type uuid", "orphan": "ForeignKeyViolationError", "collision": "UniqueViolationError"}
    assert expected[scenario] in output
    assert await _rows(url) == before
    assert await _sql(url, "SELECT version_num FROM alembic_version") == [("012_eval_log",)]
    assert await _sql(url, """
        SELECT data_type FROM information_schema.columns
        WHERE table_name = 'eval_log' AND column_name = 'job_id'
    """) == [("character varying",)]
