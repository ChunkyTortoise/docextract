"""Terminal jobs must survive duplicate delivery and late processing failures.

Database and event boundaries are controlled here; PostgreSQL lock waiting is
covered separately in test_pg_redelivery.py.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import PendingRollbackError


@pytest.mark.parametrize("status", ["completed", "needs_review", "cancelled"])
async def test_terminal_redelivery_returns_existing_record_without_processing(status):
    from worker.tasks import _process

    job_id = uuid.uuid4()
    job = SimpleNamespace(
        id=job_id, document_id=uuid.uuid4(), status=status, document_type_detected="invoice",
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = job
    record_result = MagicMock()
    record_result.scalars.return_value.first.return_value = SimpleNamespace(id="record-1")
    db = AsyncMock()
    db.execute.side_effect = [result, record_result]
    with patch("app.dependencies.get_storage", new_callable=AsyncMock) as storage:
        storage.side_effect = AssertionError("terminal redelivery must not read storage")
        outcome = await _process(db, AsyncMock(), str(job_id))

    assert outcome == {
        "status": "duplicate_ignored", "record_id": "record-1", "document_type": "invoice",
    }
    assert job.status == status
    query = db.execute.call_args_list[0].args[0]
    assert "FOR UPDATE" in str(query.compile(dialect=postgresql.dialect()))
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("status", ["completed", "needs_review", "cancelled"])
async def test_late_failure_preserves_terminal_status_and_emits_no_failed_event(status):
    from worker.tasks import _fail_job

    job = SimpleNamespace(status=status, error_message="", completed_at="original-time")
    db = AsyncMock()
    db.execute.return_value.scalar_one_or_none = MagicMock(return_value=job)
    with patch("worker.events.publish_event", new_callable=AsyncMock) as publish:
        await _fail_job(db, AsyncMock(), str(uuid.uuid4()), "late redelivery failure")

    assert vars(job) == {
        "status": status, "error_message": "", "completed_at": "original-time",
    }
    db.rollback.assert_awaited_once()
    query = db.execute.call_args.args[0]
    assert "FOR UPDATE" in str(query.compile(dialect=postgresql.dialect()))
    db.commit.assert_not_awaited()
    publish.assert_not_awaited()


async def test_failed_transaction_is_rolled_back_before_terminal_status_is_reloaded():
    """SQL errors poison the transaction; rollback also expires stale ORM state."""
    from worker.tasks import _fail_job

    job = SimpleNamespace(status="completed")
    transaction = SimpleNamespace(failed=True)
    db = AsyncMock()

    async def rollback():
        transaction.failed = False

    async def execute(query):
        if transaction.failed:
            raise PendingRollbackError("transaction must be rolled back before reuse")
        result = MagicMock()
        result.scalar_one_or_none.return_value = job
        return result

    db.rollback.side_effect = rollback
    db.execute.side_effect = execute
    with patch("worker.events.publish_event", new_callable=AsyncMock) as publish:
        await _fail_job(db, AsyncMock(), str(uuid.uuid4()), "late SQL error")

    assert not transaction.failed
    assert job.status == "completed"
    db.commit.assert_not_awaited()
    publish.assert_not_awaited()


@pytest.mark.parametrize("failure", ["rollback", "read", "commit", "missing"])
async def test_unconfirmed_failure_state_emits_no_failed_event(failure):
    """A failed event requires a durable status change, not just a processing error."""
    from worker.tasks import _fail_job

    db = AsyncMock()
    job = SimpleNamespace(status="extracting_data")
    db.execute.return_value.scalar_one_or_none = MagicMock(return_value=job)
    if failure == "rollback":
        db.rollback.side_effect = RuntimeError("rollback unavailable")
    elif failure == "read":
        db.execute.side_effect = RuntimeError("status read unavailable")
    elif failure == "commit":
        db.commit.side_effect = RuntimeError("status commit unavailable")
    else:
        db.execute.return_value.scalar_one_or_none.return_value = None

    with patch("worker.events.publish_event", new_callable=AsyncMock) as publish:
        await _fail_job(db, AsyncMock(), str(uuid.uuid4()), "processing error")

    publish.assert_not_awaited()
