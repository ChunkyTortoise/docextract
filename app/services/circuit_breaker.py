"""Async circuit breaker with CLOSED / OPEN / HALF_OPEN state machine.

Protects LLM API calls from cascading failures by temporarily stopping
calls to a failing provider and attempting recovery after a timeout.

Usage:
    cb = AsyncCircuitBreaker(failure_threshold=5, recovery_timeout=60.0)

    async with cb:
        response = await anthropic_client.messages.create(...)
"""
from __future__ import annotations

import asyncio
import time
from enum import Enum
from types import TracebackType


class CircuitState(Enum):
    CLOSED = "closed"       # Healthy — calls pass through
    OPEN = "open"           # Failing — calls rejected immediately
    HALF_OPEN = "half_open" # Recovering — one probe call allowed


class CircuitOpenError(Exception):
    """Raised when a call is attempted while the circuit is OPEN."""

    def __init__(self, message: str = "Circuit breaker is OPEN") -> None:
        super().__init__(message)


class AsyncCircuitBreaker:
    """Async context-manager circuit breaker for a single upstream dependency.

    Args:
        failure_threshold: Number of consecutive failures before opening.
        recovery_timeout: Seconds to wait before transitioning OPEN -> HALF_OPEN.
        half_open_max_calls: Max probe calls allowed in HALF_OPEN state.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 1,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._opened_at: float | None = None
        self._half_open_in_flight: int = 0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def is_open(self) -> bool:
        return self._state == CircuitState.OPEN and not self._should_attempt_reset()

    def _should_attempt_reset(self) -> bool:
        """True when enough time has passed since opening to try a probe."""
        if self._state != CircuitState.OPEN:
            return False
        return self._opened_at is not None and (time.monotonic() - self._opened_at) >= self.recovery_timeout

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> AsyncCircuitBreaker:
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_in_flight = 0
                else:
                    raise CircuitOpenError(
                        f"Circuit OPEN — retry after {self.recovery_timeout:.0f}s"
                    )

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_in_flight >= self.half_open_max_calls:
                    raise CircuitOpenError("Circuit HALF_OPEN — probe already in flight")
                self._half_open_in_flight += 1

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        async with self._lock:
            if exc_type is None:
                # Success
                self._failure_count = 0
                if self._state == CircuitState.HALF_OPEN:
                    self._half_open_in_flight = max(0, self._half_open_in_flight - 1)
                self._state = CircuitState.CLOSED
            elif exc_type is CircuitOpenError:
                # Rejection — not a real failure, don't count
                pass
            else:
                # Real failure
                if self._state == CircuitState.HALF_OPEN:
                    self._half_open_in_flight = max(0, self._half_open_in_flight - 1)
                    self._state = CircuitState.OPEN
                    self._opened_at = time.monotonic()
                else:
                    self._failure_count += 1
                    if self._failure_count >= self.failure_threshold:
                        self._state = CircuitState.OPEN
                        self._opened_at = time.monotonic()
        return False  # Do not suppress the exception

    # ------------------------------------------------------------------
    # Manual reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset to CLOSED state (for testing or manual recovery)."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at = None
        self._half_open_in_flight = 0
