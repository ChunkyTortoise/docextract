"""Job recoverability and idempotency (lane B B5 acceptance).

Fault injection before/after commit and enqueue must leave recoverable work;
repeated delivery must create one logical extraction record; processing exceptions
must not emit a completion contract. Schema-invalid results enter review, as
covered at the worker boundary in test_worker_tasks.py.
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_redis():
    return AsyncMock()


class TestRedeliveryIdempotency:
    @pytest.mark.parametrize("terminal_status", ["completed", "needs_review", "cancelled"])
    async def test_redelivered_terminal_job_is_not_reprocessed(self, mock_redis, terminal_status):
        """A re-delivered completed job returns its record, creates no second."""
        from worker.tasks import process_document

        job_id = str(uuid.uuid4())
        job = MagicMock()
        job.id = job_id
        job.status = terminal_status
        job.document_type_detected = "invoice"

        record = MagicMock()
        record.id = "record-1"

        job_result = MagicMock()
        job_result.scalar_one_or_none.return_value = job
        record_result = MagicMock()
        record_result.scalars.return_value.first.return_value = record

        with patch("worker.tasks.AsyncSessionLocal") as mock_session_cls:
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_db.execute = AsyncMock(side_effect=[job_result, record_result])

            with patch("app.dependencies.get_storage") as mock_storage:
                result = await process_document({"redis": mock_redis}, job_id)

        assert result["status"] == "duplicate_ignored"
        assert result["record_id"] == "record-1"
        mock_storage.assert_not_called()
        mock_db.commit.assert_not_called()


class TestExplicitExtractionFailure:
    async def test_extraction_exception_fails_job_without_completion(self, mock_redis):
        """An exception without an extraction result fails without a record or webhook."""
        from worker.tasks import process_document

        job_id = str(uuid.uuid4())
        job = MagicMock()
        job.id = job_id
        job.status = "extracting_data"
        job.document_id = uuid.uuid4()
        job.document_type_override = None
        job.webhook_url = "https://example.com/hook"
        job.webhook_secret_encrypted = None

        doc = MagicMock()
        doc.stored_path = "documents/x/a.pdf"
        doc.mime_type = "application/pdf"
        doc.original_filename = "a.pdf"

        job_result = MagicMock()
        job_result.scalar_one_or_none.return_value = job
        doc_result = MagicMock()
        doc_result.scalar_one.return_value = doc

        from app.services.classifier import ClassificationResult
        from app.services.pdf_extractor import ExtractedContent

        mock_storage = AsyncMock()
        mock_storage.download = AsyncMock(return_value=b"%PDF-1.4 test")

        with (
            patch("worker.tasks.AsyncSessionLocal") as mock_session_cls,
            patch("app.dependencies.get_storage", AsyncMock(return_value=mock_storage)),
            patch(
                "app.services.ingestion.ingest",
                return_value=ExtractedContent(text="doc"),
            ),
            patch(
                "app.services.classifier.classify",
                new=AsyncMock(
                    return_value=ClassificationResult(
                        doc_type="invoice", confidence=0.9, reasoning=""
                    )
                ),
            ),
            patch(
                "app.services.claude_extractor.extract",
                new=AsyncMock(side_effect=ValueError("Unparseable extraction response")),
            ),
        ):
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_db.execute = AsyncMock(
                side_effect=[job_result, doc_result, job_result]
            )

            result = await process_document({"redis": mock_redis}, job_id)

        assert result["status"] == "failed"
        assert "Unparseable extraction response" in result["error"]
        mock_db.add.assert_not_called()
        mock_redis.enqueue_job.assert_not_called()
        assert job.status == "failed"


class TestParseTimeBudget:
    async def test_slow_parsing_fails_within_time_budget(self, mock_redis, monkeypatch):
        """Async ingestion is awaited with an explicit time budget."""
        from app.config import settings
        from app.services.pdf_extractor import ExtractedContent
        from worker.tasks import process_document

        monkeypatch.setattr(settings, "parser_time_budget_seconds", 0.05)

        job_id = str(uuid.uuid4())
        job = MagicMock()
        job.id = job_id
        job.status = "extracting_text"
        job.document_id = uuid.uuid4()

        doc = MagicMock()
        doc.stored_path = "documents/x/a.pdf"
        doc.mime_type = "application/pdf"
        doc.original_filename = "a.pdf"

        job_result = MagicMock()
        job_result.scalar_one_or_none.return_value = job
        doc_result = MagicMock()
        doc_result.scalar_one.return_value = doc

        async def _slow_ingest(*args, **kwargs):
            await asyncio.sleep(0.5)
            return ExtractedContent(text="doc")

        mock_storage = AsyncMock()
        mock_storage.download = AsyncMock(return_value=b"%PDF-1.4 test")

        with (
            patch("worker.tasks.AsyncSessionLocal") as mock_session_cls,
            patch("app.dependencies.get_storage", AsyncMock(return_value=mock_storage)),
            patch("app.services.ingestion.ingest", side_effect=_slow_ingest),
        ):
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_db.execute = AsyncMock(side_effect=[job_result, doc_result])

            result = await process_document({"redis": mock_redis}, job_id)

        assert result["status"] == "failed"
        assert "time budget" in result["error"]


class TestRecoverStaleJobsReenqueues:
    async def test_recovery_reenqueues_stale_and_stranded_jobs(self, mock_redis):
        """Recovery must actually enqueue — flipping status alone strands work."""
        from worker.main import recover_stale_jobs

        stale_job = MagicMock()
        stale_job.id = uuid.uuid4()
        stale_job.status = "preprocessing"
        stranded_job = MagicMock()
        stranded_job.id = uuid.uuid4()
        stranded_job.status = "queued"

        stale_result = MagicMock()
        stale_result.scalars.return_value.all.return_value = [stale_job]
        stranded_result = MagicMock()
        stranded_result.scalars.return_value.all.return_value = [stranded_job]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[stale_result, stranded_result])

        mock_session_cls = MagicMock()
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.models.database.AsyncSessionLocal", mock_session_cls):
            await recover_stale_jobs(mock_redis)

        assert stale_job.status == "queued"
        assert mock_redis.enqueue_job.await_count == 2
        enqueued_ids = {
            call.args[1] for call in mock_redis.enqueue_job.await_args_list
        }
        assert enqueued_ids == {str(stale_job.id), str(stranded_job.id)}
        for call in mock_redis.enqueue_job.await_args_list:
            assert call.args[0] == "process_document"
            assert call.kwargs["_job_id"] == call.args[1]
