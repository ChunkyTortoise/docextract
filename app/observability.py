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

# Langfuse client — populated by setup_langfuse()
_langfuse: Any = None

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
        "cache_hits": _meter.create_counter(
            "semantic_cache_hits_total",
            description="Semantic cache hits",
        ),
        "cache_misses": _meter.create_counter(
            "semantic_cache_misses_total",
            description="Semantic cache misses",
        ),
        "cache_cost_saved": _meter.create_counter(
            "semantic_cache_cost_saved_usd",
            description="Cumulative USD saved by semantic cache",
            unit="USD",
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


def emit_cache_metrics(hit: bool, cost_saved_usd: float = 0.0) -> None:
    """Emit semantic cache hit/miss metrics.

    No-op when OTel is disabled.
    """
    if not settings.otel_enabled or not _instruments:
        return
    if hit:
        _instruments["cache_hits"].add(1)
        if cost_saved_usd > 0:
            _instruments["cache_cost_saved"].add(cost_saved_usd)
    else:
        _instruments["cache_misses"].add(1)


def get_tracer() -> Any:
    """Return the OTel tracer, or None when OTel is disabled.

    Use in services to create spans:
        tracer = get_tracer()
        if tracer:
            with tracer.start_as_current_span("extract"):
                ...
    """
    return _tracer


def setup_langfuse() -> None:
    """Initialize Langfuse cloud tracing client.

    Feature-flagged behind LANGFUSE_ENABLED=true. When disabled, all
    langfuse_* helpers are no-ops. Requires langfuse package installed.
    """
    global _langfuse

    if not settings.langfuse_enabled:
        return

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.warning("LANGFUSE_ENABLED=true but keys not set, skipping")
        return

    try:
        from langfuse import Langfuse

        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        logger.info("Langfuse tracing enabled — host '%s'", settings.langfuse_host)
    except ImportError:
        logger.warning("langfuse package not installed, skipping Langfuse setup")
    except Exception as e:
        logger.warning("Langfuse initialization failed: %s", e)


def langfuse_trace(
    name: str,
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    input: Any = None,
) -> Any:
    """Create a Langfuse trace. Returns a trace object or None when disabled.

    Usage with BackgroundTasks (Sync Sidecar pattern):
        trace = langfuse_trace("extraction", session_id=request_id)
        # ... do work ...
        background_tasks.add_task(langfuse_flush)
    """
    if _langfuse is None:
        return None

    from app.services.pii_sanitizer import sanitize_for_trace

    sanitized_input = sanitize_for_trace(input) if input else input
    return _langfuse.trace(
        name=name,
        session_id=session_id,
        user_id=user_id,
        metadata=metadata,
        input=sanitized_input,
    )


def langfuse_generation(
    trace: Any,
    name: str,
    *,
    model: str = "",
    input: Any = None,
    output: Any = None,
    usage: dict[str, int] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any:
    """Log an LLM generation within a Langfuse trace. No-op when trace is None."""
    if trace is None:
        return None

    from app.services.pii_sanitizer import sanitize_for_trace

    return trace.generation(
        name=name,
        model=model,
        input=sanitize_for_trace(input) if input else input,
        output=sanitize_for_trace(output) if output else output,
        usage=usage,
        metadata=metadata,
    )


def langfuse_flush() -> None:
    """Flush pending Langfuse events. Call in BackgroundTasks after request."""
    if _langfuse is not None:
        _langfuse.flush()


def get_langfuse() -> Any:
    """Return the Langfuse client, or None when disabled."""
    return _langfuse


def _reset_for_testing() -> None:
    """Reset module-level state between tests. Not for production use."""
    global _meter, _tracer, _instruments, _langfuse
    _meter = None
    _tracer = None
    _instruments = {}
    _langfuse = None
