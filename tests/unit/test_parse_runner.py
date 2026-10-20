"""Killable-subprocess parse runner proofs (R-parser-subprocess).

Child targets are resolved by dotted path inside the spawned process, so the
fixtures below are module-level functions importable across the spawn
boundary.
"""
from __future__ import annotations

import os
import time

import pytest

from app.services.parse_runner import (
    ParseSubprocessError,
    _parse_child,
    run_parse_subprocess,
)
from app.services.pdf_extractor import ExtractedContent


def _ok_ingest(file_bytes, mime_type, filename, deadline=None):
    return ExtractedContent(
        text=f"{filename}:{len(file_bytes)}",
        metadata={"mime": mime_type, "deadline": deadline},
        page_count=2,
    )


def _slow_ingest(file_bytes, mime_type, filename, deadline=None):
    time.sleep(30)
    return ExtractedContent(text="late")


def _failing_ingest(file_bytes, mime_type, filename, deadline=None):
    raise ValueError("boom: corrupt input")


def _crashing_ingest(file_bytes, mime_type, filename, deadline=None):
    os._exit(3)


_OK = "tests.unit.test_parse_runner:_ok_ingest"
_SLOW = "tests.unit.test_parse_runner:_slow_ingest"
_FAILING = "tests.unit.test_parse_runner:_failing_ingest"
_CRASHING = "tests.unit.test_parse_runner:_crashing_ingest"


class TestRunParseSubprocess:
    def test_result_round_trips_from_child(self):
        result = run_parse_subprocess(
            b"pdf-bytes", "application/pdf", "doc.pdf", target=_OK
        )
        assert result == ExtractedContent(
            text="doc.pdf:9",
            metadata={"mime": "application/pdf", "deadline": None},
            page_count=2,
        )

    def test_deadline_budget_forwarded_to_target(self):
        deadline = time.monotonic() + 60.0
        result = run_parse_subprocess(
            b"pdf-bytes", "application/pdf", "doc.pdf", deadline=deadline, target=_OK
        )
        # The child must see the parent's absolute deadline exactly; any
        # re-anchoring in the child would push it later by spawn latency.
        assert result.metadata["deadline"] == deadline

    def test_child_does_not_reanchor_deadline_after_spawn_latency(self):
        # Simulate spawn/import latency between the parent computing the
        # deadline and the child starting; the forwarded deadline must not move.
        class _Conn:
            sent = None

            def send(self, payload):
                self.sent = payload

            def close(self):
                pass

        deadline = time.monotonic() + 5.0
        time.sleep(0.2)
        conn = _Conn()
        _parse_child(conn, _OK, b"x", "application/pdf", "doc.pdf", deadline)
        status, result = conn.sent
        assert status == "ok"
        assert result.metadata["deadline"] == deadline

    def test_child_exception_propagates_by_type(self):
        with pytest.raises(ValueError, match="boom"):
            run_parse_subprocess(b"x", "application/pdf", "doc.pdf", target=_FAILING)

    def test_uncooperative_parser_is_killed_at_budget(self):
        # The target never checks any deadline; only the parent kill stops it.
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            run_parse_subprocess(
                b"x",
                "application/pdf",
                "doc.pdf",
                deadline=time.monotonic() + 0.5,
                target=_SLOW,
            )
        assert time.monotonic() - start < 15.0

    def test_exhausted_budget_raises_timeout(self):
        with pytest.raises(TimeoutError):
            run_parse_subprocess(
                b"x",
                "application/pdf",
                "doc.pdf",
                deadline=time.monotonic() - 1.0,
                target=_SLOW,
            )

    def test_abnormal_child_exit_without_result_is_reported(self):
        with pytest.raises(ParseSubprocessError, match="exited with code 3"):
            run_parse_subprocess(b"x", "application/pdf", "doc.pdf", target=_CRASHING)

    def test_no_deadline_runs_to_completion(self):
        result = run_parse_subprocess(
            b"pdf-bytes", "application/pdf", "doc.pdf", target=_OK
        )
        assert result.metadata["deadline"] is None
