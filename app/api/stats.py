"""Statistics and dashboard data endpoint."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.middleware import get_api_key
from app.dependencies import get_db
from app.models.api_key import APIKey
from app.models.document import Document
from app.models.job import ExtractionJob
from app.models.record import ExtractedRecord
from app.schemas.responses import StatsResponse

router = APIRouter(tags=["stats"])


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
) -> StatsResponse:
    """Get aggregate statistics for dashboard."""
    total_docs = (
        await db.execute(select(func.count(Document.id)))
    ).scalar() or 0

    total_jobs = (
        await db.execute(select(func.count(ExtractionJob.id)))
    ).scalar() or 0

    completed = (
        await db.execute(
            select(func.count(ExtractionJob.id)).where(
                ExtractionJob.status == "completed"
            )
        )
    ).scalar() or 0

    failed = (
        await db.execute(
            select(func.count(ExtractionJob.id)).where(
                ExtractionJob.status == "failed"
            )
        )
    ).scalar() or 0

    success_rate = (completed / total_jobs * 100) if total_jobs > 0 else 0.0

    # Avg confidence score across records
    avg_confidence = (
        await db.execute(select(func.avg(ExtractedRecord.confidence_score)))
    ).scalar()

    # Records needing review
    needs_review_count = (
        await db.execute(
            select(func.count(ExtractedRecord.id)).where(
                ExtractedRecord.needs_review == True  # noqa: E712
            )
        )
    ).scalar() or 0

    # Jobs in the last 24 hours
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    jobs_last_24h = (
        await db.execute(
            select(func.count(ExtractionJob.id)).where(
                ExtractionJob.created_at >= cutoff
            )
        )
    ).scalar() or 0

    # Avg processing time (completed jobs only)
    # Computed as seconds between started_at and completed_at
    avg_time = None
    if completed > 0:
        avg_time_result = (
            await db.execute(
                select(
                    func.avg(
                        func.extract(
                            "epoch",
                            ExtractionJob.completed_at - ExtractionJob.started_at,
                        )
                        * 1000
                    )
                ).where(
                    ExtractionJob.status == "completed",
                    ExtractionJob.started_at.isnot(None),
                    ExtractionJob.completed_at.isnot(None),
                )
            )
        ).scalar()
        if avg_time_result is not None:
            avg_time = round(avg_time_result, 0)

    # Doc type breakdown
    type_result = await db.execute(
        select(ExtractedRecord.document_type, func.count(ExtractedRecord.id)).group_by(
            ExtractedRecord.document_type
        )
    )
    doc_type_breakdown = {row[0]: row[1] for row in type_result.all() if row[0]}

    return StatsResponse(
        total_documents=total_docs,
        total_jobs=total_jobs,
        completed_jobs=completed,
        failed_jobs=failed,
        needs_review=needs_review_count,
        success_rate=round(success_rate, 1),
        avg_processing_time_ms=avg_time,
        avg_confidence_score=round(avg_confidence, 3) if avg_confidence else None,
        doc_type_breakdown=doc_type_breakdown,
        jobs_last_24h=jobs_last_24h,
    )
