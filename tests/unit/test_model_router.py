"""Tests for ModelRouter — fallback chain with circuit breaker integration."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from anthropic import APIStatusError, RateLimitError

from app.services.circuit_breaker import AsyncCircuitBreaker, CircuitOpenError
from app.services.model_router import AllModelsUnavailableError, ModelRouter


def _rate_limit_error() -> RateLimitError:
    """Create a minimal RateLimitError for testing."""
    mock_response = MagicMock()
    mock_response.status_code = 429
    return RateLimitError("rate limit", response=mock_response, body={})


class TestModelRouterPrimarySuccess:
    @pytest.mark.asyncio
    async def test_calls_primary_model_first(self):
        router = ModelRouter()
        call_fn = AsyncMock(return_value="result")
        result, model = await router.call_with_fallback(
            operation="extract",
            chain=["sonnet", "haiku"],
            call_fn=call_fn,
        )
        assert result == "result"
        assert model == "sonnet"
        call_fn.assert_awaited_once_with("sonnet")

    @pytest.mark.asyncio
    async def test_returns_result_and_model_name(self):
        router = ModelRouter()
        call_fn = AsyncMock(return_value={"data": 42})
        result, model = await router.call_with_fallback("op", ["m1"], call_fn)
        assert result == {"data": 42}
        assert model == "m1"


class TestModelRouterFallback:
    @pytest.mark.asyncio
    async def test_falls_back_on_rate_limit_error(self):
        router = ModelRouter()
        call_fn = AsyncMock(side_effect=[_rate_limit_error(), "fallback_result"])
        result, model = await router.call_with_fallback("extract", ["sonnet", "haiku"], call_fn)
        assert result == "fallback_result"
        assert model == "haiku"

    @pytest.mark.asyncio
    async def test_falls_back_on_api_error(self):
        router = ModelRouter()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        api_err = APIStatusError("server error", response=mock_resp, body={})
        call_fn = AsyncMock(side_effect=[api_err, "ok"])
        result, model = await router.call_with_fallback("classify", ["primary", "backup"], call_fn)
        assert result == "ok"
        assert model == "backup"

    @pytest.mark.asyncio
    async def test_skips_open_circuit_breakers(self):
        router = ModelRouter()
        # Trip the circuit for "sonnet" by failing at threshold
        cb = router.get_circuit_breaker("sonnet")
        for _ in range(router.failure_threshold):
            try:
                async with cb:
                    raise RuntimeError("trip")
            except RuntimeError:
                pass

        assert cb.is_open is True

        call_fn = AsyncMock(return_value="from_haiku")
        result, model = await router.call_with_fallback("extract", ["sonnet", "haiku"], call_fn)
        assert model == "haiku"
        call_fn.assert_awaited_once_with("haiku")


class TestModelRouterAllFail:
    @pytest.mark.asyncio
    async def test_raises_when_all_models_fail(self):
        router = ModelRouter()
        call_fn = AsyncMock(side_effect=_rate_limit_error())
        with pytest.raises(AllModelsUnavailableError) as exc_info:
            await router.call_with_fallback("extract", ["m1", "m2"], call_fn)
        err = exc_info.value
        assert "m1" in str(err) or "m2" in str(err) or "extract" in str(err).lower()

    @pytest.mark.asyncio
    async def test_raises_when_chain_is_empty(self):
        router = ModelRouter()
        call_fn = AsyncMock(return_value="x")
        with pytest.raises(AllModelsUnavailableError):
            await router.call_with_fallback("op", [], call_fn)


class TestModelRouterCircuitBreakerIntegration:
    @pytest.mark.asyncio
    async def test_circuit_breaker_per_model(self):
        router = ModelRouter()
        cb1 = router.get_circuit_breaker("model-a")
        cb2 = router.get_circuit_breaker("model-b")
        assert cb1 is not cb2

    @pytest.mark.asyncio
    async def test_same_model_returns_same_breaker(self):
        router = ModelRouter()
        assert router.get_circuit_breaker("sonnet") is router.get_circuit_breaker("sonnet")

    @pytest.mark.asyncio
    async def test_failure_records_in_circuit_breaker(self):
        router = ModelRouter(failure_threshold=5)
        cb = router.get_circuit_breaker("failing-model")
        initial_failures = cb.failure_count

        call_fn = AsyncMock(side_effect=[_rate_limit_error(), "ok"])
        await router.call_with_fallback("op", ["failing-model", "backup"], call_fn)

        assert cb.failure_count > initial_failures
