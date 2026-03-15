from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.job import ExtractionJob
from app.models.record import ExtractedRecord


async def _seed_review_item(db: AsyncSession, *, created_at: datetime | None = None) -> str:
    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    record_id = str(uuid.uuid4())

    db.add(
        Document(
            id=doc_id,
            original_filename="review.pdf",
            stored_path=f"documents/{doc_id}/review.pdf",
            mime_type="application/pdf",
            file_size_bytes=10,
            sha256_hash=uuid.uuid4().hex,
        )
    )
    db.add(
        ExtractionJob(
            id=job_id,
            document_id=doc_id,
            status="needs_review",
            priority="standard",
        )
    )
    db.add(
        ExtractedRecord(
            id=record_id,
            job_id=job_id,
            document_id=doc_id,
            document_type="invoice",
            extracted_data={"invoice_number": "INV-1", "total_amount": 13000},
            confidence_score=0.62,
            needs_review=True,
            validation_status="pending_review",
            review_reason="low_confidence",
            created_at=created_at,
        )
    )
    await db.commit()
    return record_id


@pytest.mark.asyncio
async def test_review_claim_and_approve(client: AsyncClient, db_session: AsyncSession):
    record_id = await _seed_review_item(db_session)

    claim = await client.post(f"/api/v1/review/items/{record_id}/claim")
    assert claim.status_code == 200
    assert claim.json()["status"] == "claimed"

    approve = await client.post(f"/api/v1/review/items/{record_id}/approve")
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"

    logs = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.entity_id == record_id).order_by(AuditLog.id.asc())
        )
    ).scalars().all()
    assert len(logs) >= 2
    assert logs[-1].action == "review.approved"


@pytest.mark.asyncio
async def test_review_parallel_claim_race(client: AsyncClient, db_session: AsyncSession):
    record_id = await _seed_review_item(db_session)

    first, second = await asyncio.gather(
        client.post(f"/api/v1/review/items/{record_id}/claim"),
        client.post(f"/api/v1/review/items/{record_id}/claim"),
    )
    assert sorted([first.status_code, second.status_code]) == [200, 409]


@pytest.mark.asyncio
async def test_review_correct_conflict_claim(client: AsyncClient, db_session: AsyncSession):
    record_id = await _seed_review_item(db_session)

    first_claim = await client.post(f"/api/v1/review/items/{record_id}/claim")
    assert first_claim.status_code == 200

    second_claim = await client.post(f"/api/v1/review/items/{record_id}/claim")
    assert second_claim.status_code == 409

    correct = await client.post(
        f"/api/v1/review/items/{record_id}/correct",
        json={"corrections": {"invoice_number": "INV-1A"}, "reviewer_notes": "fixed"},
    )
    assert correct.status_code == 200
    assert correct.json()["status"] == "corrected"


@pytest.mark.asyncio
async def test_review_metrics_reports_sla_and_roi(client: AsyncClient, db_session: AsyncSession):
    now = datetime.now(timezone.utc)
    stale_created_at = now - timedelta(hours=30)
    fresh_created_at = now - timedelta(hours=2)

    await _seed_review_item(db_session, created_at=stale_created_at)
    await _seed_review_item(db_session, created_at=stale_created_at)
    fresh_id = await _seed_review_item(db_session, created_at=fresh_created_at)

    # Claim one fresh item so queue has both pending and claimed records.
    claim = await client.post(f"/api/v1/review/items/{fresh_id}/claim")
    assert claim.status_code == 200

    metrics = await client.get("/api/v1/review/metrics?stale_after_hours=24")
    assert metrics.status_code == 200
    metrics_data = metrics.json()
    assert metrics_data["queue"]["stale"] >= 2
    assert metrics_data["sla"]["breach_rate"] > 0
    assert len(metrics_data["sla"]["escalation_item_ids"]) >= 2

    summary = await client.get("/api/v1/roi/summary")
    assert summary.status_code == 200
    assert "kpis" in summary.json()

    report = await client.post("/api/v1/reports/generate", json={"format": "json"})
    assert report.status_code == 200
    report_id = report.json()["report_id"]

    listing = await client.get("/api/v1/reports")
    assert listing.status_code == 200
    assert any(item["report_id"] == report_id for item in listing.json()["items"])

    fetched = await client.get(f"/api/v1/reports/{report_id}")
    assert fetched.status_code == 200
    assert fetched.json()["metadata"]["report_id"] == report_id


@pytest.mark.asyncio
async def test_report_generation_failure_marks_failed_metadata(client: AsyncClient):
    with patch.object(Path, "write_text", side_effect=OSError("disk full")):
        response = await client.post("/api/v1/reports/generate", json={"format": "json"})

    assert response.status_code == 500
    payload = response.json()
    assert "detail" in payload
    report_id = payload["detail"]["report_id"]

    get_resp = await client.get(f"/api/v1/reports/{report_id}")
    assert get_resp.status_code == 200
    metadata = get_resp.json()["metadata"]
    assert metadata["status"] == "failed"
    assert "disk full" in (metadata["error_message"] or "")
