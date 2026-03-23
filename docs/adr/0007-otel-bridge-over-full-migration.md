# ADR-0007: OpenTelemetry Bridge over Full Migration

**Status**: Accepted
**Date**: 2026-03

## Context

DocExtract has a custom `llm_tracer.py` that persists LLM call traces to PostgreSQL. The `/stats` endpoint and the HITL review feature both query the `llm_traces` table. The industry is standardizing on OpenTelemetry for observability.

## Decision

Augment the existing `llm_tracer.py` with OTel metric emission rather than replacing it. Feature-flag the OTel layer behind `OTEL_ENABLED=false`.

## Consequences

**Why:** The custom `trace_llm_call` context manager is called by every LLM service and already persists traces with request IDs, token counts, and confidence scores. Replacing it entirely would break all existing tests and the `/stats` endpoint that queries `llm_traces`. The bridge pattern adds OTel's industry-standard format (Prometheus metrics, distributed spans) without breaking the DB-backed tracing that product features depend on.

Feature-flagging behind `OTEL_ENABLED=false` means zero performance impact in development and CI — the bridge is a no-op when disabled.

**Tradeoff:** Two parallel tracing paths add conceptual overhead. If OTel becomes the primary observability layer, the custom DB tracer could eventually be deprecated. Accepted because the DB tracer powers product features, not just ops observability, so it cannot be removed without a larger refactor.
