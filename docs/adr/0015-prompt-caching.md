# ADR-0015: Anthropic Prompt Caching

**Status:** Accepted
**Date:** 2026-04-18

## Context

DocExtract processes documents in two passes: an extraction pass (system prompt + few-shot examples + doc text) and an optional correction pass. In eval suite runs the same system prompt and doc-type few-shot prefix are sent with every request, paying full input-token cost each time.

Prompt caching can reuse eligible stable content blocks across provider calls. Eligibility and pricing depend on the selected model and provider rules; sending `cache_control` alone does not establish a cache hit or savings.

The current dependency declares `anthropic>=0.49.0` in [pyproject.toml](../../pyproject.toml).

## Decision

1. **Declare `anthropic>=0.49.0`** for the provider SDK used by these request paths.
2. **Cache the system prompt** by passing `system` as a list of content blocks with `cache_control: {"type": "ephemeral"}`.
3. **Cache the few-shot corrections prefix** (when active learning is enabled) as the first user content block with `cache_control`, followed by the uncached document text.
4. **Track cache hit/miss tokens** in `TraceContext` (`cache_creation_input_tokens`, `cache_read_input_tokens`) and emit them as OTel counters (`prompt_cache_read_tokens_total`, `prompt_cache_creation_tokens_total`).

The extractor marks the system prompt and, when present, the few-shot prefix with ephemeral cache control. Their eligible token count and actual cache-hit rate have not been established by a committed run.

## Consequences

### Evidence status

Savings remain unmeasured. [scripts/bench_caching.py](../../scripts/bench_caching.py) can record token usage and latency, but no generated caching benchmark report is committed. Its report estimates cost using a hard-coded pricing table; that is separate from metered billing. A useful run must confirm nonzero cache reads and identify the model, prompt and pricing assumptions.

### Trade-offs

- **Cache key sensitivity**: changing the system prompt text invalidates the cache; prompt changes during autoresearch optimization incur a full creation charge on the first call.
- **Eligibility and break-even**: cacheable prefix length, reuse frequency and model-specific charges determine whether caching saves money. No workload-specific break-even point has been measured.
- **Instructor path**: when instructor returns a Pydantic model (instructor raw response is consumed), `record_response` cannot extract cache tokens; they degrade gracefully to `None` in the trace. OTel `AnthropicInstrumentor` captures them at the SDK level.

## Alternatives considered

- **Semantic cache** (Redis cosine-similarity lookup): already implemented separately in `app/services/semantic_cache.py`. Prompt caching is complementary: semantic cache avoids the API call entirely for near-duplicate documents; prompt caching reduces per-call cost for novel documents.
- **No caching**: simpler request construction, but does not attempt to reuse stable prompt prefixes. The cost difference remains unmeasured.
