"""Breaker state persists across independent requests (lane B B6).

Routers built per request reset their breakers on every call, so cooldowns
never carried across jobs. The shared router registry keeps per-model breaker
state process-wide; acceptance: independent requests share cooldown.
"""
from __future__ import annotations

import anthropic
import httpx
import pytest


def _transient_error() -> Exception:
    return anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://example.com")
    )


async def test_shared_router_instance_across_calls():
    from app.services.model_router import get_shared_router

    assert get_shared_router("extract") is get_shared_router("extract")
    assert get_shared_router("classify") is get_shared_router("classify")
    assert get_shared_router("classify") is not get_shared_router("extract")


async def test_breaker_cooldown_shared_across_independent_requests():
    """An open breaker rejects later, independent requests: one cooldown."""
    from app.services.model_router import AllModelsUnavailableError, get_shared_router

    router = get_shared_router("extract")
    breaker = router.get_circuit_breaker("test-model-shared")
    breaker.failure_threshold = 1

    async def boom(model: str):
        raise _transient_error()

    with pytest.raises(AllModelsUnavailableError):
        await router.call_with_fallback("extract", ["test-model-shared"], boom)

    assert breaker.is_open

    # A brand-new "request" resolves the same shared router and is rejected by
    # the same open breaker — cooldown persists across requests.
    second = get_shared_router("extract")
    with pytest.raises(AllModelsUnavailableError):
        await second.call_with_fallback("extract", ["test-model-shared"], boom)
