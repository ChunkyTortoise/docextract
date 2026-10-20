# ADR-0018: Independent LLM Judge (Gemini) + Multi-Provider Router

**Status:** Accepted
**Date:** 2026-04-18

## Context

The existing `LLMJudge` used `settings.classification_models[0]` (Claude Haiku) to evaluate Claude Sonnet extractions. Using the same model family for extraction and judging risks correlated errors. No committed calibration study establishes the magnitude or direction of bias for this pipeline.

Additionally, `model_router._is_transient()` only recognized `anthropic.*` exception types. The previous extraction chain included `glm-4-plus` (third entry) but the `call_fn` was an Anthropic client; non-Anthropic models caused immediate non-transient raises, making the fallback logic misleading.

## Decision

### Judge

Refactor `LLMJudge.evaluate()` to try **Gemini 2.5 Flash** first (independent provider) and fall back to Claude Haiku only if Gemini is unavailable or fails. `JudgeResult` now includes a `judge_model: str` field recording which model produced the verdict.

Gemini is accessed via the `GeminiJudgeClient` adapter in `app/services/providers/gemini_provider.py`, which wraps the `google.genai` async interface with a response structure compatible with the judge's JSON parser.

Activation: `LLM_JUDGE_ENABLED=true` enables provider judging; the default is disabled. `GEMINI_API_KEY` configures the Gemini adapter. Missing credentials or a failed Gemini evaluation can lead to the Claude fallback. These are configured code paths, not proof of a successful live judge run.

### Router

Update `_is_transient()` to also catch `google.api_core.exceptions.ResourceExhausted`, `ServiceUnavailable`, and `DeadlineExceeded`. This ensures Gemini provider entries in fallback chains participate correctly in the circuit breaker.

Update `README.md` to remove fictional GLM-4/Zhipu references; those providers have no implementation and cause non-transient failures on the Anthropic client.

## Consequences

### Benefits
- Uses a different provider when available, reducing dependence on the extractor's model family. This does not establish unbiased scores or a measured quality improvement.
- `judge_model` field in `JudgeResult` makes which reviewer produced the score auditable.
- Router can now handle Gemini transient errors correctly when Gemini models appear in extraction chains.

### Trade-offs
- **Gemini API key required** for independent judging; falls back to Claude if absent.
- **Latency**: judging requires provider calls when enabled. Relative Gemini/Claude latency and sampling overhead remain unmeasured.
- **Score calibration**: Gemini and Claude may use different scoring distributions for the same rubric. The implementation returns the first successful verdict; it does not compare an ensemble. The `evidence` list contains supporting quotations, not disagreement flags.

## Alternatives considered

- **GPT-4o as judge**: available via OpenAI API, strong at evaluation tasks. Not chosen because `google-genai` was already in the dependency set; adding `openai` would add another provider dependency.
- **Ensemble (all three)**: running Gemini + Claude + GPT-4o and averaging would require additional calls and a calibration method. Deferred; no ensemble quality or cost comparison is recorded.
