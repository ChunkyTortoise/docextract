"""Tests for schema modules."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("API_KEY_SECRET", "test-secret-key-that-is-32-chars!")


def test_events_imports() -> None:
    from app.schemas.events import JOB_STATUS_PROGRESS, JobStatus
    assert JobStatus.QUEUED == "queued"
    assert JobStatus.COMPLETED == "completed"
    assert JOB_STATUS_PROGRESS[JobStatus.QUEUED] == 0
    assert JOB_STATUS_PROGRESS[JobStatus.COMPLETED] == 100


def test_job_event_creation() -> None:
    from app.schemas.events import JobEvent, JobStatus
    event = JobEvent(
        job_id="test-123",
        status=JobStatus.PREPROCESSING,
        progress=50,
        message="Processing page 1",
    )
    assert event.job_id == "test-123"
    assert event.status == JobStatus.PREPROCESSING
    assert event.progress == 50
    assert event.timestamp is not None


def test_requests_imports() -> None:
    from app.schemas.requests import RecordQuery, ReviewRequest, UploadRequest
    assert UploadRequest is not None
    assert ReviewRequest is not None
    assert RecordQuery is not None


def test_upload_request_defaults() -> None:
    from app.schemas.requests import UploadRequest
    req = UploadRequest()
    assert req.document_type_override is None
    assert req.priority == "standard"
    assert req.webhook_url is None
    assert req.force is False


def test_review_request() -> None:
    from app.schemas.requests import ReviewRequest
    req = ReviewRequest(decision="approve", reviewer_notes="Looks correct")
    assert req.decision == "approve"
    assert req.corrections is None


def test_record_query_defaults() -> None:
    from app.schemas.requests import RecordQuery
    query = RecordQuery()
    assert query.page == 1
    assert query.page_size == 20
    assert query.sort_order == "desc"


def test_responses_imports() -> None:
    from app.schemas.responses import (
        ErrorResponse,
        HealthResponse,
        JobResponse,
        PaginatedRecords,
        RecordItem,
        StatsResponse,
        UploadBatchResponse,
        UploadResponse,
    )
    assert JobResponse is not None
    assert UploadResponse is not None
    assert UploadBatchResponse is not None
    assert RecordItem is not None
    assert PaginatedRecords is not None
    assert StatsResponse is not None
    assert HealthResponse is not None
    assert ErrorResponse is not None


def test_health_response() -> None:
    from app.schemas.responses import HealthResponse
    health = HealthResponse(status="healthy", db_ok=True, redis_ok=True)
    assert health.version == "1.0.0"
    assert health.status == "healthy"


def test_error_response() -> None:
    from app.schemas.responses import ErrorResponse
    err = ErrorResponse(error="Not found", detail="Document not found")
    assert err.error == "Not found"
    assert err.request_id is None


def test_job_status_enum_values() -> None:
    from app.schemas.events import JobStatus
    expected = {
        "queued", "preprocessing", "extracting_text", "classifying",
        "extracting_data", "extracting_page", "validating", "embedding", "completed",
        "needs_review", "failed", "cancelled",
    }
    actual = {s.value for s in JobStatus}
    assert actual == expected


def test_models_import() -> None:
    from app.models import (
        APIKey,
        AuditLog,
        Document,
        DocumentEmbedding,
        ExtractedRecord,
        ExtractionJob,
        ValidationError,
    )
    assert APIKey.__tablename__ == "api_keys"
    assert Document.__tablename__ == "documents"
    assert ExtractionJob.__tablename__ == "extraction_jobs"
    assert ExtractedRecord.__tablename__ == "extracted_records"
    assert DocumentEmbedding.__tablename__ == "content_embeddings"
    assert ValidationError.__tablename__ == "validation_errors"
    assert AuditLog.__tablename__ == "audit_logs"


def test_config_settings() -> None:
    from app.config import settings
    assert settings.max_file_size_mb == 50
    assert settings.max_pages == 100
    assert settings.extraction_confidence_threshold == 0.8
    assert settings.ocr_engine == "tesseract"
    assert settings.worker_max_jobs == 10
