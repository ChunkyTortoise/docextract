# ADR-0004: Gemini Embeddings over OpenAI/Local Models

**Status**: Accepted
**Date**: 2026-01

## Context

Semantic search over extracted documents requires high-quality embeddings for document-domain text (invoices, receipts, bank statements). Alternatives considered: `text-embedding-ada-002` (OpenAI), `all-MiniLM-L6-v2` / `e5-base` (local sentence-transformers), and `gemini-embedding-2-preview` (Google).

## Decision

Use `gemini-embedding-2-preview` (768-dim) for document embeddings.

## Consequences

**Why:** The current [embedding adapter](../../app/services/embedder.py) configures `gemini-embedding-2-preview` with 768 output dimensions for document retrieval. Using one adapter keeps embedding generation consistent across ingestion and search.

**Evidence limit:** No committed comparative retrieval run supports a ranking advantage over OpenAI or local models. The [offline retrieval evaluator](../../scripts/eval_offline_retrieval.py) exercises synthetic BM25 queries only; it does not measure embeddings or hybrid RRF. Actual embedding cost and comparative retrieval accuracy remain unmeasured.

**Tradeoff:** The Gemini SDK adds a dependency and couples embedding generation to Google's availability. If the provider is unavailable, new embeddings cannot be generated. Provider cost and retrieval quality should be measured on the intended workload before claiming an advantage.
