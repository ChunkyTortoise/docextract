"""Job status and SSE streaming endpoints."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.auth.middleware import get_api_key
from app.dependencies import get_db, get_redis
from app.models.api_key import APIKey
from app.models.job import ExtractionJob
from app.models.record import ExtractedRecord
from app.schemas.events import JOB_STATUS_PROGRESS, JobStatus
from app.schemas.responses import JobResponse, RecordItem

router = APIRouter(prefix="/jobs", tags=["jobs"])

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
) -> JobResponse:
    """Get job status and details."""
    result = await db.execute(select(ExtractionJob).where(ExtractionJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")

    return JobResponse(
        id=str(job.id),
        document_id=str(job.document_id),
        status=job.status,
        progress=JOB_STATUS_PROGRESS.get(job.status, 0),
        priority=job.priority,
        stage_detail=job.stage_detail,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        processing_time_ms=None,
    )


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, le=100),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
) -> list[JobResponse]:
    """List jobs with optional status filter."""
    query = select(ExtractionJob).order_by(desc(ExtractionJob.created_at))
    if status:
        query = query.where(ExtractionJob.status == status)
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    jobs = result.scalars().all()

    return [
        JobResponse(
            id=str(j.id),
            document_id=str(j.document_id),
            status=j.status,
            progress=JOB_STATUS_PROGRESS.get(j.status, 0),
            priority=j.priority,
            stage_detail=j.stage_detail,
            error_message=j.error_message,
            created_at=j.created_at,
            started_at=j.started_at,
            completed_at=j.completed_at,
            processing_time_ms=None,
        )
        for j in jobs
    ]


@router.get("/{job_id}/record", response_model=RecordItem)
async def get_job_record(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
) -> RecordItem:
    """Get the extracted record for a specific job."""
    # Verify job exists
    job_result = await db.execute(
        select(ExtractionJob).where(ExtractionJob.id == job_id)
    )
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")

    # Find record linked to this job
    record_result = await db.execute(
        select(ExtractedRecord).where(ExtractedRecord.job_id == job_id)
    )
    record = record_result.scalar_one_or_none()
    if not record:
        raise HTTPException(404, "No record found for this job")

    return RecordItem(
        id=str(record.id),
        job_id=str(record.job_id),
        document_id=str(record.document_id),
        document_type=record.document_type,
        extracted_data=record.extracted_data,
        confidence_score=record.confidence_score,
        needs_review=record.needs_review,
        validation_status=record.validation_status,
        review_status=None,
        created_at=record.created_at,
    )


@router.patch("/{job_id}")
async def cancel_job(
    job_id: str,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    api_key: APIKey = Depends(get_api_key),
):
    """Cancel a job. Request body: {"action": "cancel"}."""
    if body.get("action") != "cancel":
        raise HTTPException(400, "Only 'cancel' action is supported")

    result = await db.execute(
        select(ExtractionJob).where(ExtractionJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")

    if job.status in TERMINAL_STATUSES:
        raise HTTPException(409, f"Job is already in terminal state: {job.status}")

    job.status = JobStatus.CANCELLED
    job.completed_at = datetime.now(timezone.utc)
    await db.commit()

    # Publish cancellation SSE event
    from worker.events import publish_event

    await publish_event(redis, job_id, {
        "job_id": job_id,
        "status": "cancelled",
        "progress": -1,
        "message": "Job cancelled by user",
    })

    return {"status": "cancelled", "job_id": job_id}


@router.get("/{job_id}/events")
async def job_events(
    job_id: str,
    redis: aioredis.Redis = Depends(get_redis),
    api_key: APIKey = Depends(get_api_key),
):
    """SSE stream of job progress events."""
    from worker.events import subscribe_events

    async def event_generator():
        async for event in subscribe_events(redis, job_id):
            yield {
                "data": json.dumps(event),
                "retry": 3000,
            }

    return EventSourceResponse(event_generator())
