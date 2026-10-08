# ADR-0014: Native LLM-as-Judge Eval over TruLens/RAGAS

**Status**: Accepted
**Date**: 2026-04

## Context

DocExtract needed online quality monitoring: a way to measure extraction accuracy in production without ground-truth labels. The options were a third-party eval framework (TruLens, RAGAS, DeepEval) or a purpose-built LLM-as-judge running as an ARQ task.

## Decision

Use a native `LLMJudge` with extraction rubrics for completeness, field_accuracy, hallucination_absence and format_compliance. The [sampling task](../../worker/judge_tasks.py) evaluates each dimension separately and stores the scores in `eval_log`. The document-processing path enqueues `judge_extraction_sample` when `hash(job_id) % 10 == 0`, targeting approximately one in ten job IDs. The judge is disabled by default (`llm_judge_enabled=False`); when enabled, it tries Gemini first and falls back to Claude. Disabled or failed evaluations currently produce neutral dimension scores in the sampling task, not measured quality verdicts.

## Alternatives Considered

- **TruLens**: Provides prebuilt feedback functions and a dashboard. Requires a separate TruLens server or cloud account, and its feedback functions are designed for RAG pipelines, not structured document extraction. The schema mismatch would require wrapping every extraction call in TruLens instrumentation.
- **RAGAS**: Excellent for RAG faithfulness/context recall metrics. Requires a reference corpus per query. DocExtract has no ground-truth corpus in production. RAGAS metrics are not directly applicable to extraction tasks (field presence, value accuracy).
- **DeepEval**: Requires running a test suite with expected outputs. Useful for offline eval but does not provide online sampling.
- **Promptfoo**: Already integrated for CI golden-file regression testing (`promptfooconfig.yaml`). Not designed for production sampling.

## Consequences

**Why:** A native judge gives full control over the rubric, sampling rate, and storage schema. The 4-dimension rubric maps directly to DocExtract's product requirements: completeness (all required fields present), field_accuracy (values match source), hallucination_absence (no invented data), format_compliance (output matches schema). Scores are stored in `eval_log` with composite as the EWMA input for the Quality Monitor dashboard. Sampling limits the frequency of judge tasks. Actual judge cost, latency and pipeline impact have not been measured in a committed run.

**Tradeoff:** Maintaining the rubric and judge prompts requires engineering effort as document types evolve. Third-party frameworks provide prebuilt rubrics and community support. Accepted for control over extraction-specific criteria and storage. Comparative accuracy against third-party evaluators has not been established.
