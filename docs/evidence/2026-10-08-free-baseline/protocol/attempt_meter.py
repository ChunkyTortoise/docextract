"""Mock-only transport preparation for per-attempt budget and usage accounting."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

LOG = logging.getLogger(__name__)


class MeterStop(RuntimeError):
    """A request must not be sent after a budget or accounting failure."""


@dataclass(frozen=True)
class ModelPolicy:
    input_limit: int
    output_limit: int
    input_rate: Decimal
    output_rate: Decimal
    cache_read_rate: Decimal
    cache_5m_rate: Decimal
    cache_1h_rate: Decimal
    price_source: str
    price_date: str

    def __post_init__(self) -> None:
        for value in (self.input_limit, self.output_limit):
            if type(value) is not int or value <= 0:
                raise ValueError("Positive integer model token limits required")
        for value in self.rates:
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError("Explicit finite nonnegative Decimal rates required")
        if not self.price_source or not self.price_date:
            raise ValueError("Pricing provenance required")

    @property
    def rates(self) -> tuple[Decimal, ...]:
        return (
            self.input_rate,
            self.output_rate,
            self.cache_read_rate,
            self.cache_5m_rate,
            self.cache_1h_rate,
        )

    def bound(self, output_tokens: int) -> Decimal:
        # Bound every input token at the most expensive input/cache category.
        return (
            self.input_limit
            * max(
                self.input_rate,
                self.cache_read_rate,
                self.cache_5m_rate,
                self.cache_1h_rate,
            )
            + output_tokens * self.output_rate
        )

    def cost(self, usage: dict[str, Any], output_cap: int) -> Decimal:
        if set(usage) - {
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "cache_creation",
        }:
            raise MeterStop("Unsupported billing dimension")

        def tokens(value: Any) -> int:
            if type(value) is not int or value < 0:
                raise MeterStop("Missing or invalid usage tokens")
            return value

        uncached = tokens(usage.get("input_tokens"))
        output = tokens(usage.get("output_tokens"))
        read = tokens(usage.get("cache_read_input_tokens", 0))
        created = tokens(usage.get("cache_creation_input_tokens", 0))
        breakdown = usage.get("cache_creation")
        five = hour = 0
        if created:
            if not isinstance(breakdown, dict) or set(breakdown) != {
                "ephemeral_5m_input_tokens",
                "ephemeral_1h_input_tokens",
            }:
                raise MeterStop("Cache creation TTL usage missing")
            five = tokens(breakdown["ephemeral_5m_input_tokens"])
            hour = tokens(breakdown["ephemeral_1h_input_tokens"])
            if five + hour != created:
                raise MeterStop("Cache token breakdown mismatch")
        elif breakdown and any(breakdown.values()):
            raise MeterStop("Unexpected cache breakdown")
        if uncached + read + created > self.input_limit or output > output_cap:
            raise MeterStop("Usage exceeded the pre-send token bound")
        return (
            uncached * self.input_rate
            + output * self.output_rate
            + read * self.cache_read_rate
            + five * self.cache_5m_rate
            + hour * self.cache_1h_rate
        )


class AttemptMeter(httpx.AsyncBaseTransport):
    """Accepts MockTransport only. No production network transport is enabled.

    SDK, Instructor, correction and fallback calls sharing this transport share
    one monotonic ledger. Unknown-cost attempts retain their reservation and
    block all further sends. Only metadata/usage/hashes are retained.
    """

    def __init__(
        self,
        inner: httpx.MockTransport,
        budget: Decimal,
        models: dict[str, ModelPolicy],
    ) -> None:
        if type(inner) is not httpx.MockTransport:
            raise ValueError("Only a mock HTTP transport is permitted")
        if (
            not isinstance(budget, Decimal)
            or not budget.is_finite()
            or budget <= 0
            or not models
        ):
            raise ValueError("Explicit positive budget and model policies required")
        self.inner = inner
        self.budget = budget
        self.models = dict(models)
        self.spent = Decimal("0")
        self.reserved = Decimal("0")
        self.blocked: str | None = None
        self.case_id: str | None = None
        self.operation: str | None = None
        self.rows: list[dict[str, Any]] = []
        self.lock = asyncio.Lock()

    def set_context(self, case_id: str, operation: str) -> None:
        if self.lock.locked() or not case_id or not operation:
            raise MeterStop("Case context is absent or a request is active")
        self.case_id, self.operation = case_id, operation

    def receipt(self) -> dict[str, Any]:
        return copy.deepcopy(
            dict(
                status="MOCK ONLY, PERFORMANCE UNMEASURED",
                budget_usd=str(self.budget),
                priced_subtotal_usd=str(self.spent),
                unresolved_reservation_usd=str(self.reserved),
                cost_usd=str(self.spent) if not self.reserved else None,
                blocked=self.blocked,
                attempts=self.rows,
            )
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        async with self.lock:
            if self.blocked:
                raise MeterStop(self.blocked)
            if not self.case_id or not self.operation:
                raise MeterStop("Set case and operation before sending")
            if (
                request.method != "POST"
                or str(request.url) != "https://api.anthropic.com/v1/messages"
            ):
                raise MeterStop("Only the declared Messages endpoint is permitted")
            payload = json.loads(await request.aread())
            if payload.get("stream") or payload.get("service_tier") not in (
                None,
                "standard",
            ):
                raise MeterStop("Streaming and nonstandard tiers are unsupported")
            if set(payload) - {
                "model",
                "max_tokens",
                "messages",
                "system",
                "tools",
                "tool_choice",
                "temperature",
                "top_p",
                "top_k",
                "stop_sequences",
                "metadata",
                "stream",
                "service_tier",
            }:
                raise MeterStop("Unsupported request pricing dimension")
            model = payload.get("model")
            policy = self.models.get(model)
            cap = payload.get("max_tokens")
            if (
                not policy
                or type(cap) is not int
                or cap <= 0
                or cap > policy.output_limit
            ):
                raise MeterStop("Unapproved model or output bound")
            bound = policy.bound(cap)
            if self.spent + self.reserved + bound > self.budget:
                self.blocked = "Budget cannot reserve the next individual attempt"
                raise MeterStop(self.blocked)
            self.reserved += bound
            row = dict(
                attempt=len(self.rows) + 1,
                case_id=self.case_id,
                operation=self.operation,
                request_sha256=hashlib.sha256(request.content).hexdigest(),
                requested_model=model,
                output_cap=cap,
                reserved_usd=str(bound),
                cost_usd=None,
                price_source=policy.price_source,
                price_date=policy.price_date,
            )
            self.rows.append(row)
            start = time.perf_counter()
            try:
                response = await self.inner.handle_async_request(request)
                await response.aread()
                row["http_status"] = response.status_code
                body = response.json()
                row["returned_model"] = body.get("model")
                row["usage"] = body.get("usage")
                if (
                    response.status_code != 200
                    or body.get("model") != model
                    or not isinstance(body.get("usage"), dict)
                ):
                    raise MeterStop("Response cost or returned model is unverified")
                cost = policy.cost(body["usage"], cap)
                if cost > bound:
                    raise MeterStop("Cost exceeded reserved bound")
                self.spent += cost
                self.reserved -= bound
                row["cost_usd"] = str(cost)
                return response
            except BaseException as exc:
                self.blocked = "Unresolved attempt, further requests blocked"
                row["error_type"] = type(exc).__name__
                LOG.warning(
                    "Meter halted after case %s attempt %s: %s",
                    self.case_id,
                    row["attempt"],
                    type(exc).__name__,
                )
                raise
            finally:
                row["latency_ms"] = (time.perf_counter() - start) * 1000

    async def aclose(self) -> None:
        await self.inner.aclose()


def price_attempts(
    rows: list[dict[str, Any]], allowed: list[str]
) -> tuple[Decimal, bool]:
    """Aggregate individually verified mock transport receipts for the runner."""
    total = Decimal("0")
    complete = bool(rows)
    for row in rows:
        raw = row.get("cost_usd")
        if raw is None or row.get("returned_model") not in allowed:
            complete = False
            continue
        value = Decimal(raw)
        if not value.is_finite() or value < 0:
            complete = False
            continue
        total += value
    return total, complete
