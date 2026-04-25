# ADR-0017: Semantic Cache (L1 Exact + L2 Embedding Similarity)

**Status**: Accepted
**Date**: 2026-04-18

## Context

DocExtract processes documents submitted by recurring users and batch pipelines. In practice, many uploaded documents are near-duplicates: the same invoice template with different line-item values, the same bank statement format across months, or repeated API calls during development. Paying full Claude API cost for each submission is wasteful when the extraction result would be identical or nearly identical.

Two types of cache hits are worth targeting:

- **Exact deduplication**: the same document (byte-for-byte) submitted again. SHA-256 hash on the stored file catches this before any LLM call.
- **Near-duplicate deduplication**: documents with the same text structure but different values (e.g., invoices from the same vendor). Exact hash misses these; embedding similarity can catch them.

## Decision

Implement a two-layer semantic cache in `app/services/semantic_cache.py`, feature-flagged behind `SEMANTIC_CACHE_ENABLED=false`:

- **L1 (exact)**: SHA-256 hash of the document content, checked before enqueueing the ARQ job. Already implemented at upload time via `app/utils/hashing.py`.
- **L2 (embedding similarity)**: Embed the extracted document text using Gemini embeddings, store the embedding in Redis alongside the cached extraction result. On new requests, compute cosine similarity against cached embeddings. Return the cached result when similarity exceeds a configurable threshold (`SEMANTIC_CACHE_THRESHOLD`, default 0.97).

Cache entries expire via Redis TTL (default 24 hours). The similarity threshold is intentionally conservative (0.97) to avoid returning incorrect field values for superficially similar documents with different monetary amounts.

## Alternatives Considered

- **No cache (always call Claude)**: Simple, always correct. Wasteful for repeated submissions.
- **Exact hash only (L1 only)**: Catches byte-for-byte duplicates but misses near-duplicates, which are the common case in batch pipelines.
- **Prompt-level caching (Anthropic API)**: Covered by ADR-0015. Complementary -- prompt caching reduces per-call cost for novel documents; semantic cache avoids the API call entirely for near-duplicate documents.
- **Redis sorted set with approximate nearest neighbor**: More complex, unnecessary at DocExtract's scale. Linear scan over cached embeddings is fast enough when the cache size is bounded by TTL.

## Consequences

**Why:** The L1/L2 layered approach handles both the exact case (zero overhead, hash lookup) and the near-duplicate case (one embedding call, avoiding one Claude call). At a 0.97 threshold, the false-positive rate on the invoice and bank-statement document types is negligible -- values like totals and dates change the text enough to fall below threshold.

**Cost model:** Gemini embedding API is free-tier. The Redis storage cost for a 768-dim float32 embedding is ~3KB per entry -- negligible at any realistic cache size.

**Tradeoff:** A 0.97 threshold is conservative. Lowering it toward 0.90 increases cache hit rate but risks returning incorrect field values for documents with the same format but different amounts. The threshold should be tuned per document type (invoices: 0.97; contracts: 0.95 is safer). This tuning is deferred until production data shows the hit-rate distribution.

**Feature flag:** `SEMANTIC_CACHE_ENABLED=false` by default. The cache adds a Redis read + embedding call overhead on every miss. Until hit-rate data is available, the default-off flag ensures new deployments don't pay the miss overhead before the cache is warm.
