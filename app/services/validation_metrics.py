"""Thread-safe validation statistics tracker."""
from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass
class ValidationSnapshot:
    total: int
    passed: int
    failed: int
    pass_rate: float


class ValidationStats:
    """Thread-safe counters for validation pass/fail tracking."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total = 0
        self._passed = 0
        self._failed = 0

    def record(self, passed: bool) -> None:
        """Record a validation result."""
        with self._lock:
            self._total += 1
            if passed:
                self._passed += 1
            else:
                self._failed += 1

    @property
    def pass_rate(self) -> float:
        """Return pass rate as float 0.0-1.0."""
        with self._lock:
            if self._total == 0:
                return 0.0
            return self._passed / self._total

    def snapshot(self) -> ValidationSnapshot:
        """Return immutable snapshot of current stats."""
        with self._lock:
            return ValidationSnapshot(
                total=self._total,
                passed=self._passed,
                failed=self._failed,
                pass_rate=self._passed / self._total if self._total > 0 else 0.0,
            )

    def reset(self) -> None:
        """Reset all counters (for testing)."""
        with self._lock:
            self._total = 0
            self._passed = 0
            self._failed = 0


# Module-level singleton
validation_stats = ValidationStats()
