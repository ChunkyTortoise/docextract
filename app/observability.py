"""OpenTelemetry observability setup with Prometheus metrics export.

Feature-flagged behind OTEL_ENABLED=true. When disabled all emit functions
are no-ops so existing code and tests are unaffected.

Custom metrics:
    llm.call.duration_ms  — Histogram (model, operation, status)
    llm.calls.total       — Counter  (model, operation, status)
    llm.tokens.total      — Counter  (model, direction)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.config import settings

if TYPE_CHECKING:
    from fastapi import FastAPI
    from app.services.llm_tracer import TraceContext

logger = logging.getLogger(__name__)

# Module-level state — populated by setup_telemetry()
_meter: Any = None
_instruments: dict[str, Any] = {}


def setup_telemetry(app: "FastAPI") -> None:
    """Register OTel providers and mount /metrics on the FastAPI app.

    Safe to call when disabled — becomes a no-op. Import errors from missing
    packages are caught and logged so the app still starts without OTel.
    """
    global _meter, _instruments

    if not settings.otel_enabled:
        return

    try:
        from opentelemetry import metrics, trace
        from opentelemetry.exporter.prometheus import PrometheusMetricReader
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from prometheus_client import make_asgi_app
    except ImportError as e:
        logger.warning("OTel packages not installed, skipping telemetry: %s", e)
        return

    resource = Resource.create({"service.name": settings.otel_service_name})

    tracer_provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(tracer_provider)

    prometheus_reader = PrometheusMetricReader()
    meter_provider = MeterProvider(resource=resource, metric_readers=[prometheus_reader])
    metrics.set_meter_provider(meter_provider)

    _meter = metrics.get_meter("docextract", version="1.0.0")
    _instruments = {
        "duration": _meter.create_histogram(
            "llm_call_duration_ms",
            description="LLM call duration in milliseconds",
            unit="ms",
        ),
        "calls": _meter.create_counter(
            "llm_calls_total",
            description="Total LLM API calls",
        ),
        "tokens": _meter.create_counter(
            "llm_tokens_total",
            description="Total LLM tokens processed",
        ),
    }

    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

    logger.info(
        "OpenTelemetry enabled for service '%s' — /metrics exposed",
        settings.otel_service_name,
    )


def emit_llm_metrics(ctx: "TraceContext") -> None:
    """Emit OTel metrics from a completed TraceContext.

    No-op when OTel is disabled or instruments are not yet initialized.
    Called from llm_tracer.trace_llm_call in the finally block.
    """
    if not settings.otel_enabled or not _instruments:
        return

    attrs = {"model": ctx.model, "operation": ctx.operation, "status": ctx._status}
    _instruments["duration"].record(ctx.latency_ms, attributes=attrs)
    _instruments["calls"].add(1, attributes=attrs)

    if ctx._input_tokens is not None:
        _instruments["tokens"].add(
            ctx._input_tokens,
            attributes={"model": ctx.model, "direction": "input"},
        )
    if ctx._output_tokens is not None:
        _instruments["tokens"].add(
            ctx._output_tokens,
            attributes={"model": ctx.model, "direction": "output"},
        )


def _reset_for_testing() -> None:
    """Reset module-level state between tests. Not for production use."""
    global _meter, _instruments
    _meter = None
    _instruments = {}
