# ADR-0006: Circuit Breaker Model Fallback

**Status**: Accepted
**Date**: 2026-03

## Context

Single-model LLM pipelines have a hard dependency on one provider endpoint. Rate limit spikes and regional outages hit at unpredictable times and can take minutes to hours to resolve. DocExtract's extraction pipeline must remain available even when the primary model is degraded.

## Decision

Wrap all LLM API calls in a per-model circuit breaker with an ordered fallback chain: Claude Sonnet → Claude Haiku for extraction; Claude Haiku → Claude Sonnet for classification.

## Consequences

**Why:** A circuit breaker prevents wasted retries against a degraded endpoint (fail fast) and automatically restores the primary model after a recovery window. The fallback chain ensures extraction continues — at potentially lower quality — rather than failing entirely. The per-operation chain is inverted by intent: extraction uses Sonnet-first (higher quality needed), classification uses Haiku-first (simpler task, lower cost), so the "degraded" fallback for each is the opposite model rather than a worse one.

**Tradeoff:** A second model call is slightly more expensive than a single-model retry with backoff. Accepted because availability outweighs marginal cost at typical DocExtract volumes, and because the circuit breaker suppresses repeated calls to a dead endpoint — which actually reduces cost during outages compared to naive retry loops.
