# ADR-0018 — Independent LLM Judge (Gemini) + Multi-Provider Router

**Status:** Accepted  
**Date:** 2026-04-18

## Context

The existing `LLMJudge` used `settings.classification_models[0]` (Claude Haiku) to evaluate Claude Sonnet extractions. This creates a **self-grading bias**: the same model family produces both the output being judged and the verdict, inflating scores. Studies on LLM evaluation show self-evaluation scores are systematically higher than cross-provider evaluation.

Additionally, `model_router._is_transient()` only recognized `anthropic.*` exception types. The extraction chain includes `glm-4-plus` (third entry) but the `call_fn` was an Anthropic client — non-Anthropic models caused immediate non-transient raises, making the fallback logic misleading.

## Decision

### Judge

Refactor `LLMJudge.evaluate()` to try **Gemini 2.5 Flash** first (independent provider) and fall back to Claude Haiku only if Gemini is unavailable or fails. `JudgeResult` now includes a `judge_model: str` field recording which model produced the verdict.

Gemini is accessed via the `GeminiJudgeClient` adapter in `app/services/providers/gemini_provider.py`, which wraps the `google.genai` async interface with a response structure compatible with the judge's JSON parser.

Activation: requires `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) env var. Without it, `_get_gemini_client()` returns `None` and the system falls back to Claude silently.

### Router

Update `_is_transient()` to also catch `google.api_core.exceptions.ResourceExhausted`, `ServiceUnavailable`, and `DeadlineExceeded`. This ensures Gemini provider entries in fallback chains participate correctly in the circuit breaker.

Update `README.md` to remove fictional GLM-4/Zhipu references — those providers have no implementation and cause non-transient failures on the Anthropic client.

## Consequences

### Benefits
- Eliminates self-grading bias in eval quality scores — an independent model's evaluation is more credible in interviews and in published benchmarks.
- `judge_model` field in `JudgeResult` makes which reviewer produced the score auditable.
- Router can now handle Gemini transient errors correctly when Gemini models appear in extraction chains.

### Trade-offs
- **Gemini API key required** for independent judging — degrades gracefully to Claude if absent.
- **Latency**: `_evaluate_with_gemini` adds ~400-800ms latency vs local Claude; acceptable for eval runs (not on the request hot path unless judge sampling is enabled).
- **Score calibration**: Gemini and Claude may use different scoring distributions for the same rubric — the ensemble disagrement flag (`evidence` list) surfaces conflicts but doesn't auto-resolve them.

## Alternatives considered

- **GPT-4o as judge**: available via OpenAI API, strong at evaluation tasks. Not chosen because `google-genai` was already in the dependency set; adding `openai` would add another provider dependency.
- **Ensemble (all three)**: running Gemini + Claude + GPT-4o and averaging — stronger signal but 3× judge cost. Deferred; current architecture supports adding it later.
