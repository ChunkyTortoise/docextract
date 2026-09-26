"""Document upload and management endpoints."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

import arq
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.auth.middleware import require_roles
from app.config import settings
from app.dependencies import get_arq_pool, get_db, get_redis, get_storage
from app.models.api_key import APIKey
from app.models.document import Document
from app.models.job import ExtractionJob
from app.schemas.responses import UploadResponse
from app.storage.base import StorageBackend
from app.utils.hashing import hash_file
from app.utils.mime import detect_mime_type, is_allowed_mime_type

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


def _safe_filename(filename: str | None) -> str:
    """Basename-only filename; reject traversal / absolute paths."""
    if filename is None or filename == "":
        return "unknown"
    name = Path(filename).name
    if not name or name in {".", ".."}:
        raise HTTPException(400, "Invalid filename")
    return name


async def _read_upload_bounded(file: UploadFile) -> bytes:
    """Read upload bytes, enforcing MAX_FILE_SIZE_MB before buffering unbounded."""
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    content_length = file.headers.get("content-length") if file.headers else None
    if content_length is not None:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(400, f"File exceeds {settings.max_file_size_mb}MB limit")
        except ValueError:
            pass
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(400, f"File exceeds {settings.max_file_size_mb}MB limit")
        chunks.append(chunk)
    return b"".join(chunks)



@router.post("/upload", response_model=UploadResponse, status_code=202)
async def upload_document(
    file: UploadFile = File(...),
    document_type_override: str | None = Form(None),
    priority: str = Form("standard"),
    webhook_url: str | None = Form(None),
    webhook_secret: str | None = Form(None),
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    redis: aioredis.Redis = Depends(get_redis),
    arq_pool: arq.ArqRedis = Depends(get_arq_pool),
    api_key: APIKey = Depends(require_roles("operator")),
) -> UploadResponse:
    """Upload a document for processing."""
    file_bytes = await _read_upload_bounded(file)

    mime_type = detect_mime_type(file_bytes)
    if not is_allowed_mime_type(mime_type):
        raise HTTPException(415, f"Unsupported file type: {mime_type}")

    if webhook_url:
        from app.api.webhooks import validate_webhook_url

        try:
            await run_in_threadpool(validate_webhook_url, webhook_url)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    sha256 = hash_file(file_bytes)

    if not force:
        existing = await db.execute(
            select(Document).where(Document.sha256_hash == sha256)
        )
        doc = existing.scalars().first()
        if doc:
            job_result = await db.execute(
                select(ExtractionJob)
                .where(ExtractionJob.document_id == doc.id)
                .order_by(ExtractionJob.created_at.desc())
            )
            job = job_result.scalars().first()
            return UploadResponse(
                document_id=str(doc.id),
                job_id=str(job.id) if job else "",
                filename=doc.original_filename,
                duplicate=True,
                message="Duplicate document detected. Returning existing job.",
            )

    doc_id = uuid.uuid4()
    safe_name = _safe_filename(file.filename)
    key = f"documents/{doc_id}/{safe_name}"
    await storage.upload(key, file_bytes, mime_type)

    doc = Document(
        id=doc_id,
        original_filename=safe_name,
        stored_path=key,
        mime_type=mime_type,
        file_size_bytes=len(file_bytes),
        sha256_hash=sha256,
        uploaded_by=api_key.id,
    )
    db.add(doc)

    job_id = uuid.uuid4()
    job = ExtractionJob(
        id=job_id,
        document_id=doc_id,
        status="queued",
        priority=priority,
        document_type_override=document_type_override,
        webhook_url=webhook_url,
    )

    if webhook_secret and not settings.aes_key:
        raise HTTPException(
            400,
            "webhook_secret provided but AES_KEY is not configured; refusing to sign with an empty key",
        )
    if webhook_secret:
        from app.services.webhook_sender import encrypt_secret

        job.webhook_secret_encrypted = encrypt_secret(webhook_secret, settings.aes_key)

    db.add(job)
    await db.commit()

    # Commit before enqueue so the queue never sees invisible rows; an enqueue
    # failure leaves committed, recoverable work (the recovery cron re-enqueues
    # queued jobs) instead of a half-recorded upload.
    queued_message = "Document queued for processing."
    try:
        await arq_pool.enqueue_job(
            "process_document",
            str(job_id),
            _queue_name=settings.worker_queue,
            _job_id=str(job_id),
        )
    except Exception as exc:
        logger.warning("Enqueue failed for job %s; deferring to recovery: %s", job_id, exc)
        job.error_message = f"Queue submission deferred to recovery: {exc}"[:500]
        await db.commit()
        queued_message = "Document stored; queue submission deferred to the recovery worker."

    return UploadResponse(
        document_id=str(doc_id),
        job_id=str(job_id),
        filename=safe_name,
        duplicate=False,
        message=queued_message,
    )


@router.post("/batch", status_code=202)
async def batch_upload(
    files: list[UploadFile] = File(...),
    priority: str = Form("standard"),
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    redis: aioredis.Redis = Depends(get_redis),
    arq_pool: arq.ArqRedis = Depends(get_arq_pool),
    api_key: APIKey = Depends(require_roles("operator")),
):
    """Upload multiple documents for processing."""
    job_ids: list[str] = []
    duplicates: list[str] = []
    errors: list[dict] = []

    for uploaded_file in files:
        try:
            filename = _safe_filename(uploaded_file.filename)
        except HTTPException:
            errors.append({"filename": uploaded_file.filename or "unknown", "reason": "invalid_filename"})
            continue
        try:
            file_bytes = await _read_upload_bounded(uploaded_file)
        except HTTPException:
            errors.append({"filename": filename, "reason": "file_too_large"})
            continue

        mime_type = detect_mime_type(file_bytes)
        if not is_allowed_mime_type(mime_type):
            errors.append({"filename": filename, "reason": "unsupported_type", "mime_type": mime_type})
            continue

        sha256 = hash_file(file_bytes)

        # Dedup check
        if not force:
            existing = await db.execute(
                select(Document).where(Document.sha256_hash == sha256)
            )
            doc = existing.scalars().first()
            if doc:
                duplicates.append(uploaded_file.filename or "unknown")
                continue

        doc_id = uuid.uuid4()
        key = f"documents/{doc_id}/{filename}"
        await storage.upload(key, file_bytes, mime_type)

        doc = Document(
            id=doc_id,
            original_filename=filename,
            stored_path=key,
            mime_type=mime_type,
            file_size_bytes=len(file_bytes),
            sha256_hash=sha256,
            uploaded_by=api_key.id,
        )
        db.add(doc)

        job_id = uuid.uuid4()
        job = ExtractionJob(
            id=job_id,
            document_id=doc_id,
            status="queued",
            priority=priority,
        )
        db.add(job)
        await db.flush()

        job_ids.append(str(job_id))

    await db.commit()

    # Enqueue only after the commit: workers can never observe invisible rows,
    # and a mid-batch failure can never leave queued-but-deleted work behind.
    deferred: list[str] = []
    for job_id in job_ids:
        try:
            await arq_pool.enqueue_job(
                "process_document",
                job_id,
                _queue_name=settings.worker_queue,
                _job_id=job_id,
            )
        except Exception as exc:
            # Committed and recoverable: the recovery cron re-enqueues it.
            logger.warning("Enqueue failed for batch job %s; deferring: %s", job_id, exc)
            deferred.append(job_id)
            errors.append({"job_id": job_id, "reason": "enqueue_deferred_to_recovery"})

    return {"job_ids": job_ids, "duplicates": duplicates, "errors": errors, "deferred": deferred}


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    api_key: APIKey = Depends(require_roles("operator")),
) -> Response:
    """Delete a document and its storage file."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "Document not found")

    await storage.delete(doc.stored_path)
    await db.delete(doc)
    await db.commit()
    return Response(status_code=204)
