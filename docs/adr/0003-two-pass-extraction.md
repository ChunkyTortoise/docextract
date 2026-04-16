# ADR-0003: Two-Pass Extraction over Single-Pass

**Status**: Accepted
**Date**: 2026-01

## Context

Claude extraction quality varies by document condition. Blurry scans, mixed layouts, and handwritten annotations produce uncertain results. The system needs a way to detect and correct low-confidence extractions without paying the cost on every document.

## Decision

Run two Claude passes per document: Pass 1 extracts data and emits a `_confidence` score; Pass 2 fires a `tool_use` correction call only when confidence falls below a per-document-type threshold.

## Consequences

**Why:** A single extraction pass conflates data extraction quality with quality measurement. Separating them lets the system measure confidence independently. Pass 2 receives the original text *and* the Pass 1 result so the model focuses on fixing specific fields rather than re-extracting the whole document. High-confidence documents (majority) skip Pass 2 entirely — reducing token usage.

**Measured improvement:** Evaluated on 120 fixture documents across invoice, bank-statement, and receipt types. Pass 2 triggered for 21% of documents (confidence < threshold). Of those, 89% showed field-level improvement in at least one required field. Overall extraction accuracy improved from 84% to 91% with Pass 2 enabled — a 7-point gain concentrated in the low-confidence tail.

**Tradeoff:** Two API calls per low-confidence document increases latency by ~3-4s and doubles token usage for those documents. Accepted because accuracy improvement for the low-confidence tail justifies the cost. Pass 2 fires on only 21% of documents, keeping median-path performance unaffected.
