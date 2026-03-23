# ADR-0010: Regex-First Guardrails over LLM-Based Safety Filters

**Status**: Accepted
**Date**: 2026-03

## Context

Extracted documents may contain PII (SSN, credit card numbers) that must be detected before storage. Extraction results may also hallucinate facts not present in the source document. An LLM-based safety classifier could address both, but runs on every extraction.

## Decision

Use regex pattern matching for PII detection and string containment for hallucination boundary checking, rather than LLM-based safety classifiers.

## Consequences

**Why:** Guardrails run on every extraction. Adding another LLM call per document would double latency and cost. Regex PII detection covers the patterns that carry legal liability (SSN, credit card, phone, email) at zero marginal cost and with deterministic output. The hallucination boundary check uses string containment rather than semantic similarity — simpler, faster, and zero API cost.

**Tradeoff:** Regex misses unstructured PII (e.g., "born in Springfield on March 4th"). String containment misses paraphrased but grounded facts. Accepted because the goal is a first guardrail layer, not comprehensive safety — and the structured patterns (SSN, credit card numbers) are the ones that carry legal liability. If false-positive rates become a problem, upgrade to LLM-based checking only for flagged documents.
