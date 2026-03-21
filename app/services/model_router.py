"""Model fallback router with per-model circuit breakers.

Wraps LLM API calls with a fallback chain: if the primary model fails,
the router tries the next model in the chain. Each model has its own
circuit breaker that opens after repeated failures, preventing wasted
calls to a degraded provider.

Usage:
    router = ModelRouter()

    result, model_used = await router.call_with_fallback(
        operation="extract",
        chain=["claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
        call_fn=lambda model: client.messages.create(model=model, ...),
    )
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import anthropic

from app.services.circuit_breaker import AsyncCircuitBreaker, CircuitOpenError

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Exceptions that indicate a model provider is temporarily unavailable.
# 4xx client errors (BadRequestError, AuthenticationError, etc.) are NOT
# transient — the same bad request will fail on any model, so we don't retry.
def _is_transient(e: Exception) -> bool:
    if isinstance(e, anthropic.RateLimitError):
        return True
    if isinstance(e, anthropic.APIConnectionError):
        return True
    if isinstance(e, anthropic.APITimeoutError):
        return True
    if isinstance(e, anthropic.APIStatusError):
        # Only retry on server errors (5xx), not client errors (4xx)
        return e.status_code >= 500
    return False


class AllModelsUnavailableError(Exception):
    """Raised when every model in the fallback chain fails or is circuit-open."""

    def __init__(self, operation: str, chain: list[str]) -> None:
        models = ", ".join(chain) if chain else "(empty chain)"
        super().__init__(f"All models unavailable for '{operation}': [{models}]")
        self.operation = operation
        self.chain = chain


class ModelRouter:
    """Routes LLM calls through a configurable fallback chain.

    Args:
        failure_threshold: Failures before a model's circuit opens.
        recovery_timeout: Seconds before a OPEN circuit attempts recovery.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._breakers: dict[str, AsyncCircuitBreaker] = {}

    def get_circuit_breaker(self, model: str) -> AsyncCircuitBreaker:
        """Return the circuit breaker for a model, creating if needed."""
        if model not in self._breakers:
            self._breakers[model] = AsyncCircuitBreaker(
                failure_threshold=self.failure_threshold,
                recovery_timeout=self.recovery_timeout,
            )
        return self._breakers[model]

    async def call_with_fallback(
        self,
        operation: str,
        chain: list[str],
        call_fn: Callable[[str], Awaitable[T]],
    ) -> tuple[T, str]:
        """Call the first available model in the chain, falling back on failure.

        Args:
            operation: Human-readable name (for logging and error messages).
            chain: Ordered list of model names to try.
            call_fn: Async callable that takes a model name and returns a result.

        Returns:
            (result, model_name) tuple identifying which model succeeded.

        Raises:
            AllModelsUnavailableError: If all models fail or are circuit-open.
        """
        if not chain:
            raise AllModelsUnavailableError(operation, chain)

        last_error: Exception | None = None

        for model in chain:
            cb = self.get_circuit_breaker(model)

            if cb.is_open:
                logger.debug("Skipping %s for '%s' — circuit OPEN", model, operation)
                continue

            try:
                async with cb:
                    result = await call_fn(model)
                logger.debug("'%s' succeeded with %s", operation, model)
                return result, model

            except CircuitOpenError as e:
                logger.debug("Skipping %s for '%s' — %s", model, operation, e)
                last_error = e
                continue

            except Exception as e:
                if not _is_transient(e):
                    raise
                logger.warning(
                    "Model %s failed for '%s' (%s: %s), trying next",
                    model,
                    operation,
                    type(e).__name__,
                    e,
                )
                last_error = e
                continue

        raise AllModelsUnavailableError(operation, chain) from last_error
