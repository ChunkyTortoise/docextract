# ADR-0014: Native LLM-as-Judge Eval over TruLens/RAGAS

**Status**: Accepted
**Date**: 2026-04

## Context

DocExtract needed online quality monitoring: a way to measure extraction accuracy in production without ground-truth labels. The options were a third-party eval framework (TruLens, RAGAS, DeepEval) or a purpose-built LLM-as-judge running as an ARQ task.

## Decision

Build a native `LLMJudge` class that calls Claude with a 4-dimension rubric (completeness, field_accuracy, hallucination_absence, format_compliance), stores results in an `eval_log` table, and runs on a 10% sample of jobs via ARQ fire-and-forget task (`judge_extraction_sample`).

## Alternatives Considered

- **TruLens**: Provides prebuilt feedback functions and a dashboard. Requires a separate TruLens server or cloud account, and its feedback functions are designed for RAG pipelines, not structured document extraction. The schema mismatch would require wrapping every extraction call in TruLens instrumentation.
- **RAGAS**: Excellent for RAG faithfulness/context recall metrics. Requires a reference corpus per query — DocExtract has no ground-truth corpus in production. RAGAS metrics are not directly applicable to extraction tasks (field presence, value accuracy).
- **DeepEval**: Requires running a test suite with expected outputs. Useful for offline eval but does not provide online sampling.
- **Promptfoo**: Already integrated for CI golden-file regression testing (`promptfooconfig.yaml`). Not designed for production sampling.

## Consequences

**Why:** A native judge gives full control over the rubric, sampling rate, and storage schema. The 4-dimension rubric maps directly to DocExtract's product requirements: completeness (all required fields present), field_accuracy (values match source), hallucination_absence (no invented data), format_compliance (output matches schema). Scores are stored in `eval_log` with composite as the EWMA input for the Quality Monitor dashboard. The 10% sampling rate keeps judge costs at ~$0.003/job (Haiku pricing) with negligible latency impact on the main pipeline.

**Tradeoff:** Maintaining the rubric and judge prompts requires engineering effort as document types evolve. Third-party frameworks provide prebuilt rubrics and community support. Accepted because the domain-specific rubric is more accurate than generic faithfulness metrics, and the native implementation avoids vendor lock-in for a core quality signal.
