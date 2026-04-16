# ADR-0013: instructor Library over Manual JSON Parsing

**Status**: Accepted
**Date**: 2026-04

## Context

DocExtract's Claude extraction pass receives structured document data as a JSON object. The original implementation parsed this manually: call Claude, strip markdown fences, `json.loads()`, handle parse errors, validate required fields against the schema class. This approach had several failure modes: truncated JSON, unescaped characters, and Claude occasionally emitting explanatory prose before the JSON block.

## Decision

Use the `instructor` library to wrap the Anthropic client for Pass 1 extraction when a Pydantic schema class is known. Pass `response_model=schema_class, max_retries=3` to `client.messages.create()`. Fall back to the manual JSON path when no schema class is registered for the document type.

## Alternatives Considered

- **Continue with manual JSON parsing + regex fence-stripping**: Simple, no new dependency. Fails silently on malformed output; requires bespoke repair logic for each new document type.
- **Outlines / Guidance**: Grammar-constrained decoding for open-source models. Does not support Anthropic's hosted API.
- **Tool-use / function-calling only**: Already used for Pass 2 correction calls. Pass 1 with `tool_use` adds ~20% prompt overhead and complicates the two-pass handoff.

## Consequences

**Why:** `instructor` handles retry logic, JSON repair, and Pydantic validation in a single call. `max_retries=3` means transient malformed responses are retried before surfacing an error. The typed response from `response.model_dump()` replaces manual parsing and eliminates the fence-stripping regex. Schema validation errors become `InstructorRetryError`, which the extraction pipeline catches and converts to `schema_valid=False` with `confidence=0.0` — a clean signal for HITL escalation.

**Tradeoff:** Adds a dependency (`instructor>=1.0`) and couples extraction to instructor's release cadence. The fallback raw-JSON path remains active for unregistered document types, so the dependency is not hard-required for all extractions. If instructor's API changes, the impact is contained to `claude_extractor.py`.
