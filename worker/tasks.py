"""ARQ worker task: orchestrates the full document processing pipeline."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import AsyncSessionLocal
from app.schemas.events import JOB_STATUS_PROGRESS, JobStatus

logger = logging.getLogger(__name__)

# Error classification
TRANSIENT_ERRORS = (httpx.TimeoutException, ConnectionError, OSError)


async def process_document(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    """Full document processing pipeline.

    Pipeline steps:
    1. Load job from DB
    2. Download file from storage
    3. Detect MIME type
    4. Ingest (extract text)
    5. Classify document type
    6. Claude extraction (two-pass)
    7. Validate business rules
    8. Store validation errors
    9. Create embedding
    10. Store record to DB
    11. Update job -> COMPLETED
    12. Send webhook if configured

    Returns dict with status and record_id on success.
    """
    redis: aioredis.Redis = ctx["redis"]

    async with AsyncSessionLocal() as db:
        try:
            return await _process(db, redis, job_id)
        except tuple(TRANSIENT_ERRORS) as e:
            logger.warning("Transient error processing job %s: %s", job_id, e)
            await _fail_job(db, redis, job_id, str(e))
            raise  # ARQ will retry
        except Exception as e:
            logger.error("Permanent error processing job %s: %s", job_id, e, exc_info=True)
            await _fail_job(db, redis, job_id, str(e))
            return {"status": "failed", "error": str(e)}


async def _process(db: AsyncSession, redis: aioredis.Redis, job_id: str) -> dict[str, Any]:
    from app.dependencies import get_storage
    from app.models.document import Document
    from app.models.embedding import DocumentEmbedding
    from app.models.job import ExtractionJob
    from app.models.record import ExtractedRecord
    from app.models.audit_log import AuditLog
    from app.models.validation_error import ValidationError as ValidationErrorModel
    from app.schemas.document_types import DOCUMENT_TYPE_MAP
    from app.services.classifier import classify
    from app.services.claude_extractor import extract
    from app.services.embedder import embed
    from app.services.ingestion import UnsupportedMimeType, ingest
    from app.services.validator import validate
    from app.services.webhook_sender import decrypt_secret, send_webhook
    from app.utils.mime import detect_mime_type
    from worker.events import publish_event

    # 1. Load job
    job_result = await db.execute(select(ExtractionJob).where(ExtractionJob.id == job_id))
    job = job_result.scalar_one_or_none()
    if not job:
        raise ValueError(f"Job {job_id} not found")

    # Load document
    doc_result = await db.execute(select(Document).where(Document.id == job.document_id))
    doc = doc_result.scalar_one()

    # Update -> PREPROCESSING
    await _update_job_status(db, redis, job, JobStatus.PREPROCESSING)

    # 2. Download file
    storage = await get_storage()
    file_bytes = await storage.download(doc.stored_path)

    # 3. Detect MIME type
    mime_type = detect_mime_type(file_bytes) or doc.mime_type

    # 4. Ingest -> EXTRACTING_TEXT
    await _update_job_status(db, redis, job, JobStatus.EXTRACTING_TEXT)
    try:
        extracted = ingest(file_bytes, mime_type, doc.original_filename)
    except UnsupportedMimeType as e:
        raise ValueError(str(e))  # Permanent error

    # 5. Classify -> CLASSIFYING
    await _update_job_status(db, redis, job, JobStatus.CLASSIFYING)
    classification = await classify(extracted.text, db=db)
    doc_type = classification.doc_type

    # 6. Extract with Claude -> EXTRACTING_DATA
    await _update_job_status(db, redis, job, JobStatus.EXTRACTING_DATA)
    schema_class = DOCUMENT_TYPE_MAP.get(doc_type)
    extraction_result = await extract(extracted.text, doc_type, schema_class, db=db)

    # 7. Validate -> VALIDATING
    await _update_job_status(db, redis, job, JobStatus.VALIDATING)
    validation_result = validate(doc_type, extraction_result.data, extraction_result.confidence)

    # 8. Embed -> EMBEDDING
    await _update_job_status(db, redis, job, JobStatus.EMBEDDING)
    embedding_text = extracted.text[:2000]
    embedding_vector = await embed(embedding_text, db=db)

    # 9. Store record
    record_id = str(uuid.uuid4())
    record = ExtractedRecord(
        id=record_id,
        job_id=job.id,
        document_id=job.document_id,
        document_type=doc_type,
        extracted_data=extraction_result.data,
        raw_text=extracted.text[:5000],
        confidence_score=extraction_result.confidence,
        needs_review=validation_result.needs_review,
        validation_status=(
            "pending_review"
            if validation_result.needs_review
            else ("failed" if not validation_result.is_valid else "passed")
        ),
        review_reason=(
            "Auto-queued due to validation/review triggers"
            if validation_result.needs_review
            else None
        ),
    )
    db.add(record)
    await db.flush()

    db.add(
        AuditLog(
            entity_type="record",
            entity_id=record.id,
            action="record.created",
            actor="worker",
            old_data=None,
            new_data={
                "validation_status": record.validation_status,
                "needs_review": record.needs_review,
                "confidence_score": record.confidence_score,
            },
            metadata_={"job_id": str(job.id), "document_type": doc_type},
        )
    )

    # Store validation errors
    for err in validation_result.errors:
        db.add(ValidationErrorModel(
            id=str(uuid.uuid4()),
            record_id=record.id,
            field_name=err.field_path,
            rule_name=err.error_type,
            message=err.message,
            severity=err.severity.value.lower(),
        ))

    # Store embedding
    db.add(DocumentEmbedding(
        id=str(uuid.uuid4()),
        record_id=record.id,
        content_text=embedding_text,
        embedding=embedding_vector,
    ))

    # 10. Complete job
    now = datetime.now(timezone.utc)
    job.status = (
        JobStatus.NEEDS_REVIEW.value
        if validation_result.needs_review
        else JobStatus.COMPLETED.value
    )
    job.document_type_detected = doc_type
    job.completed_at = now
    if job.started_at:
        job.processing_time_ms = int((now - job.started_at).total_seconds() * 1000)

    await db.commit()

    # Publish completion event
    await publish_event(redis, job_id, {
        "job_id": job_id,
        "status": job.status,
        "progress": JOB_STATUS_PROGRESS[
            JobStatus.NEEDS_REVIEW if validation_result.needs_review else JobStatus.COMPLETED
        ],
        "message": (
            f"Extraction complete and queued for review. Document type: {doc_type}"
            if validation_result.needs_review
            else f"Extraction complete. Document type: {doc_type}"
        ),
    })

    # 11. Send webhook if configured
    if job.webhook_url:
        secret = ""
        if job.webhook_secret_encrypted:
            secret = decrypt_secret(job.webhook_secret_encrypted, settings.aes_key)
        await send_webhook(job.webhook_url, {
            "event": "job.completed",
            "job_id": job_id,
            "status": "completed",
            "document_type": doc_type,
            "record_id": record_id,
        }, secret)

    return {"status": "completed", "record_id": record_id, "document_type": doc_type}


async def _update_job_status(db: AsyncSession, redis: aioredis.Redis, job: Any, status: JobStatus) -> None:
    from worker.events import publish_event

    job.status = status.value
    job.progress_pct = JOB_STATUS_PROGRESS.get(status, 0)
    job.stage_detail = status.value

    if status == JobStatus.PREPROCESSING:
        job.started_at = datetime.now(timezone.utc)

    await db.flush()
    await publish_event(redis, str(job.id), {
        "job_id": str(job.id),
        "status": status.value,
        "progress": JOB_STATUS_PROGRESS.get(status, 0),
        "message": f"Status: {status.value}",
    })


async def _fail_job(db: AsyncSession, redis: aioredis.Redis, job_id: str, error: str) -> None:
    from app.models.job import ExtractionJob
    from worker.events import publish_event

    try:
        job_result = await db.execute(select(ExtractionJob).where(ExtractionJob.id == job_id))
        job = job_result.scalar_one_or_none()
        if job:
            job.status = JobStatus.FAILED.value
            job.error_message = error[:500]
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()
    except Exception as e:
        logger.error("Failed to update job failure status: %s", e)

    await publish_event(redis, job_id, {
        "job_id": job_id,
        "status": JobStatus.FAILED.value,
        "progress": -1,
        "message": f"Failed: {error[:100]}",
    })
