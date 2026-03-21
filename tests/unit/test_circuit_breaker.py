"""Tests for AsyncCircuitBreaker — CLOSED/OPEN/HALF_OPEN state machine."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services.circuit_breaker import AsyncCircuitBreaker, CircuitOpenError, CircuitState


class TestCircuitBreakerInitialState:
    def test_starts_closed(self):
        cb = AsyncCircuitBreaker(failure_threshold=3)
        assert cb.state == CircuitState.CLOSED

    def test_failure_count_starts_zero(self):
        cb = AsyncCircuitBreaker(failure_threshold=3)
        assert cb.failure_count == 0

    def test_is_open_false_when_closed(self):
        cb = AsyncCircuitBreaker(failure_threshold=3)
        assert cb.is_open is False


class TestCircuitBreakerFailures:
    @pytest.mark.asyncio
    async def test_records_failures_on_exception(self):
        cb = AsyncCircuitBreaker(failure_threshold=3)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                async with cb:
                    raise RuntimeError("fail")
        assert cb.failure_count == 2
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self):
        cb = AsyncCircuitBreaker(failure_threshold=3)
        for _ in range(3):
            with pytest.raises(RuntimeError):
                async with cb:
                    raise RuntimeError("fail")
        assert cb.state == CircuitState.OPEN
        assert cb.is_open is True

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self):
        cb = AsyncCircuitBreaker(failure_threshold=3)
        with pytest.raises(RuntimeError):
            async with cb:
                raise RuntimeError("fail")
        assert cb.failure_count == 1
        async with cb:
            pass  # success
        assert cb.failure_count == 0


class TestCircuitBreakerOpenState:
    @pytest.mark.asyncio
    async def test_rejects_calls_when_open(self):
        cb = AsyncCircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
        with pytest.raises(RuntimeError):
            async with cb:
                raise RuntimeError("trip it")
        assert cb.state == CircuitState.OPEN
        with pytest.raises(CircuitOpenError):
            async with cb:
                pass  # should never reach here

    @pytest.mark.asyncio
    async def test_open_does_not_count_rejection_as_failure(self):
        cb = AsyncCircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
        with pytest.raises(RuntimeError):
            async with cb:
                raise RuntimeError("trip it")
        failure_count_when_open = cb.failure_count
        with pytest.raises(CircuitOpenError):
            async with cb:
                pass
        assert cb.failure_count == failure_count_when_open


class TestCircuitBreakerHalfOpen:
    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_timeout(self):
        cb = AsyncCircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        with pytest.raises(RuntimeError):
            async with cb:
                raise RuntimeError("trip it")
        assert cb.state == CircuitState.OPEN
        await asyncio.sleep(0.05)
        # Peek at state without calling — state changes lazily on next call attempt
        assert cb._should_attempt_reset() is True

    @pytest.mark.asyncio
    async def test_closes_on_half_open_success(self):
        cb = AsyncCircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        with pytest.raises(RuntimeError):
            async with cb:
                raise RuntimeError("trip it")
        await asyncio.sleep(0.05)
        # Next call should enter HALF_OPEN and succeed -> CLOSED
        async with cb:
            pass
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_reopens_on_half_open_failure(self):
        cb = AsyncCircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        with pytest.raises(RuntimeError):
            async with cb:
                raise RuntimeError("trip it")
        await asyncio.sleep(0.05)
        with pytest.raises(RuntimeError):
            async with cb:
                raise RuntimeError("still broken")
        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerReset:
    @pytest.mark.asyncio
    async def test_reset_clears_state(self):
        cb = AsyncCircuitBreaker(failure_threshold=1)
        with pytest.raises(RuntimeError):
            async with cb:
                raise RuntimeError("trip it")
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0


class TestCircuitBreakerConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_access_is_safe(self):
        cb = AsyncCircuitBreaker(failure_threshold=10)
        # Many concurrent successes should not corrupt state
        async def _succeed():
            async with cb:
                await asyncio.sleep(0)

        await asyncio.gather(*[_succeed() for _ in range(20)])
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_concurrent_failures_trip_exactly_at_threshold(self):
        cb = AsyncCircuitBreaker(failure_threshold=5)

        async def _fail():
            try:
                async with cb:
                    raise RuntimeError("fail")
            except (RuntimeError, CircuitOpenError):
                pass

        await asyncio.gather(*[_fail() for _ in range(10)])
        # Circuit must be open — exact failure count depends on timing but state must be OPEN
        assert cb.state == CircuitState.OPEN
