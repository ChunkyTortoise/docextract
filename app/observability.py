"""OpenTelemetry observability setup with Prometheus metrics and OTLP span export.

Feature-flagged behind OTEL_ENABLED=true. When disabled all emit functions
are no-ops so existing code and tests are unaffected.

Custom metrics:
    llm_call_duration_ms       — Histogram (model, operation, status)
    llm_calls_total            — Counter   (model, operation, status)
    llm_tokens_total           — Counter   (model, direction)
    circuit_breaker_state      — Gauge     (model) — 0=CLOSED, 1=HALF_OPEN, 2=OPEN

Distributed tracing (OTLP):
    Enable by setting OTEL_EXPORTER_OTLP_ENDPOINT (e.g. http://jaeger:4317).
    Sends gRPC spans to any OTLP-compatible backend (Jaeger, Tempo, Honeycomb).
    Local dev: docker compose -f docker-compose.yml -f docker-compose.observability.yml up
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
_tracer: Any = None
_instruments: dict[str, Any] = {}

# Circuit breaker state numeric mapping (for Prometheus gauge)
_CB_STATE_VALUES = {"closed": 0, "half_open": 1, "open": 2}


def setup_telemetry(app: "FastAPI") -> None:
    """Register OTel providers, mount /metrics, and configure OTLP span export.

    Safe to call when disabled — becomes a no-op. Import errors from missing
    packages are caught and logged so the app still starts without OTel.
    """
    global _meter, _tracer, _instruments

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

    # ── Tracer provider + optional OTLP span export ──────────────────────────
    tracer_provider = TracerProvider(resource=resource)

    if settings.otel_exporter_otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            otlp_exporter = OTLPSpanExporter(
                endpoint=settings.otel_exporter_otlp_endpoint,
                insecure=settings.otel_exporter_otlp_insecure,
            )
            tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
            logger.info(
                "OTLP span export enabled — endpoint '%s'",
                settings.otel_exporter_otlp_endpoint,
            )
        except ImportError as e:
            logger.warning(
                "opentelemetry-exporter-otlp-proto-grpc not installed, "
                "span export disabled: %s",
                e,
            )

    trace.set_tracer_provider(tracer_provider)
    _tracer = trace.get_tracer("docextract")

    # ── Meter provider + Prometheus export ───────────────────────────────────
    prometheus_reader = PrometheusMetricReader()
    meter_provider = MeterProvider(resource=resource, metric_readers=[prometheus_reader])
    metrics.set_meter_provider(meter_provider)

    _meter = metrics.get_meter("docextract")
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
        "circuit_breaker": _meter.create_gauge(
            "circuit_breaker_state",
            description="Circuit breaker state per model: 0=CLOSED, 1=HALF_OPEN, 2=OPEN",
        ),
        # Cost tracking gauge — add when OTEL_ENABLED=true:
        # "llm_cost_usd": _meter.create_gauge(
        #     "llm_cost_usd",
        #     description="Cumulative LLM spend in USD per model/operation (Gauge, updated by CostTracker)",
        #     unit="USD",
        # ),
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


def emit_circuit_breaker_state(model: str, state: str) -> None:
    """Emit circuit breaker state as a Prometheus gauge.

    Called by ModelRouter after each state transition.
    state should be one of: 'closed', 'half_open', 'open'.
    No-op when OTel is disabled.
    """
    if not settings.otel_enabled or "circuit_breaker" not in _instruments:
        return
    numeric = _CB_STATE_VALUES.get(state, 0)
    _instruments["circuit_breaker"].set(numeric, attributes={"model": model})


def get_tracer() -> Any:
    """Return the OTel tracer, or None when OTel is disabled.

    Use in services to create spans:
        tracer = get_tracer()
        if tracer:
            with tracer.start_as_current_span("extract"):
                ...
    """
    return _tracer


def _reset_for_testing() -> None:
    """Reset module-level state between tests. Not for production use."""
    global _meter, _tracer, _instruments
    _meter = None
    _tracer = None
    _instruments = {}
