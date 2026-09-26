# ADR-0003: Two-Pass Extraction over Single-Pass

**Status**: Accepted
**Date**: 2026-01

## Context

Claude extraction quality varies by document condition. Blurry scans, mixed layouts, and handwritten annotations produce uncertain results. The system needs a way to detect and correct low-confidence extractions without paying the cost on every document.

## Decision

Run two Claude passes per document: Pass 1 extracts data and emits a `_confidence` score; Pass 2 fires a `tool_use` correction call only when confidence falls below a per-document-type threshold.

## Consequences

**Why:** A single extraction pass conflates data extraction quality with quality measurement. Separating them lets the system measure confidence independently. Pass 2 receives the original text *and* the Pass 1 result so the model focuses on fixing specific fields rather than re-extracting the whole document. High-confidence documents (majority) skip Pass 2 entirely - reducing token usage.

**Evaluation status:** No committed live comparison establishes the correction trigger rate or a before/after accuracy gain. The 28-fixture replay does not measure the effect of a second model call.

**Review contract:** Schema-invalid results, including exhausted structured-output retries, are persisted with validation errors and queued for human review. Provider or parser exceptions that produce no result fail the job. Review webhooks use `job.needs_review`.

**Tradeoff:** A second call adds tokens and latency on low-confidence documents. The size of that overhead and any quality improvement require a funded comparison with recorded predictions.
