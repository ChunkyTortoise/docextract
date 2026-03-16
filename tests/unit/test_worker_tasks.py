"""Tests for worker tasks — pipeline orchestrator."""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


# ---- Stub out heavy optional dependencies before importing worker.tasks ----

def _ensure_stub(module_name: str) -> None:
    """Insert a stub module if the real one isn't available."""
    if module_name not in sys.modules:
        sys.modules[module_name] = MagicMock()


# Stub modules that may not be installed in test environment
for _mod in [
    "fitz",
    "pdfplumber",
    "pytesseract",
    "paddleocr",
    "cv2",
    "sentence_transformers",
    "magic",
    "anthropic",
    "pgvector",
    "pgvector.sqlalchemy",
]:
    _ensure_stub(_mod)


@pytest.fixture
def job_id():
    return str(uuid.uuid4())


@pytest.fixture
def mock_job(job_id):
    """Create a mock ExtractionJob."""
    job = MagicMock()
    job.id = job_id
    job.document_id = uuid.uuid4()
    job.status = "queued"
    job.started_at = None
    job.completed_at = None
    job.webhook_url = None
    job.webhook_secret_encrypted = None
    job.progress_pct = 0
    job.stage_detail = None
    job.document_type_detected = None
    job.error_message = None
    return job


@pytest.fixture
def mock_document():
    """Create a mock Document."""
    doc = MagicMock()
    doc.id = uuid.uuid4()
    doc.original_filename = "invoice.pdf"
    doc.stored_path = "uploads/invoice.pdf"
    doc.mime_type = "application/pdf"
    return doc


@pytest.fixture
def mock_redis():
    return AsyncMock()


class TestProcessDocumentTopLevel:
    """Tests using patched _process to verify error handling."""

    @pytest.mark.asyncio
    async def test_transient_error_reraises(self, job_id, mock_redis):
        """Test that transient errors are re-raised for ARQ retry."""
        from worker.tasks import process_document

        with patch("worker.tasks.AsyncSessionLocal") as mock_session_cls:
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("worker.tasks._process", side_effect=ConnectionError("redis down")):
                with patch("worker.tasks._fail_job", new_callable=AsyncMock):
                    with pytest.raises(ConnectionError):
                        await process_document({"redis": mock_redis}, job_id)

    @pytest.mark.asyncio
    async def test_permanent_error_returns_failed(self, job_id, mock_redis):
        """Test that permanent errors return failed status."""
        from worker.tasks import process_document

        with patch("worker.tasks.AsyncSessionLocal") as mock_session_cls:
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("worker.tasks._process", side_effect=ValueError("bad document")):
                with patch("worker.tasks._fail_job", new_callable=AsyncMock):
                    result = await process_document({"redis": mock_redis}, job_id)

        assert result["status"] == "failed"
        assert "bad document" in result["error"]

    @pytest.mark.asyncio
    async def test_httpx_timeout_is_transient(self, job_id, mock_redis):
        """Test that httpx.TimeoutException triggers retry."""
        from worker.tasks import process_document

        with patch("worker.tasks.AsyncSessionLocal") as mock_session_cls:
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("worker.tasks._process", side_effect=httpx.ReadTimeout("timeout")):
                with patch("worker.tasks._fail_job", new_callable=AsyncMock):
                    with pytest.raises(httpx.ReadTimeout):
                        await process_document({"redis": mock_redis}, job_id)


class TestProcessPipeline:
    """Tests for _process pipeline with fully mocked dependencies."""

    @pytest.fixture
    def pipeline_mocks(self, mock_job, mock_document):
        """Set up all mocks for _process."""
        from app.services.classifier import ClassificationResult
        from app.services.claude_extractor import ExtractionResult
        from app.services.pdf_extractor import ExtractedContent
        from app.services.validator import ValidationResult

        mock_db = AsyncMock()
        job_result = MagicMock()
        job_result.scalar_one_or_none.return_value = mock_job
        doc_result = MagicMock()
        doc_result.scalar_one.return_value = mock_document
        mock_db.execute = AsyncMock(side_effect=[job_result, doc_result])
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        mock_storage = AsyncMock()
        mock_storage.download = AsyncMock(return_value=b"%PDF-1.4 test")

        patches = [
            patch("app.dependencies.get_storage", AsyncMock(return_value=mock_storage)),
            patch("app.utils.mime.detect_mime_type", return_value="application/pdf"),
            patch(
                "app.services.ingestion.ingest",
                return_value=ExtractedContent(
                    text="Invoice #12345\nTotal: $500.00", metadata={}, page_count=1
                ),
            ),
            patch(
                "app.services.classifier.classify",
                new_callable=AsyncMock,
                return_value=ClassificationResult(
                    doc_type="invoice", confidence=0.95, reasoning="Invoice detected"
                ),
            ),
            patch(
                "app.services.claude_extractor.extract",
                new_callable=AsyncMock,
                return_value=ExtractionResult(
                    data={"invoice_number": "12345", "total_amount": 500.00},
                    confidence=0.92,
                ),
            ),
            patch(
                "app.services.validator.validate",
                return_value=ValidationResult(
                    is_valid=True, errors=[], needs_review=False, confidence=0.92
                ),
            ),
            patch("app.services.embedder.embed", new_callable=AsyncMock, return_value=[0.1] * 768),
            patch("worker.events.publish_event", new_callable=AsyncMock),
        ]

        started = [p.start() for p in patches]

        return mock_db, patches, started

    @pytest.mark.asyncio
    async def test_pipeline_completes_successfully(
        self, job_id, mock_redis, pipeline_mocks
    ):
        mock_db, patches, _ = pipeline_mocks
        try:
            from worker.tasks import _process
            result = await _process(mock_db, mock_redis, job_id)

            assert result["status"] == "completed"
            assert "record_id" in result
            assert result["document_type"] == "invoice"
        finally:
            for p in patches:
                p.stop()

    @pytest.mark.asyncio
    async def test_job_not_found_raises(self, mock_redis, pipeline_mocks):
        mock_db, patches, _ = pipeline_mocks
        try:
            # Override db to return None for job
            no_job_result = MagicMock()
            no_job_result.scalar_one_or_none.return_value = None
            mock_db.execute = AsyncMock(return_value=no_job_result)

            from worker.tasks import _process
            with pytest.raises(ValueError, match="not found"):
                await _process(mock_db, mock_redis, "nonexistent-id")
        finally:
            for p in patches:
                p.stop()

    @pytest.mark.asyncio
    async def test_webhook_called_when_configured(
        self, job_id, mock_job, mock_redis, pipeline_mocks
    ):
        mock_db, patches, _ = pipeline_mocks
        mock_job.webhook_url = "https://example.com/hook"
        mock_job.webhook_secret_encrypted = None

        webhook_patch = patch(
            "app.services.webhook_sender.send_webhook", new_callable=AsyncMock
        )

        try:
            mock_webhook = webhook_patch.start()
            from worker.tasks import _process
            await _process(mock_db, mock_redis, job_id)

            mock_webhook.assert_called_once()
            call_args = mock_webhook.call_args
            assert call_args[0][0] == "https://example.com/hook"
            assert call_args[0][1]["event"] == "job.completed"
        finally:
            webhook_patch.stop()
            for p in patches:
                p.stop()

    @pytest.mark.asyncio
    async def test_validation_errors_stored(
        self, job_id, mock_job, mock_redis, pipeline_mocks
    ):
        from app.services.validator import ErrorSeverity, ValidationError, ValidationResult

        mock_db, patches, started = pipeline_mocks

        # Override validate to return errors
        validate_patch = patch(
            "app.services.validator.validate",
            return_value=ValidationResult(
                is_valid=False,
                errors=[
                    ValidationError(
                        field_path="total_amount",
                        error_type="CALCULATION_MISMATCH",
                        message="Total doesn't match",
                        severity=ErrorSeverity.ERROR,
                    ),
                ],
                needs_review=True,
                confidence=0.5,
            ),
        )

        try:
            validate_patch.start()
            from worker.tasks import _process
            result = await _process(mock_db, mock_redis, job_id)

            assert result["status"] == "completed"
            # db.add called for: record + audit_log + validation_error + embedding = 4
            assert mock_db.add.call_count == 4
        finally:
            validate_patch.stop()
            for p in patches:
                p.stop()


class TestFailJob:
    @pytest.mark.asyncio
    async def test_fail_job_updates_status(self, job_id, mock_redis):
        """Test _fail_job sets status to FAILED and publishes event."""
        mock_job = MagicMock()
        mock_job.status = "processing"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_job
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("worker.events.publish_event", new_callable=AsyncMock) as mock_publish:
            from worker.tasks import _fail_job
            await _fail_job(mock_db, mock_redis, job_id, "Something broke")

        assert mock_job.status == "failed"
        assert mock_job.error_message == "Something broke"
        mock_db.commit.assert_called_once()
        mock_publish.assert_called_once()
