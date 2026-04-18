# ADR-0019 — TF-IDF Reranker + Agentic Self-Reflection Loop

**Status:** Accepted  
**Date:** 2026-04-18

## Context

Two gaps in the AI pipeline were identified:

1. **No-op reranker**: `agentic_rag._execute_tool("rerank_results")` returned an empty list and an empty observation string — effectively silently dropped the user's rerank request without executing any ranking.

2. **Single-pass extraction**: Even when the model returns a low-confidence extraction (below 0.8), the system returned that result without a corrective loop. The instructor retry only handles schema-validation failures, not semantic low-confidence.

## Decision

### Reranker (`app/services/reranker.py`)

Replace the no-op with a `TFIDFReranker` class that:
1. Fits a TF-IDF vocabulary on [query] + [candidate documents].
2. Computes cosine similarity between the query vector and each document vector.
3. Combines TF-IDF score with the existing retrieval score (RRF or vector similarity) using a weighted blend (`alpha=0.4` for TF-IDF, `0.6` for retrieval).
4. Returns results sorted by combined score.

`_execute_tool` receives `accumulated_results` as a new parameter so the reranker has access to the results accumulated across previous agent steps.

No external API key or model download required — `scikit-learn` is already a transitive dependency.

### Agentic Reflection (`app/services/claude_extractor.py`)

Add `reflection: bool = False` parameter to `extract()`. When set and `confidence < 0.8`:
1. Show the model its own low-confidence extraction alongside the source document.
2. Ask for a revised extraction with an updated confidence score.
3. Return the revised result; set `ExtractionResult.reflection_applied = True`.

The reflection pass uses the same model that produced the original extraction (avoids multi-provider cost for this path), with prompt caching on the system prompt.

## Consequences

### Reranker
- **Benefit**: `rerank_results` action now returns meaningfully scored results; agent loop can request reranking as an explicit improvement step.
- **Trade-off**: TF-IDF doesn't capture semantic similarity — it will miss synonyms. A cross-encoder model (e.g., `cross-encoder/ms-marco-MiniLM-L-6-v2` via `sentence-transformers`) would be stronger but requires a model download not feasible in the current Streamlit Cloud environment. Logged as a follow-up.

### Reflection
- **Benefit**: Low-confidence extractions get a self-corrective pass before returning to the caller — reduces cases where a confidence 0.5 extraction goes straight to the client.
- **Trade-off**: Adds ~1-2s latency and ~$0.002 cost when triggered. Only fires on `reflection=True` (opt-in, not default) and only below the 0.8 threshold, so production impact is bounded.
- **Metric tracking**: `reflection_applied` flag in `ExtractionResult` + `trace_llm_call(operation="reflect")` in OTel traces allow measuring reflection frequency and confidence lift.

## Alternatives considered

- **Cohere rerank-3 API**: Strong semantic reranker, no local model. Not chosen because it requires a new API key and adds a production dependency on a third party; TF-IDF is self-sufficient.
- **BGE-reranker-v2-m3 local model**: Best accuracy; blocked by Streamlit Cloud memory limits and absence of `FlagEmbedding` in the venv.
- **Judge-driven reflection**: Use `LLMJudge` verdict to trigger reflection — stronger signal but doubles the judge+extract cost. Deferred; current implementation uses self-assessed confidence as the proxy.
