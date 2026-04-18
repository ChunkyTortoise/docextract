# ADR-0016 — Anthropic Native Citations API for Grounded Extraction

**Status:** Accepted  
**Date:** 2026-04-18

## Context

DocExtract extracts structured fields from documents but previously returned no source attribution — a recruiter or reviewer could not verify which text span in the original document supported a given extracted value. The hand-rolled validator in `app/services/response_validator.py` checks schema conformance but cannot produce character-level provenance.

Anthropic's Citations API (available in `anthropic>=0.49.0`) enables the model to cite specific character spans within a "document" content block, returning `CitationCharLocation` objects with `start_char_index` / `end_char_index` into the original text.

## Decision

Add a `citations: bool = False` parameter to `extract()`. When `True`:

1. Run the normal two-pass extraction to get the structured result.
2. Run a **citation grounding pass** using the raw Anthropic client (not instructor-wrapped) with the document passed as a `"document"` content block with `citations: {"enabled": True}`.
3. Parse `content[*].citations` from the response; match each `CitationCharLocation` to its extracted field via value-matching heuristic in `_match_citation_to_field`.
4. Return a `CitationGrounding` object (new schema in `app/schemas/citations.py`) attached to `ExtractionResult.grounding`.

The grounding pass is a separate API call, not inline with extraction, to avoid coupling the structured-output/instructor flow with the document-block format requirement of Citations.

## Consequences

### Benefits
- Each extracted field can be traced to a source character span — interview-verifiable and useful in the Streamlit review UI.
- `CitationGrounding.grounded_fields` / `ungrounded_fields` measure how many fields were successfully anchored.
- Enables a "citation coverage %" metric alongside F1 in the quality dashboard.

### Trade-offs
- **Extra API call** per document when `citations=True` — approximately +40% latency and cost for that operation. Disabled by default; opt-in per request.
- **Heuristic field matching**: current implementation matches by substring — will be incorrect for numeric fields shared between multiple spans (e.g., same amount appearing in subtotal and total). A future iteration can pass the field-to-span mapping as a structured instruction.
- **Instructor incompatibility**: the "document" block type required for citations cannot be injected through instructor's `response_model` flow. The grounding pass uses the raw client.

## Alternatives considered

- **Inline tool-use grounding**: ask the extractor model to return citations inline using tool_use — would require restructuring the extraction prompt significantly and loses instructor's retry/validation benefits.
- **Post-hoc regex anchoring**: find extracted values in the document via regex — simpler but breaks on reformatted or OCR-normalized text; no character-offset guarantee.
