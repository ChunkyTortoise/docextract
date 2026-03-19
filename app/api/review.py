"""Human-in-the-loop review queue endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.middleware import require_roles
from app.dependencies import get_db
from app.models.api_key import APIKey
from app.models.audit_log import AuditLog
from app.models.record import ExtractedRecord

router = APIRouter(prefix="/review", tags=["review"])

REVIEW_STATUSES = {"pending_review", "claimed", "approved", "corrected"}


async def _append_audit(
    db: AsyncSession,
    *,
    record: ExtractedRecord,
    action: str,
    actor: str,
    old_data: dict | None,
    new_data: dict | None,
    metadata: dict | None = None,
) -> None:
    payload = {
        "entity_type": "record",
        "entity_id": record.id,
        "action": action,
        "actor": actor,
        "old_data": old_data,
        "new_data": new_data,
        "metadata_": metadata or {},
    }
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "sqlite":
        next_id = (
            await db.execute(select(func.coalesce(func.max(AuditLog.id), 0) + 1))
        ).scalar_one()
        payload["id"] = int(next_id)
    db.add(AuditLog(**payload))


@router.get("/items")
async def list_review_items(
    status: str | None = Query(default=None),
    assignee: str | None = Query(default=None),
    doc_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_roles("operator")),
) -> dict:
    filters = []
    if status:
        if status not in REVIEW_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
        filters.append(ExtractedRecord.validation_status == status)
    else:
        filters.append(
            ExtractedRecord.validation_status.in_(["pending_review", "claimed"])
        )

    if assignee:
        filters.append(ExtractedRecord.reviewed_by == assignee)
    if doc_type:
        filters.append(ExtractedRecord.document_type == doc_type)

    query = select(ExtractedRecord).where(and_(*filters)).order_by(ExtractedRecord.created_at.asc())
    count_query = select(func.count()).select_from(query.subquery())

    total = (await db.execute(count_query)).scalar_one()
    items = (
        (
            await db.execute(
                query.offset((page - 1) * page_size).limit(page_size)
            )
        )
        .scalars()
        .all()
    )

    return {
        "items": [
            {
                "id": str(item.id),
                "job_id": str(item.job_id),
                "document_id": str(item.document_id),
                "document_type": item.document_type,
                "status": item.validation_status,
                "assignee": item.reviewed_by,
                "created_at": item.created_at,
                "confidence_score": item.confidence_score,
                "review_reason": item.review_reason,
            }
            for item in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_next": page * page_size < total,
    }


@router.post("/items/{item_id}/claim")
async def claim_review_item(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_roles("operator")),
) -> dict:
    actor = str(api_key.id)

    row = (
        await db.execute(select(ExtractedRecord).where(ExtractedRecord.id == item_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Review item not found")

    # Optimistic concurrency: only claim if still unassigned and review-required.
    result = await db.execute(
        update(ExtractedRecord)
        .where(
            ExtractedRecord.id == item_id,
            ExtractedRecord.needs_review.is_(True),
            ExtractedRecord.validation_status == "pending_review",
            ExtractedRecord.reviewed_by.is_(None),
        )
        .values(validation_status="claimed", reviewed_by=actor)
    )

    if result.rowcount == 0:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Review item is already claimed or no longer pending.",
        )

    claimed = (
        await db.execute(select(ExtractedRecord).where(ExtractedRecord.id == item_id))
    ).scalar_one()
    try:
        await _append_audit(
            db,
            record=claimed,
            action="review.claimed",
            actor=actor,
            old_data={"status": row.validation_status, "assignee": row.reviewed_by},
            new_data={"status": "claimed", "assignee": actor},
        )
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Audit write failed")
    await db.commit()

    return {"status": "claimed", "item_id": item_id, "assignee": actor}


@router.post("/items/{item_id}/approve")
async def approve_review_item(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_roles("operator")),
) -> dict:
    actor = str(api_key.id)
    item = (
        await db.execute(select(ExtractedRecord).where(ExtractedRecord.id == item_id))
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    if not item.needs_review:
        raise HTTPException(status_code=409, detail="Item is already resolved")

    old = {"status": item.validation_status, "needs_review": item.needs_review}
    item.validation_status = "approved"
    item.needs_review = False
    item.reviewed_by = actor
    item.reviewed_at = datetime.now(timezone.utc)

    try:
        await _append_audit(
            db,
            record=item,
            action="review.approved",
            actor=actor,
            old_data=old,
            new_data={"status": item.validation_status, "needs_review": item.needs_review},
        )
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Audit write failed")
    await db.commit()

    return {"status": "approved", "item_id": item_id}


@router.post("/items/{item_id}/correct")
async def correct_review_item(
    item_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_roles("operator")),
) -> dict:
    actor = str(api_key.id)
    corrections = payload.get("corrections")
    if not isinstance(corrections, dict) or not corrections:
        raise HTTPException(status_code=400, detail="corrections must be a non-empty object")

    notes = payload.get("reviewer_notes")

    item = (
        await db.execute(select(ExtractedRecord).where(ExtractedRecord.id == item_id))
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    if not item.needs_review:
        raise HTTPException(status_code=409, detail="Item is already resolved")

    old = {
        "status": item.validation_status,
        "needs_review": item.needs_review,
        "corrected_data": item.corrected_data,
    }

    item.corrected_data = corrections
    item.reviewer_notes = notes
    item.validation_status = "corrected"
    item.needs_review = False
    item.reviewed_by = actor
    item.reviewed_at = datetime.now(timezone.utc)

    try:
        await _append_audit(
            db,
            record=item,
            action="review.corrected",
            actor=actor,
            old_data=old,
            new_data={
                "status": item.validation_status,
                "needs_review": item.needs_review,
                "corrected_data": corrections,
            },
        )
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Audit write failed")
    await db.commit()

    return {"status": "corrected", "item_id": item_id}


@router.get("/metrics")
async def review_metrics(
    stale_after_hours: int = Query(default=24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_roles("operator")),
) -> dict:
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(hours=stale_after_hours)
    reviewed_cutoff = now - timedelta(hours=24)

    pending = (
        await db.execute(
            select(func.count(ExtractedRecord.id)).where(
                ExtractedRecord.validation_status == "pending_review"
            )
        )
    ).scalar_one()
    claimed = (
        await db.execute(
            select(func.count(ExtractedRecord.id)).where(
                ExtractedRecord.validation_status == "claimed"
            )
        )
    ).scalar_one()
    stale = (
        await db.execute(
            select(func.count(ExtractedRecord.id)).where(
                ExtractedRecord.needs_review.is_(True),
                ExtractedRecord.created_at < stale_cutoff,
            )
        )
    ).scalar_one()
    reviewed_24h = (
        await db.execute(
            select(func.count(ExtractedRecord.id)).where(
                ExtractedRecord.reviewed_at.is_not(None),
                ExtractedRecord.reviewed_at >= reviewed_cutoff,
            )
        )
    ).scalar_one()

    avg_review_seconds = (
        await db.execute(
            select(
                func.avg(
                    func.extract("epoch", ExtractedRecord.reviewed_at)
                    - func.extract("epoch", ExtractedRecord.created_at)
                )
            ).where(ExtractedRecord.reviewed_at.is_not(None))
        )
    ).scalar()

    stale_items = (
        (
            await db.execute(
                select(ExtractedRecord.id)
                .where(
                    ExtractedRecord.needs_review.is_(True),
                    ExtractedRecord.created_at < stale_cutoff,
                )
                .order_by(ExtractedRecord.created_at.asc())
                .limit(25)
            )
        )
        .scalars()
        .all()
    )

    return {
        "queue": {
            "pending": int(pending),
            "claimed": int(claimed),
            "total_open": int(pending + claimed),
            "stale": int(stale),
        },
        "throughput": {
            "reviewed_last_24h": int(reviewed_24h),
            "avg_time_to_review_seconds": float(avg_review_seconds or 0),
        },
        "sla": {
            "stale_after_hours": stale_after_hours,
            "breach_rate": round((float(stale) / float(max(pending + claimed, 1))), 4),
            "escalation_item_ids": [str(item) for item in stale_items],
        },
    }
