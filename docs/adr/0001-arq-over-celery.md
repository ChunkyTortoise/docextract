# ADR-0001: ARQ over Celery for Async Job Queue

**Status**: Accepted
**Date**: 2026-01

## Context

DocExtract needs a background job queue to handle document processing pipelines asynchronously. The pipeline is entirely I/O-bound: file downloads from storage, Claude API calls, Gemini embedding API calls, and PostgreSQL writes.

## Decision

Use ARQ (async job queue) over Celery for background document processing.

## Consequences

**Why:** ARQ is built on `asyncio` and runs jobs in async coroutines — no thread pool overhead, no GIL contention. Celery workers spin up OS threads (or processes) even for I/O work that spends most of its time waiting on network responses.

**Tradeoff:** ARQ has a smaller ecosystem and fewer native scheduler primitives than Celery Beat. Periodic tasks require external cron or a separate scheduler. Accepted because DocExtract has no scheduled tasks — all work is event-driven by document uploads.
