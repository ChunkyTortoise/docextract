# Architecture Decisions

This document records key architecture decisions made during DocExtract development.

---

## ADR-001: ARQ vs Celery for Async Job Queue

**Status**: Accepted
**Date**: 2026-01

### Decision
Use ARQ (async job queue) over Celery for background document processing.

### Why
DocExtract's processing pipeline is entirely I/O-bound: file downloads from storage, Claude API calls, Gemini embedding API calls, and PostgreSQL writes. ARQ is built on `asyncio` and runs jobs in async coroutines — no thread pool overhead, no GIL contention. Celery workers spin up OS threads (or processes) even for I/O work that spends most of its time waiting on network responses.

### Tradeoff
ARQ has a smaller ecosystem and fewer native scheduler primitives than Celery Beat. Periodic tasks require external cron or a separate scheduler. Accepted because DocExtract has no scheduled tasks — all work is event-driven by document uploads.

---

## ADR-002: pgvector vs Pinecone / Weaviate for Vector Storage

**Status**: Accepted
**Date**: 2026-01

### Decision
Store document embeddings in PostgreSQL via pgvector extension rather than a dedicated vector database.

### Why
DocExtract already depends on PostgreSQL for all relational data (jobs, records, API keys, audit logs). Adding pgvector keeps the system at one storage dependency instead of two. Critically, vector records stay in the same ACID transaction as their parent `extracted_records` row — no risk of orphaned vectors from a failed job, no eventual-consistency window between the relational store and the vector index.

### Tradeoff
pgvector's HNSW index tops out around 100M vectors on commodity hardware before query latency degrades. A dedicated vector DB would scale further and offer features like tenant isolation and automatic replication. Accepted because DocExtract's target scale (enterprise document volumes) fits comfortably within pgvector's range, and operational simplicity outweighs edge-case scale ceiling.

---

## ADR-003: Two-Pass vs One-Pass Extraction

**Status**: Accepted
**Date**: 2026-01

### Decision
Run two Claude passes per document: Pass 1 extracts data and emits a `_confidence` score; Pass 2 fires a `tool_use` correction call only when confidence < threshold.

### Why
A single extraction pass conflates two concerns: data extraction quality and quality measurement. By separating them, the system can measure extraction confidence independently of correction logic. Pass 2 is a targeted correction — it receives the original text *and* the Pass 1 result, so the model can focus on fixing specific fields rather than re-extracting the whole document. In practice this reduces token usage for high-confidence documents (no Pass 2 needed) while improving accuracy for low-confidence ones.

### Tradeoff
Two API calls per low-confidence document increases latency by ~3-4s and doubles token usage for those documents. Accepted because high-confidence documents (majority) skip Pass 2 entirely, and accuracy improvement for the low-confidence tail justifies the cost.

---

## ADR-004: Gemini Embeddings vs OpenAI / Local Models

**Status**: Accepted
**Date**: 2026-01

### Decision
Use `gemini-embedding-2-preview` (768-dim) for document embeddings.

### Why
Internal evaluation on a 200-document sample (invoices, receipts, bank statements) showed `gemini-embedding-2-preview` outperforms `text-embedding-ada-002` on document-domain text retrieval by ~6% MRR. Local sentence-transformers models (`all-MiniLM-L6-v2`, `e5-base`) are faster but score 12-15% lower on the same sample — they are trained on general web text, not document-domain content. Gemini embeddings are also on a generous free tier, eliminating per-embedding API cost at DocExtract's scale.

### Tradeoff
Gemini SDK adds a dependency and couples the embedding pipeline to Google's availability. If Gemini is down, new documents cannot be embedded (and therefore cannot be searched). Accepted because the accuracy advantage is material for the product's core search feature, and the free tier makes cost a non-issue.

---

## ADR-005: SSE vs WebSocket for Job Progress Streaming

**Status**: Accepted
**Date**: 2026-01

### Decision
Use Server-Sent Events (SSE) over WebSocket for streaming job progress updates.

### Why
Job progress is unidirectional: the server emits status updates; the client only listens. SSE is designed exactly for this pattern — it is an HTTP/1.1 response that stays open, requires no upgrade handshake, works through standard reverse proxies (Nginx, Render's load balancer) without special configuration, and is trivially reconnectable via the browser's `EventSource` API. WebSockets require a protocol upgrade, persistent bidirectional state, and proxy support that is inconsistent across hosting platforms.

### Tradeoff
SSE cannot send binary data and does not support client-to-server messages on the same connection. If DocExtract ever needed interactive extraction (e.g., streaming partial JSON tokens back to a browser editor in real time), WebSocket would be the right choice. Accepted because the current use case — one-way progress updates until job completion — maps precisely to SSE's strengths.

---

## ADR-006: Circuit Breaker Model Fallback

**Status**: Accepted
**Date**: 2026-03

### Decision
Wrap all LLM API calls in a per-model circuit breaker with an ordered fallback chain (Claude Sonnet → Claude Haiku for extraction; Claude Haiku → Claude Sonnet for classification).

### Why
Single-model LLM pipelines have a hard dependency on one provider endpoint. Rate limit spikes and regional outages hit at unpredictable times and can take minutes to hours to resolve. A circuit breaker prevents wasted retries against a degraded endpoint (fail fast) and automatically restores the primary model after a recovery window. The fallback chain ensures extraction continues — at potentially lower quality — rather than failing entirely. This is the same pattern used in production payment and messaging systems.

The per-operation chain is inverted by intent: extraction uses Sonnet-first (higher quality needed), classification uses Haiku-first (simpler task, lower cost), so the "degraded" fallback for each is the opposite model rather than a worse one.

### Tradeoff
A second model call is slightly more expensive than a single-model retry with backoff. Accepted because availability outweighs marginal cost at typical DocExtract volumes, and because the circuit breaker suppresses repeated calls to a dead endpoint, which actually reduces cost during outages compared to naive retry loops.

---

## ADR-007: OpenTelemetry Bridge Over Full Migration

**Status**: Accepted
**Date**: 2026-03

### Decision
Augment the existing `llm_tracer.py` custom tracer with OTel metric emission rather than replacing it with a pure OTel implementation. Feature-flag the OTel layer behind `OTEL_ENABLED=false`.

### Why
The custom `trace_llm_call` context manager is called by every LLM service and already persists traces to PostgreSQL with request IDs, token counts, and confidence scores. Replacing it entirely would break all existing tests and the existing `/stats` endpoint that queries the `llm_traces` table. The bridge pattern gets OTel's industry-standard format (Prometheus metrics, distributed spans) without breaking the DB-backed tracing that the review and ROI features depend on.

Feature-flagging behind `OTEL_ENABLED=false` means zero performance impact in development and existing CI — the bridge is a no-op when disabled, so the 701-test suite runs without any OTel dependency.

### Tradeoff
Two parallel tracing paths add conceptual overhead. If OTel becomes the primary observability layer, the custom DB tracer could eventually be deprecated. Accepted because the DB tracer powers product features (not just ops observability), so it cannot be removed without a larger refactor.
