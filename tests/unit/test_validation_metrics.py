"""Tests for validation_metrics service."""
from __future__ import annotations

import pytest
from app.services.validation_metrics import ValidationStats, ValidationSnapshot


class TestValidationStats:
    def test_initial_pass_rate_zero(self):
        stats = ValidationStats()
        assert stats.pass_rate == 0.0

    def test_record_passed(self):
        stats = ValidationStats()
        stats.record(True)
        assert stats.pass_rate == 1.0

    def test_record_failed(self):
        stats = ValidationStats()
        stats.record(False)
        assert stats.pass_rate == 0.0

    def test_mixed_pass_rate(self):
        stats = ValidationStats()
        stats.record(True)
        stats.record(True)
        stats.record(False)
        assert stats.pass_rate == pytest.approx(2 / 3)

    def test_snapshot_returns_snapshot(self):
        stats = ValidationStats()
        stats.record(True)
        snap = stats.snapshot()
        assert isinstance(snap, ValidationSnapshot)
        assert snap.total == 1
        assert snap.passed == 1
        assert snap.failed == 0

    def test_reset_clears_counters(self):
        stats = ValidationStats()
        stats.record(True)
        stats.record(False)
        stats.reset()
        assert stats.pass_rate == 0.0
        snap = stats.snapshot()
        assert snap.total == 0

    def test_singleton_exists(self):
        from app.services.validation_metrics import validation_stats
        assert isinstance(validation_stats, ValidationStats)

    def test_snapshot_pass_rate_matches_property(self):
        stats = ValidationStats()
        stats.record(True)
        stats.record(False)
        snap = stats.snapshot()
        assert snap.pass_rate == stats.pass_rate
