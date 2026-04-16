"""Integration tests for GET /api/v1/metrics/business."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.job import ExtractionJob
from app.models.llm_trace import LLMTrace


async def _create_doc_and_job(
    db: AsyncSession,
    *,
    status: str = "completed",
    started_offset_s: int = 10,
    completed_offset_s: int = 70,
) -> tuple[str, str]:
    """Insert a document and job created within the last 30 days."""
    now = datetime.now(UTC)
    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    doc = Document(
        id=doc_id,
        original_filename="biz_test.pdf",
        stored_path=f"documents/{doc_id}/biz_test.pdf",
        mime_type="application/pdf",
        file_size_bytes=2048,
        sha256_hash=uuid.uuid4().hex,
    )
    db.add(doc)

    job = ExtractionJob(
        id=job_id,
        document_id=doc_id,
        status=status,
        priority="standard",
        started_at=now - timedelta(seconds=started_offset_s),
        completed_at=now - timedelta(seconds=completed_offset_s - started_offset_s)
        if status == "completed"
        else None,
    )
    db.add(job)
    await db.commit()
    return doc_id, job_id


async def _create_trace(db: AsyncSession, job_id: str | None = None) -> str:
    """Insert an LLMTrace created within the last 30 days."""
    trace_id = str(uuid.uuid4())
    trace = LLMTrace(
        id=trace_id,
        model="claude-haiku-4-5-20251001",
        operation="extract",
        input_tokens=500,
        output_tokens=200,
        latency_ms=1200,
        status="success",
    )
    db.add(trace)
    await db.commit()
    return trace_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_business_metrics_empty_db(client: AsyncClient):
    """Returns valid response with zeros when no jobs exist."""
    response = await client.get("/api/v1/metrics/business")
    assert response.status_code == 200
    data = response.json()

    assert "straight_through_rate" in data
    assert "avg_cost_usd" in data
    assert "p50_ms" in data
    assert "p95_ms" in data
    assert "docs_30d" in data
    assert "hitl_escalation_rate" in data

    assert isinstance(data["straight_through_rate"], float)
    assert isinstance(data["avg_cost_usd"], float)
    assert isinstance(data["p50_ms"], float)
    assert isinstance(data["p95_ms"], float)
    assert isinstance(data["docs_30d"], int)
    assert isinstance(data["hitl_escalation_rate"], float)


@pytest.mark.asyncio
async def test_business_metrics_with_jobs(client: AsyncClient, db_session: AsyncSession):
    """Returns correct counts and types with real job records."""
    # Create 2 completed + 1 failed job
    await _create_doc_and_job(db_session, status="completed")
    await _create_doc_and_job(db_session, status="completed")
    await _create_doc_and_job(db_session, status="failed")
    await _create_trace(db_session)

    response = await client.get("/api/v1/metrics/business")
    assert response.status_code == 200
    data = response.json()

    # docs_30d must count all three jobs created above
    assert data["docs_30d"] >= 3

    # straight_through_rate: at least 2 completed out of 3+
    assert 0.0 <= data["straight_through_rate"] <= 1.0

    # hitl_escalation_rate is a fixed placeholder
    assert data["hitl_escalation_rate"] == 0.12

    # avg_cost_usd defaults to 0.03 (no cost_usd on LLMTrace model yet)
    assert data["avg_cost_usd"] == pytest.approx(0.03, rel=1e-3)

    # percentiles are floats >= 0
    assert data["p50_ms"] >= 0.0
    assert data["p95_ms"] >= 0.0


@pytest.mark.asyncio
async def test_business_metrics_auth_required(client: AsyncClient):
    """Endpoint rejects requests with missing API key."""
    response = await client.get(
        "/api/v1/metrics/business",
        headers={"X-API-Key": ""},
    )
    assert response.status_code in (401, 403)
