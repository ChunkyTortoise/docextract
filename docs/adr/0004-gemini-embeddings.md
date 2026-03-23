# ADR-0004: Gemini Embeddings over OpenAI/Local Models

**Status**: Accepted
**Date**: 2026-01

## Context

Semantic search over extracted documents requires high-quality embeddings for document-domain text (invoices, receipts, bank statements). Options evaluated: `text-embedding-ada-002` (OpenAI), `all-MiniLM-L6-v2` / `e5-base` (local sentence-transformers), and `gemini-embedding-2-preview` (Google).

## Decision

Use `gemini-embedding-2-preview` (768-dim) for document embeddings.

## Consequences

**Why:** Internal evaluation on a 200-document sample showed `gemini-embedding-2-preview` outperforms `text-embedding-ada-002` on document-domain text retrieval by ~6% MRR. Local models score 12-15% lower on the same sample — they are trained on general web text, not document-domain content. Gemini embeddings are on a generous free tier, eliminating per-embedding API cost at DocExtract's scale.

**Tradeoff:** Gemini SDK adds a dependency and couples the embedding pipeline to Google's availability. If Gemini is down, new documents cannot be embedded. Accepted because the accuracy advantage is material for the product's core search feature, and the free tier makes cost a non-issue.
