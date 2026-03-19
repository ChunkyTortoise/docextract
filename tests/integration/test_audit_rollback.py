"""Audit rollback and SLA breach-rate tests."""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.job import ExtractionJob
from app.models.record import ExtractedRecord


async def _seed_review_record(
    db: AsyncSession,
    *,
    status: str = "pending_review",
    needs_review: bool = True,
) -> str:
    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    record_id = str(uuid.uuid4())

    db.add(Document(
        id=doc_id,
        original_filename="test.pdf",
        stored_path=f"documents/{doc_id}/test.pdf",
        mime_type="application/pdf",
        file_size_bytes=100,
        sha256_hash=uuid.uuid4().hex,
    ))
    db.add(ExtractionJob(
        id=job_id,
        document_id=doc_id,
        status="needs_review",
        priority="standard",
    ))
    db.add(ExtractedRecord(
        id=record_id,
        job_id=job_id,
        document_id=doc_id,
        document_type="invoice",
        extracted_data={"invoice_number": "INV-001", "total": "500.00"},
        confidence_score=0.65,
        needs_review=needs_review,
        validation_status=status,
        review_reason="low_confidence",
    ))
    await db.commit()
    return record_id


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_claim(client: AsyncClient, db_session: AsyncSession):
    record_id = await _seed_review_record(db_session, status="pending_review")

    # Inject fault: db.add raises when called with AuditLog
    original_add = db_session.add

    def bad_add(obj):
        if isinstance(obj, AuditLog):
            raise RuntimeError("Simulated audit failure")
        return original_add(obj)

    db_session.add = bad_add
    try:
        response = await client.post(f"/api/v1/review/items/{record_id}/claim")
    finally:
        db_session.add = original_add

    assert response.status_code == 500

    # After rollback, record must still be pending_review
    row = (
        await db_session.execute(
            select(ExtractedRecord).where(ExtractedRecord.id == record_id)
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.validation_status == "pending_review"


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_approve(client: AsyncClient, db_session: AsyncSession):
    record_id = await _seed_review_record(db_session, status="pending_review", needs_review=True)

    original_add = db_session.add

    def bad_add(obj):
        if isinstance(obj, AuditLog):
            raise RuntimeError("Simulated audit failure")
        return original_add(obj)

    db_session.add = bad_add
    try:
        response = await client.post(f"/api/v1/review/items/{record_id}/approve")
    finally:
        db_session.add = original_add

    assert response.status_code == 500

    row = (
        await db_session.execute(
            select(ExtractedRecord).where(ExtractedRecord.id == record_id)
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.needs_review is True


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_correct(client: AsyncClient, db_session: AsyncSession):
    record_id = await _seed_review_record(db_session, status="pending_review", needs_review=True)

    original_add = db_session.add

    def bad_add(obj):
        if isinstance(obj, AuditLog):
            raise RuntimeError("Simulated audit failure")
        return original_add(obj)

    db_session.add = bad_add
    try:
        response = await client.post(
            f"/api/v1/review/items/{record_id}/correct",
            json={"corrections": {"invoice_number": "INV-001-FIXED"}},
        )
    finally:
        db_session.add = original_add

    assert response.status_code == 500

    row = (
        await db_session.execute(
            select(ExtractedRecord).where(ExtractedRecord.id == record_id)
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.needs_review is True
    assert row.validation_status != "corrected"


@pytest.mark.asyncio
async def test_sla_breach_rate_deterministic(
    client: AsyncClient,
    db_session: AsyncSession,
    seed_stale_review_items,
):
    """Verify breach_rate = stale / max(pending+claimed, 1) is computed correctly."""
    # Snapshot state before seeding (other tests may have committed records)
    pre = (await client.get("/api/v1/review/metrics?stale_after_hours=24")).json()
    pre_stale = pre["queue"]["stale"]
    pre_total = pre["queue"]["pending"] + pre["queue"]["claimed"]

    # Seed 3 stale + 1 fresh records
    await seed_stale_review_items(n_stale=3, n_fresh=1)

    response = await client.get("/api/v1/review/metrics?stale_after_hours=24")
    assert response.status_code == 200
    data = response.json()

    total_open = data["queue"]["pending"] + data["queue"]["claimed"]
    stale = data["queue"]["stale"]

    # Exactly 3 new stale records were added
    assert stale == pre_stale + 3
    # Total grew by 4 (3 stale + 1 fresh)
    assert total_open == pre_total + 4
    # breach_rate formula: stale / max(pending+claimed, 1)
    assert data["sla"]["breach_rate"] == round(stale / max(total_open, 1), 4)
