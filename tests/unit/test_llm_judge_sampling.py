"""Unit tests for worker/judge_tasks.py — pure-python logic, no API calls."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worker.judge_tasks import _score_to_int, judge_extraction_sample

# ---------------------------------------------------------------------------
# _score_to_int
# ---------------------------------------------------------------------------


def test_score_to_int_maps_zero_to_one() -> None:
    assert _score_to_int(0.0) == 1


def test_score_to_int_maps_one_to_five() -> None:
    assert _score_to_int(1.0) == 5


def test_score_to_int_maps_midpoint() -> None:
    # 0.5 * 4 + 1 = 3
    assert _score_to_int(0.5) == 3


def test_score_to_int_clamps_above_one() -> None:
    assert _score_to_int(1.5) == 5


def test_score_to_int_clamps_below_zero() -> None:
    assert _score_to_int(-0.5) == 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_judge_result(score: float) -> MagicMock:
    r = MagicMock()
    r.score = score
    return r


def _make_mock_db(fake_job: object, fake_record: object) -> MagicMock:
    mock_db = MagicMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)
    mock_db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=fake_job)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=fake_record)),
        ]
    )
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    return mock_db


# ---------------------------------------------------------------------------
# judge_extraction_sample
# ---------------------------------------------------------------------------


async def test_judge_sample_writes_eval_log() -> None:
    """Happy path: judge evaluates 4 dimensions and EvalLog is written."""
    fake_job = MagicMock()
    fake_job.id = "job-001"

    fake_record = MagicMock()
    fake_record.job_id = "job-001"
    fake_record.raw_text = "Invoice from Acme Corp totalling $500"
    fake_record.extracted_data = {"vendor": "Acme Corp", "total": 500}
    fake_record.document_type = "invoice"

    mock_db = _make_mock_db(fake_job, fake_record)

    mock_judge = MagicMock()
    mock_judge.evaluate = AsyncMock(return_value=_make_judge_result(0.9))

    with (
        patch("worker.judge_tasks.AsyncSessionLocal", return_value=mock_db),
        patch("worker.judge_tasks.LLMJudge", return_value=mock_judge),
    ):
        await judge_extraction_sample({}, "job-001")

    # judge.evaluate called 4 times (once per dimension)
    assert mock_judge.evaluate.call_count == 4
    # EvalLog row added to DB
    mock_db.add.assert_called_once()
    eval_log_arg = mock_db.add.call_args[0][0]
    assert eval_log_arg.job_id == "job-001"
    # score 0.9 -> _score_to_int(0.9) = round(0.9*4)+1 = 5
    assert eval_log_arg.completeness == 5
    assert eval_log_arg.field_accuracy == 5
    assert eval_log_arg.hallucination_absence == 5
    assert eval_log_arg.format_compliance == 5
    # composite = (5+5+5+5) / (5*4) = 1.0
    assert eval_log_arg.composite == pytest.approx(1.0, abs=0.001)
    mock_db.commit.assert_called_once()


async def test_judge_sample_neutral_default_when_judge_returns_none() -> None:
    """When LLMJudge returns None (disabled/error), dimensions default to 3."""
    fake_job = MagicMock()
    fake_record = MagicMock()
    fake_record.job_id = "job-002"
    fake_record.raw_text = "text"
    fake_record.extracted_data = {}
    fake_record.document_type = "invoice"

    mock_db = _make_mock_db(fake_job, fake_record)

    mock_judge = MagicMock()
    mock_judge.evaluate = AsyncMock(return_value=None)

    with (
        patch("worker.judge_tasks.AsyncSessionLocal", return_value=mock_db),
        patch("worker.judge_tasks.LLMJudge", return_value=mock_judge),
    ):
        await judge_extraction_sample({}, "job-002")

    eval_log_arg = mock_db.add.call_args[0][0]
    assert eval_log_arg.completeness == 3
    assert eval_log_arg.field_accuracy == 3
    # composite = (3+3+3+3) / (5*4) = 0.6
    assert eval_log_arg.composite == pytest.approx(0.6, abs=0.001)


async def test_judge_sample_skips_when_job_not_found() -> None:
    """Returns early (no eval_log write) when the job does not exist."""
    mock_db = MagicMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    mock_db.add = MagicMock()

    with (
        patch("worker.judge_tasks.AsyncSessionLocal", return_value=mock_db),
        patch("worker.judge_tasks.LLMJudge"),
    ):
        await judge_extraction_sample({}, "missing-job")

    mock_db.add.assert_not_called()


async def test_judge_sample_swallows_exception() -> None:
    """Exceptions inside the task are caught and not re-raised."""
    with patch("worker.judge_tasks.AsyncSessionLocal", side_effect=RuntimeError("DB gone")):
        # Should not raise
        await judge_extraction_sample({}, "job-error")
