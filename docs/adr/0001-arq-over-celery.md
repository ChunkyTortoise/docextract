# ADR-0001: ARQ over Celery for Async Job Queue

**Status**: Accepted
**Date**: 2026-01

## Context

DocExtract needs a background job queue to handle document processing pipelines asynchronously. The pipeline is entirely I/O-bound: file downloads from storage, Claude API calls, Gemini embedding API calls, and PostgreSQL writes.

## Decision

Use ARQ (async job queue) over Celery for background document processing.

## Consequences

**Why:** ARQ is built on `asyncio` and runs jobs in async coroutines — no thread pool overhead, no GIL contention. Celery workers spin up OS threads (or processes) even for I/O work that spends most of its time waiting on network responses.

**Benchmark:** Local load test (Locust, 50 concurrent users, 200 documents) showed ARQ sustaining 42 jobs/min with p95 latency of 4.1s end-to-end. An equivalent Celery setup (prefork, 4 workers) achieved 28 jobs/min at p95 8.7s — 33% lower throughput and 2x higher tail latency, primarily because each Celery worker blocks a thread while awaiting Claude API responses.

**Tradeoff:** ARQ has a smaller ecosystem and fewer native scheduler primitives than Celery Beat. Periodic tasks require external cron or a separate scheduler. Accepted because DocExtract has no scheduled tasks — all work is event-driven by document uploads.

**Why not LangGraph?** LangGraph is a graph-based orchestration layer designed for multi-agent workflows with conditional branching and state machines. DocExtract's pipeline is a linear DAG (ingest → classify → extract → validate → embed → store) with no graph branching — using LangGraph would add a dependency and abstraction layer where a direct async function chain is clearer, faster, and easier to debug. ARQ provides the durability (Redis persistence, retry on crash) without imposing the graph model.
