"""Document upload and management endpoints."""
from __future__ import annotations

import uuid

import redis.asyncio as aioredis
import arq
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.middleware import get_api_key
from app.config import settings
from app.dependencies import get_db, get_redis, get_storage
from app.models.api_key import APIKey
from app.models.document import Document
from app.models.job import ExtractionJob
from app.schemas.responses import UploadResponse
from app.storage.base import StorageBackend
from app.utils.hashing import hash_file
from app.utils.mime import detect_mime_type, is_allowed_mime_type

router = APIRouter(prefix="/documents", tags=["documents"])


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
    api_key: APIKey = Depends(get_api_key),
) -> UploadResponse:
    """Upload a document for processing."""
    file_bytes = await file.read()

    if len(file_bytes) > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(400, f"File exceeds {settings.max_file_size_mb}MB limit")

    mime_type = detect_mime_type(file_bytes)
    if not is_allowed_mime_type(mime_type):
        raise HTTPException(415, f"Unsupported file type: {mime_type}")

    sha256 = hash_file(file_bytes)

    if not force:
        existing = await db.execute(
            select(Document).where(Document.sha256_hash == sha256)
        )
        doc = existing.scalar_one_or_none()
        if doc:
            job_result = await db.execute(
                select(ExtractionJob)
                .where(ExtractionJob.document_id == doc.id)
                .order_by(ExtractionJob.created_at.desc())
            )
            job = job_result.scalar_one_or_none()
            return UploadResponse(
                document_id=str(doc.id),
                job_id=str(job.id) if job else "",
                filename=doc.original_filename,
                duplicate=True,
                message="Duplicate document detected. Returning existing job.",
            )

    doc_id = uuid.uuid4()
    key = f"documents/{doc_id}/{file.filename}"
    await storage.upload(key, file_bytes, mime_type)

    doc = Document(
        id=doc_id,
        original_filename=file.filename or "unknown",
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

    if webhook_secret and settings.aes_key:
        from app.services.webhook_sender import encrypt_secret

        job.webhook_secret_encrypted = encrypt_secret(webhook_secret, settings.aes_key)

    db.add(job)
    await db.commit()

    # Enqueue ARQ job
    arq_redis = await arq.create_pool(
        arq.connections.RedisSettings.from_dsn(settings.redis_url)
    )
    await arq_redis.enqueue_job(
        "process_document",
        str(job_id),
        _queue_name=settings.worker_queue,
        _job_id=str(job_id),
    )
    await arq_redis.aclose()

    return UploadResponse(
        document_id=str(doc_id),
        job_id=str(job_id),
        filename=file.filename or "",
        duplicate=False,
        message="Document queued for processing.",
    )


@router.delete("/{document_id}", status_code=204, response_class=Response)
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    api_key: APIKey = Depends(get_api_key),
) -> None:
    """Delete a document and its storage file."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "Document not found")

    await storage.delete(doc.stored_path)
    await db.delete(doc)
    await db.commit()
