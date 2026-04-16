"""End-to-end tests: real PDF upload → Anthropic extraction → results check.

These tests require:
  - ANTHROPIC_API_KEY set in the environment
  - A live database (or the test DB with the real worker running)

Skip condition: the `skip_without_api_key` fixture skips all tests when
ANTHROPIC_API_KEY is absent so the suite stays green in CI without credentials.

Run only e2e tests:
    pytest -m e2e tests/e2e/

Exclude e2e tests:
    pytest -m "not e2e"
"""
from __future__ import annotations

import asyncio
import io
import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

# Reuse the hashing util and models from the test suite
from app.dependencies import get_arq_pool, get_db, get_redis, get_storage
from app.models import APIKey
from app.utils.hashing import hash_api_key

# Shared constants
E2E_API_KEY = "e2e-test-api-key-" + uuid.uuid4().hex[:8]
POLL_INTERVAL_S = 3
POLL_TIMEOUT_S = 120
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _upload_pdf(client: AsyncClient, pdf_bytes: bytes, filename: str) -> dict:
    """Upload a PDF and return the 202 response body."""
    with (
        patch("app.api.documents.detect_mime_type", return_value="application/pdf"),
        patch("app.api.documents.is_allowed_mime_type", return_value=True),
    ):
        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": (filename, io.BytesIO(pdf_bytes), "application/pdf")},
        )
    assert response.status_code == 202, f"Upload failed: {response.text}"
    return response.json()


async def _poll_job(client: AsyncClient, job_id: str) -> dict:
    """Poll job status until terminal or timeout; return final job JSON."""
    elapsed = 0.0
    while elapsed < POLL_TIMEOUT_S:
        resp = await client.get(f"/api/v1/jobs/{job_id}")
        assert resp.status_code == 200, f"Job poll failed: {resp.text}"
        data = resp.json()
        if data["status"] in TERMINAL_STATUSES:
            return data
        await asyncio.sleep(POLL_INTERVAL_S)
        elapsed += POLL_INTERVAL_S

    pytest.fail(f"Job {job_id} did not reach terminal status within {POLL_TIMEOUT_S}s")


async def _get_record(client: AsyncClient, job_id: str) -> dict:
    """Fetch the extracted record for a completed job."""
    resp = await client.get(f"/api/v1/jobs/{job_id}/record")
    assert resp.status_code == 200, f"Record fetch failed: {resp.text}"
    return resp.json()


def _count_non_empty_string_fields(data: dict) -> int:
    """Recursively count leaf string values that are non-empty."""
    count = 0
    for v in data.values():
        if isinstance(v, str) and v.strip():
            count += 1
        elif isinstance(v, dict):
            count += _count_non_empty_string_fields(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    count += _count_non_empty_string_fields(item)
                elif isinstance(item, str) and item.strip():
                    count += 1
    return count


# ---------------------------------------------------------------------------
# Shared e2e client fixture (real app, in-memory SQLite, no worker)
# ---------------------------------------------------------------------------

@pytest.fixture
async def e2e_client(db_session, test_redis, fake_storage, fake_arq_pool):
    """
    AsyncClient wired to the real FastAPI app with the same overrides used in
    integration tests, plus an e2e-specific API key seeded into the DB.
    """
    from sqlalchemy import select

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

    # Seed the e2e API key
    key_hash = hash_api_key(E2E_API_KEY)
    existing = await db_session.execute(
        select(APIKey).where(APIKey.key_hash == key_hash)
    )
    if existing.scalar_one_or_none() is None:
        api_key_row = APIKey(
            id=str(uuid.uuid4()),
            name="e2e-test-key",
            role="admin",
            key_hash=key_hash,
            is_active=True,
            rate_limit_per_minute=1000,
        )
        db_session.add(api_key_row)
        await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": E2E_API_KEY},
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# E2E tests
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_invoice_extraction_e2e(
    skip_without_api_key,  # noqa: F811 — fixture used for side-effect only
    synthetic_invoice_pdf: bytes,
    e2e_client: AsyncClient,
):
    """
    Upload a synthetic invoice PDF through the real FastAPI app, poll until the
    extraction job reaches a terminal state, then assert that at least 3
    non-empty string fields were extracted from the document.

    The test is intentionally forgiving: it checks field presence, not exact
    values, because LLM output is non-deterministic.
    """
    upload_data = await _upload_pdf(e2e_client, synthetic_invoice_pdf, "invoice_e2e.pdf")
    job_id = upload_data["job_id"]

    job = await _poll_job(e2e_client, job_id)

    assert job["status"] == "completed", (
        f"Invoice extraction job did not complete successfully. "
        f"Final status: {job['status']}. "
        f"Error: {job.get('error_message')}"
    )

    record = await _get_record(e2e_client, job_id)
    extracted = record.get("extracted_data") or {}

    non_empty_fields = _count_non_empty_string_fields(extracted)
    assert non_empty_fields >= 3, (
        f"Expected at least 3 non-empty string fields in extracted invoice data, "
        f"got {non_empty_fields}. Extracted data: {extracted}"
    )


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_bank_statement_extraction_e2e(
    skip_without_api_key,  # noqa: F811 — fixture used for side-effect only
    synthetic_bank_statement_pdf: bytes,
    e2e_client: AsyncClient,
):
    """
    Upload a synthetic bank statement PDF through the real FastAPI app, poll
    until the extraction job reaches a terminal state, then assert that at least
    3 non-empty string fields were extracted from the document.

    Verification is intentionally permissive — we confirm the pipeline ran and
    produced output, not that every field matches a known value.
    """
    upload_data = await _upload_pdf(
        e2e_client, synthetic_bank_statement_pdf, "bank_statement_e2e.pdf"
    )
    job_id = upload_data["job_id"]

    job = await _poll_job(e2e_client, job_id)

    assert job["status"] == "completed", (
        f"Bank statement extraction job did not complete successfully. "
        f"Final status: {job['status']}. "
        f"Error: {job.get('error_message')}"
    )

    record = await _get_record(e2e_client, job_id)
    extracted = record.get("extracted_data") or {}

    non_empty_fields = _count_non_empty_string_fields(extracted)
    assert non_empty_fields >= 3, (
        f"Expected at least 3 non-empty string fields in extracted bank statement data, "
        f"got {non_empty_fields}. Extracted data: {extracted}"
    )
