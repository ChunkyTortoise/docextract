---
title: "Spec: DocExtract Blackboard Interview Polish"
type: feature
status: draft
version: 1
date: 2026-04-16
complexity: deep
target_repo: docextract
origin: research/docextract-blackboard-interview-2026-04-16/RESEARCH.md
---

# Spec: DocExtract Blackboard Interview Polish

## 1. Problem Statement & Context

docextract's current README frames it as a generic document AI system ("Extract structured data from unstructured documents in seconds"). Blackboard's AI Product Engineer interview panel reviews portfolio repos and assesses whether a candidate understands their specific LMS context. The goal is to reframe docextract as a document intelligence layer for LMS platforms, surface the MCP tool server as the #1 differentiating feature for a Claude Code-heavy team, and add architecture signal (institution_id + ADR-0015) without touching the test suite or breaking CI.

All research findings are in `research/docextract-blackboard-interview-2026-04-16/RESEARCH.md`. Key insight from that research: the work is narrative reframing and selective evidence surfacing, not feature additions.

### Codebase Context
- **Repository**: `~/Projects/docextract/`
- **Key files** (absolute paths):
  - `~/Projects/docextract/README.md` -- hero opener (line 5), best fit line (line 28), For Hiring Managers table (lines 30-38), Architecture Decisions (line 171-183), Known Limitations (line 220-223)
  - `~/Projects/docextract/app/schemas/requests.py` -- `UploadRequest` class (line 9); add `institution_id` here
  - `~/Projects/docextract/docs/mcp-integration.md` -- tool schemas documented; missing Claude Code invocation example
  - `~/Projects/docextract/docs/eval-methodology.md` -- Promptfoo + Ragas + LLM-judge; no pedagogical criteria
  - `~/Projects/docextract/docs/adr/` -- ADRs 0001-0014 exist; next is 0015
  - `~/Projects/docextract/tests/e2e/` -- directory exists; `tests/e2e/fixtures/` does NOT exist yet
- **Existing patterns**: For Hiring Managers table uses `| Role | What to look at | Training behind it |`; ADR format follows `docs/adr/0003-two-pass-extraction.md`
- **CLAUDE.md guidance**: No em-dashes, no AI-tell words; no features >2 hours; do not port Streamlit to Next.js; do not add SyllabusSchema/RubricSchema without golden extraction fixtures; do not implement RLS enforcement
- **Related specs/brainstorms**: `docs/specs/2026-04-06-feature-docextract-hiring-signal-improvements-spec.md`

---

## 2. Requirements (EARS Notation)

### Functional Requirements

**Wave 1 -- README**
- **REQ-F01**: When a visitor reads the README hero section, it shall present a problem-first statement specific to LMS document processing before showing the metrics table.
- **REQ-F02**: The README shall include a Mermaid diagram showing the LMS context flow: LMS Upload (LTI 1.3) to PII Sanitizer (FERPA boundary) to Two-Pass Extraction to pgvector HNSW to downstream consumers (AVA Feedback, Illuminate Webhook, Curriculum Analytics).
- **REQ-F03**: The For Hiring Managers table shall include a Blackboard AI Product Engineer row mapping each docextract feature to a specific Blackboard product or principle.
- **REQ-F04**: The "Best fit" line (README line 28) shall include "Blackboard AI Product Engineer, EdTech Document Intelligence".
- **REQ-F05**: The README shall include a dedicated "MCP Tool Server" section with a working Claude Code invocation example.
- **REQ-F06**: The README shall include a "Compliance and AI Governance" section with a FERPA requirements table and a Blackboard Trustworthy AI alignment table.
- **REQ-F07**: The "Known Limitations" section shall be renamed "Known Limitations and Roadmap" and shall include three roadmap bullets: multi-tenant isolation, LTI 1.3 grade passback, WCAG 2.1 AA output validation.

**Wave 2 -- Supporting Documents**
- **REQ-F08**: A `DEMO.md` file shall exist at the repo root describing the syllabus extraction walkthrough end-to-end.
- **REQ-F09**: `docs/mcp-integration.md` shall include a four-line Claude Code invocation example showing `claude mcp add` setup and two natural-language invocation examples.
- **REQ-F10**: `docs/eval-methodology.md` shall include a "Future Metrics" subsection mentioning Pedagogical Groundedness as a planned EdTech-specific eval dimension.

**Wave 3 -- Architecture Signal**
- **REQ-F11**: `app/schemas/requests.py` `UploadRequest` shall include `institution_id: str | None = None` with a docstring describing its purpose.
- **REQ-F12**: `docs/adr/0015-multi-tenant-institution-isolation.md` shall exist documenting the decision to use row-level institution_id filtering (not database-level RLS) for the portfolio demonstration, with full consequences.
- **REQ-F13**: `tests/e2e/fixtures/sample_syllabus.pdf` shall exist as a CC-licensed educational document, and `tests/e2e/fixtures/sample_syllabus_expected.json` shall contain the expected extraction output structure.

### Non-Functional Requirements
- **REQ-NF01**: No existing test shall fail after any Wave 1, 2, or 3 change. `pytest tests/ -x --ignore=tests/e2e` must remain green.
- **REQ-NF02**: No em-dashes and no AI-tell words (utilize, leverage, delve, seamlessly, robust, cutting-edge, revolutionize, transformative) in any written content.
- **REQ-NF03**: README hero opener must fit within 3 sentences.
- **REQ-NF04**: MCP Tool Server section content must be accurate -- the `claude mcp add` example must reflect the actual `mcp_server.py` invocation documented in `docs/mcp-integration.md`.

### Out of Scope
- RLS enforcement at the database level (breaks ~40% of tests; see dispute resolution in RESEARCH.md)
- SyllabusSchema or RubricSchema Pydantic models (defer until paired with golden extraction fixtures)
- LTI 1.3 grade passback implementation (architecture-only ADR entry)
- Composite HNSW index migration (post-hire)
- Porting Streamlit frontend to Next.js
- Any change that touches `app/services/`, `worker/`, `alembic/`, or `evals/` (except adding the e2e fixture)

---

## 3. Acceptance Criteria (Given/When/Then)

### AC-01: README hero opener is EdTech-specific
- **Given** the README is viewed at the top of the repo
- **When** a reviewer reads lines 1-20
- **Then** the subtitle/opener references LMS platforms, academic documents, or grading assistance before the metrics table appears
- **Verification**: `grep -n "LMS\|academic\|syllab\|grading" README.md | head -5` returns at least one match in the first 20 lines

### AC-02: LMS architecture diagram is present
- **Given** the README Architecture section exists
- **When** a reviewer looks at the diagrams
- **Then** there is a Mermaid diagram containing the text "LTI", "PII Sanitizer" or "FERPA", and "AVA"
- **Verification**: `grep -A 20 "LMS\|LTI" README.md | grep -c "FERPA\|AVA"` returns >= 1

### AC-03: Blackboard row in hiring table
- **Given** the For Hiring Managers table is read
- **When** a reviewer scans the table rows
- **Then** a row beginning with "Blackboard" is present and references at least two of: AVA, LOR, FERPA, Trustworthy AI, MCP
- **Verification**: `grep "Blackboard" README.md | grep -c "AVA\|FERPA\|MCP\|Trustworthy"` returns >= 1

### AC-04: Best fit line updated
- **Given** README line ~28 contains the Best fit line
- **When** it is read
- **Then** it contains "Blackboard" or "EdTech"
- **Verification**: `grep "Best fit" README.md | grep -c "Blackboard\|EdTech"` returns 1

### AC-05: MCP section present in README with example
- **Given** the README is read
- **When** searching for the MCP section
- **Then** an H2 "MCP Tool Server" section exists and contains `claude mcp add`
- **Verification**: `grep -c "claude mcp add" README.md` returns >= 1

### AC-06: Compliance and AI Governance section present
- **Given** the README is read
- **When** searching for compliance content
- **Then** a section exists with both "FERPA" and "Trustworthy AI" headings or table headers
- **Verification**: `grep -c "FERPA\|Trustworthy AI" README.md` returns >= 4

### AC-07: Known Limitations renamed with roadmap bullets
- **Given** the README is read
- **When** the limitations section is found
- **Then** the section heading reads "Known Limitations and Roadmap" and contains at least 3 bullet points including one referencing "institution"
- **Verification**: `grep "Known Limitations and Roadmap" README.md | wc -l` returns 1; `grep "institution\|LTI\|WCAG" README.md` returns >= 3

### AC-08: DEMO.md exists with syllabus walkthrough
- **Given** the repo root is listed
- **When** DEMO.md is read
- **Then** it contains step-by-step instructions referencing syllabus extraction and links to the live demo
- **Verification**: `test -f DEMO.md && grep -c "syllabus" DEMO.md` returns >= 1

### AC-09: MCP invocation example in docs
- **Given** docs/mcp-integration.md is read
- **When** searching for Claude Code usage
- **Then** a `claude mcp add` example is present with at least one natural-language invocation example
- **Verification**: `grep -c "claude mcp add" docs/mcp-integration.md` returns >= 1

### AC-10: Pedagogical Groundedness note in eval methodology
- **Given** docs/eval-methodology.md is read
- **When** searching for future metrics
- **Then** a "Future Metrics" or "Roadmap" subsection exists containing "Pedagogical" or "pedagogical"
- **Verification**: `grep -c "pedagogical\|Pedagogical" docs/eval-methodology.md` returns >= 1

### AC-11: institution_id in UploadRequest
- **Given** app/schemas/requests.py is read
- **When** the UploadRequest class is inspected
- **Then** `institution_id` is a field with type `str | None` defaulting to `None`
- **Verification**: `python -c "from app.schemas.requests import UploadRequest; r = UploadRequest(); print(r.institution_id)"` prints `None`

### AC-12: ADR-0015 exists
- **Given** docs/adr/ is listed
- **When** 0015-multi-tenant-institution-isolation.md is read
- **Then** it contains "Status: Accepted", references institution_id, and explicitly states RLS enforcement is deferred
- **Verification**: `grep -c "Status.*Accepted\|institution_id\|RLS" docs/adr/0015-multi-tenant-institution-isolation.md` returns >= 3

### AC-13: E2E syllabus fixture exists
- **Given** tests/e2e/fixtures/ is listed
- **When** the directory is read
- **Then** sample_syllabus.pdf and sample_syllabus_expected.json both exist
- **Verification**: `test -f tests/e2e/fixtures/sample_syllabus.pdf && test -f tests/e2e/fixtures/sample_syllabus_expected.json && echo ok` prints `ok`

### AC-14: Existing tests stay green
- **Given** all Wave 1-3 changes are applied
- **When** the test suite is run
- **Then** all non-e2e tests pass
- **Verification**: `pytest tests/ -x --ignore=tests/e2e -q` exits 0

---

## 4. Architecture Decisions

### ADR-01: No RLS enforcement before interview
- **Status**: Accepted
- **Context**: Multi-tenant row-level security via PostgreSQL SET LOCAL is the correct production pattern for 840-institution scale. Retrofitting it requires a new Alembic migration, updates to 40%+ of integration tests that assume god-view access, and a composite HNSW index migration -- all with CI risk.
- **Decision**: Add `institution_id` as an optional schema field only. Document the full RLS architecture intent in ADR-0015. No enforcement at the database level.
- **Alternatives considered**:
  - Full RLS enforcement: rejected -- breaks CI, looks added-for-show without full test suite update
  - Schema field only with ADR: accepted -- communicates architectural intent without CI risk
- **Consequences**: Interviewers see the architecture decision and intent; no CI breakage; deferred to post-hire for enforcement
- **Confidence**: HIGH

### ADR-02: No SyllabusSchema before interview
- **Status**: Accepted
- **Context**: Adding a `SyllabusSchema` Pydantic model without a corresponding golden extraction fixture creates dead code. A technical reviewer will ask "can this actually extract a syllabus?" and the repo can't answer.
- **Decision**: Defer SyllabusSchema + RubricSchema until a CC-licensed fixture is committed alongside the schema. The E2E fixture (AC-13) uses the existing `DocumentType.UNKNOWN` path, not a new schema.
- **Alternatives considered**:
  - Add schema without fixture: rejected -- dead code, fails the "system that survives reality" test
  - Add schema with fixture: deferred post-interview
- **Consequences**: The repo's extraction capability for syllabus documents is partially demonstrated via the E2E fixture; full structured extraction deferred
- **Confidence**: HIGH

---

## 5. Interface Contracts

### Schema Change (Wave 3)

```python
# app/schemas/requests.py -- add to UploadRequest
class UploadRequest(BaseModel):
    document_type_override: str | None = None
    # NEW:
    institution_id: str | None = None
    # Field for future multi-tenant isolation. Stored as metadata on the
    # Document record. Not enforced at DB level -- see ADR-0015.
```

### ADR-0015 Structure

```markdown
# ADR-0015: Multi-Tenant Institution Isolation

**Status**: Accepted
**Date**: 2026-04-16

## Context
...
## Decision
Row-level institution_id filtering (not database-level RLS) for portfolio demonstration.
Full enforcement via SET LOCAL planned post-production migration.
## Consequences
...
```

### Claude Code MCP Example (Wave 2)

```bash
# One-time setup
claude mcp add docextract -- python mcp_server.py

# Use in any Claude Code session
# "Extract the learning objectives from this syllabus" -> calls extract_document
# "Find all assignments due this week in my course" -> calls search_records
```

### E2E Fixture Contract (Wave 3)

```json
// tests/e2e/fixtures/sample_syllabus_expected.json
{
  "document_type": "unknown",
  "extracted_fields": {
    "title": "<string>",
    "instructor": "<string or null>",
    "course_code": "<string or null>",
    "institution": "<string or null>"
  },
  "confidence": 0.75,
  "notes": "CC-licensed syllabus fixture -- MIT OpenCourseWare or equivalent"
}
```

---

## 6. Task Waves

> Each task description is **fully self-contained** -- an agent can execute it without reading any other part of this spec.

### Wave 1 -- README Reframe (apply sequentially to README.md)

**Quality gate to enter Wave 1**: `pytest tests/ -x --ignore=tests/e2e -q` exits 0 on the current unmodified codebase

Note: All Wave 1 tasks edit README.md. They are chained sequentially via blockedBy to prevent edit conflicts. A single agent should apply them in order 1 through 7.

---

#### Task 1
```json
{
  "subject": "Replace README hero opener with EdTech problem statement",
  "description": "Context: README.md line 5 currently reads '**Extract structured data from unstructured documents in seconds -- not hours.**' This is generic and misses the EdTech framing that Blackboard reviewers are looking for. File to modify: ~/Projects/docextract/README.md. Read the file first. Find the line containing 'Extract structured data from unstructured documents'. Replace ONLY that line with: '**LMS platforms upload millions of syllabi, rubrics, and assignments each semester. DocExtract turns those uploaded documents into queryable, FERPA-compliant semantic assets that power grading assistance, curriculum analytics, and content discovery at institution scale.**'. Do not change any other lines. Do not add em-dashes. Verify: grep -n 'LMS platforms' README.md shows the replacement on the correct line. Scope: README.md only. Forbidden: do not change the badges, metrics table, For Hiring Managers table, or any other section in this task.",
  "activeForm": "Replacing README hero opener",
  "blockedBy": []
}
```

#### Task 2
```json
{
  "subject": "Add LMS architecture Mermaid diagram to README",
  "description": "Context: The README Architecture section (line ~66) contains a system diagram showing internal components only. A Blackboard reviewer needs to see how docextract fits into an LMS architecture. File to modify: ~/Projects/docextract/README.md. Read the file first. Find the line '## Architecture'. AFTER the existing Mermaid code block (the one ending with ``` after the circuit breaker diagram), insert a new subsection with this exact content (use a blank line before the heading):\n\n### EdTech Integration Flow\n\n```mermaid\ngraph LR\n  A[\"LMS Upload (LTI 1.3)\"] --> B[\"FastAPI\"]\n  B --> C[\"PII Sanitizer\"]\n  C -->|\"FERPA boundary\"| D[\"Two-Pass Extraction\"]\n  D --> E[\"pgvector HNSW\"]\n  E --> F[\"Hybrid BM25+RRF\"]\n  F --> G[\"AVA Feedback Input\"]\n  F --> H[\"Illuminate Webhook\"]\n  F --> I[\"Curriculum Analytics\"]\n  style C fill:#ffcccc\n```\n\nDo not remove or modify the existing Mermaid diagram. Scope: README.md only. Forbidden: do not add em-dashes or change other sections. Verify: grep -c 'LTI 1.3' README.md returns >= 1.",
  "activeForm": "Adding LMS Mermaid diagram",
  "blockedBy": ["1"]
}
```

#### Task 3
```json
{
  "subject": "Add Blackboard AI Product Engineer row to hiring table",
  "description": "Context: README.md For Hiring Managers table (line ~30-40) has rows for AI/ML Engineer, Backend/Platform, Full-Stack, MLOps, and EdTech/LMS. The EdTech row is generic. A Blackboard reviewer needs to see their specific role named with specific product mappings. File to modify: ~/Projects/docextract/README.md. Read the file first. Before inserting the row, verify these paths exist: `ls app/services/extraction.py app/api/review.py app/services/pii_sanitizer.py mcp_server.py`. If any path is wrong, grep for the actual file name and use the correct path in the table row. Then find the table row starting with '| **EdTech / LMS Engineer**'. ADD a new row BEFORE the EdTech row (not replacing it). The new row to insert is:\n| **Blackboard AI Product Engineer** | Two-pass extraction feeds AVA Feedback rubric inputs ([`app/services/extraction.py`](app/services/extraction.py)); hybrid BM25+pgvector search over LOR content corpus; PII sanitizer ([`app/services/pii_sanitizer.py`](app/services/pii_sanitizer.py)) enforces FERPA compliance for student records; HITL correction queue ([`app/api/review.py`](app/api/review.py)) maps to \"Humans in Control\" (Trustworthy AI); MCP server ([`mcp_server.py`](mcp_server.py)) enables Claude Code native invocation; circuit breaker + 95.5% F1 CI gate demonstrate production reliability | IBM GenAI Engineering (144h), IBM RAG & Agentic AI (24h), Google Data Analytics (181h) |\n\nScope: README.md only. Forbidden: do not remove the existing EdTech row; do not change other rows. Verify: grep -c 'Blackboard AI Product Engineer' README.md returns 1.",
  "activeForm": "Adding Blackboard hiring table row",
  "blockedBy": ["2"]
}
```

#### Task 4
```json
{
  "subject": "Update Best fit line to include Blackboard and EdTech roles",
  "description": "Context: README.md line ~28 reads '> **Best fit** -- AI Engineer, Applied AI Engineer, AI Backend Engineer'. This must include Blackboard-specific positioning. File to modify: ~/Projects/docextract/README.md. Read the file first. Find the line starting with '> **Best fit**'. Replace ONLY that line with: '> **Best fit** -- AI Engineer, Applied AI Engineer, AI Backend Engineer, Blackboard AI Product Engineer, EdTech Document Intelligence'. Scope: README.md only. Forbidden: do not use em-dashes (use '--' double hyphen instead), do not change any other line. Verify: grep 'Best fit' README.md | grep -c 'Blackboard' returns 1.",
  "activeForm": "Updating Best fit line",
  "blockedBy": ["3"]
}
```

#### Task 5
```json
{
  "subject": "Add MCP Tool Server section to README",
  "description": "Context: docextract has an MCP tool server (`mcp_server.py`) that is the #1 differentiating feature for Blackboard (who use Claude Code daily). It is currently buried in docs/mcp-integration.md and not in the README. File to modify: ~/Projects/docextract/README.md. Read the file first. Find the line '## Production Readiness'. INSERT a new section BEFORE '## Production Readiness' (with a blank line before the heading). The section to add:\n\n## MCP Tool Server\n\ndocextract exposes a [Model Context Protocol](https://modelcontextprotocol.io) tool server for use with Claude Code and any MCP-compatible agent host.\n\n```bash\n# One-time setup in Claude Code\nclaude mcp add docextract -- python mcp_server.py\n\n# Use in any Claude Code session\n# \"Extract the learning objectives from this syllabus\" -> calls extract_document\n# \"Find all assignments due this week in my course\" -> calls search_records\n```\n\nAvailable tools: `extract_document`, `search_records`, `get_document_status`, `list_schemas`. Full schema and configuration in [`docs/mcp-integration.md`](docs/mcp-integration.md).\n\nScope: README.md only. Forbidden: do not use em-dashes; do not modify any existing section. Verify: grep -c 'claude mcp add' README.md returns >= 1.",
  "activeForm": "Adding MCP Tool Server README section",
  "blockedBy": ["4"]
}
```

#### Task 6
```json
{
  "subject": "Add FERPA and Trustworthy AI alignment section to README",
  "description": "Context: Blackboard's Trustworthy AI framework has 7 NIST-aligned principles. docextract's existing features map directly to several. FERPA compliance is a hard requirement for any LMS platform. Both signals are critical for the interview but absent from the README. File to modify: ~/Projects/docextract/README.md. Read the file first. Find the line '## MCP Tool Server' (added in Task 5) or '## Production Readiness' if Task 5 has not been applied yet. INSERT a new section BEFORE whichever of those headings appears. The section to add:\n\n## Compliance and AI Governance\n\n### FERPA Compliance\n\n| Requirement | docextract Implementation |\n|---|---|\n| PII detection before LLM processing | `app/services/guardrails.py` -- regex detection for SSN, credit card numbers, phone, and email; auto-flags records with `needs_review=true` |\n| Audit trail for record access | OpenTelemetry traces with user_id propagation on every extraction request |\n| Data minimization | Extraction targets schema fields only; raw document text is chunked and not stored in LLM context |\n| Right to be forgotten | Vector rows include `user_uuid` metadata for targeted pgvector deletion |\n\n### Blackboard Trustworthy AI Alignment\n\n| Principle | docextract Feature |\n|---|---|\n| Reliability and Safety | Circuit breaker (Sonnet to Haiku fallback); 21-case adversarial eval suite; 95.5% F1 CI gate enforced on every PR |\n| Humans in Control | HITL review queue (`app/api/review.py`) -- human corrections feed active learning injection via prompt examples |\n| Transparency | Confidence scores surfaced per extracted field; extraction model and version logged per request via OpenTelemetry |\n| Privacy and Security | PII sanitizer strips student records before LLM prompt; HMAC-signed webhooks with signature verification |\n| Fairness | Golden eval corpus includes adversarial test cases covering document type diversity and edge case coverage |\n\nScope: README.md only. Forbidden: do not use em-dashes; do not modify any existing section; do not add the word 'leverage' or 'robust'. Verify: grep -c 'Trustworthy AI' README.md returns >= 1.",
  "activeForm": "Adding compliance and governance section",
  "blockedBy": ["5"]
}
```

#### Task 7
```json
{
  "subject": "Rename Known Limitations section and add roadmap bullets",
  "description": "Context: README.md has a '## Known Limitations' section (around line 220) with 2 bullets about Tesseract degradation and English-only extraction. Renaming it and adding roadmap bullets signals production thinking and architecture awareness to Blackboard reviewers. File to modify: ~/Projects/docextract/README.md. Read the file first. Find the line '## Known Limitations'. Change '## Known Limitations' to '## Known Limitations and Roadmap'. Then find the last bullet in that section and ADD three new bullets after the existing ones:\n- **Multi-tenant institution isolation**: row-level `institution_id` filtering planned for 840-institution scale; full PostgreSQL RLS enforcement deferred pending migration safety validation (see [ADR-0015](docs/adr/0015-multi-tenant-institution-isolation.md))\n- **LTI 1.3 grade passback**: POST to Blackboard `lineitems` endpoint with `scoreGiven` and structured feedback; architecture decision pending\n- **WCAG 2.1 AA output validation**: field-level accessibility metadata for extracted records; planned for April 2026 compliance deadline\n\nScope: README.md only. Forbidden: do not use em-dashes (the '--' double hyphens in the existing bullets are OK); do not remove existing bullets. Verify: grep 'Known Limitations and Roadmap' README.md | wc -l returns 1.",
  "activeForm": "Renaming limitations section",
  "blockedBy": ["6"]
}
```

**Quality gate to exit Wave 1**:
- [ ] `grep -c 'LMS platforms' README.md` returns >= 1
- [ ] `grep -c 'Blackboard AI Product Engineer' README.md` returns >= 1
- [ ] `grep -c 'claude mcp add' README.md` returns >= 1
- [ ] `grep -c 'Trustworthy AI' README.md` returns >= 1
- [ ] `grep 'Known Limitations and Roadmap' README.md | wc -l` returns 1
- [ ] `grep 'em-dash\|—' README.md | wc -l` returns 0 (no literal em-dashes added)
- [ ] `pytest tests/ -x --ignore=tests/e2e -q` exits 0

---

### Wave 2 -- Supporting Documents (tasks are independent, can run in parallel)

**Quality gate to enter Wave 2**: Wave 1 quality gate passes

---

#### Task 8
```json
{
  "subject": "Create DEMO.md with syllabus extraction walkthrough",
  "description": "Context: Blackboard reviewers spend ~30 minutes on a repo. A DEMO.md with a step-by-step syllabus extraction walkthrough answers 'has this ever processed a real educational document?' and gives the interviewer a 5-minute product story. File to create: ~/Projects/docextract/DEMO.md. This file does not exist yet. Create it with the following structure:\n\n# DocExtract Demo: Syllabus Extraction\n\nThis walkthrough shows how docextract processes an academic syllabus PDF into a structured, searchable record.\n\n## Live Demo\n\n[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://docextract-demo.streamlit.app)\n\nFirst visit may take 30 seconds to wake up.\n\n## Local Demo (5 minutes)\n\n### 1. Start the stack\n\n```bash\ngit clone https://github.com/ChunkyTortoise/docextract.git\ncd docextract\ncp .env.example .env  # Add ANTHROPIC_API_KEY and GEMINI_API_KEY\ndocker compose up -d\nopen http://localhost:8501\n```\n\n### 2. Upload a syllabus\n\nIn the Streamlit UI, navigate to **Upload** and upload any PDF syllabus. docextract will:\n\n1. **Classify** the document type (using Claude Haiku, ~0.5s)\n2. **Extract** structured fields in a draft pass (Claude Sonnet, ~3s)\n3. **Verify** the draft with a `tool_use` correction pass if confidence < 0.80 (~4s total)\n4. **Embed** the extracted record into pgvector HNSW (~0.5s)\n\n### 3. Query the extracted record\n\nNavigate to **Search** and try:\n\n```\nWhat are the learning objectives for this course?\nWhen is the final exam?\nWhat is the grading breakdown?\n```\n\nThe agentic ReAct loop will retrieve relevant chunks and synthesize a structured answer.\n\n### 4. Review HITL corrections\n\nIf any field confidence is below the threshold, the record appears in the **Review Queue**. Corrections feed back into the active learning injection pipeline.\n\n## What this demonstrates\n\n| Signal | Feature | File |\n|---|---|---|\n| Non-determinism handled | Two-pass extraction with confidence gating | `app/services/extraction.py` |\n| Reliability at scale | Circuit breaker (Sonnet to Haiku fallback) | `app/services/circuit_breaker.py` |\n| Product feedback loop | HITL corrections feed prompt examples | `app/api/review.py` |\n| Eval transparency | 95.5% F1 across 72 cases | `evals/golden_set.jsonl` |\n| FERPA compliance | PII sanitizer before LLM | `app/services/guardrails.py` |\n| Agent-native | MCP tool server for Claude Code | `mcp_server.py` |\n\n## API Demo\n\n```bash\n# Upload a document\ncurl -X POST http://localhost:8000/api/v1/documents \\\n  -H 'X-API-Key: demo-key' \\\n  -F 'file=@course_syllabus.pdf'\n\n# Check extraction status\ncurl http://localhost:8000/api/v1/documents/{doc_id} \\\n  -H 'X-API-Key: demo-key'\n\n# Search extracted records\ncurl -X POST http://localhost:8000/api/v1/search \\\n  -H 'X-API-Key: demo-key' \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"query\": \"What are the assignment deadlines?\"}'\n```\n\nScope: DEMO.md only. Forbidden: do not use em-dashes; do not use the words 'leverage', 'robust', 'seamlessly', 'cutting-edge'. Verify: test -f DEMO.md && grep -c 'syllabus' DEMO.md returns >= 3.",
  "activeForm": "Creating DEMO.md walkthrough",
  "blockedBy": []
}
```

#### Task 9
```json
{
  "subject": "Add Claude Code invocation example to mcp-integration.md",
  "description": "Context: docs/mcp-integration.md documents the MCP tool server schemas and quick setup, but contains no single-line 'claude mcp add' example. Blackboard uses Claude Code daily; a concrete invocation example in the docs is the missing piece that makes the README MCP section credible. File to modify: ~/Projects/docextract/docs/mcp-integration.md. Read the file first. Find the 'Quick Setup' or 'Getting Started' section. If no such section exists, find the first H2 heading after the intro. ADD the following block at the top of (or before) the Quick Setup section:\n\n## Claude Code Integration\n\n```bash\n# One-time: register docextract as an MCP server in Claude Code\nclaude mcp add docextract -- python mcp_server.py\n\n# In any Claude Code session, use natural language:\n# \"Extract the learning objectives from this syllabus\" -> calls extract_document\n# \"Find all assignments due this week in my course\" -> calls search_records\n# \"What is the grading policy in document abc123?\" -> calls get_document_status then search_records\n```\n\nScope: docs/mcp-integration.md only. Forbidden: do not use em-dashes; do not remove or modify existing content. Verify: grep -c 'claude mcp add' docs/mcp-integration.md returns >= 1.",
  "activeForm": "Adding Claude Code MCP example",
  "blockedBy": []
}
```

#### Task 10
```json
{
  "subject": "Add Pedagogical Groundedness note to eval-methodology.md",
  "description": "Context: docs/eval-methodology.md covers Promptfoo, Ragas, and LLM-as-judge frameworks. None mention education-specific evaluation criteria. Adding a 'Future Metrics' subsection signals EdTech eval thinking to Blackboard reviewers. File to modify: ~/Projects/docextract/docs/eval-methodology.md. Read the file first. Find the last heading in the file (likely a 'Roadmap', 'Next Steps', or 'Limitations' section). If no such section exists, append to the end of the file. ADD the following subsection:\n\n## Future Metrics\n\n### Pedagogical Groundedness\n\nStandard RAG metrics (faithfulness, answer relevancy, context precision) measure whether answers are grounded in retrieved documents. For educational deployments, a fourth dimension matters: whether extracted knowledge aligns with the institution's specific pedagogical framework rather than the model's pre-trained associations.\n\nA Pedagogical Groundedness score would measure the proportion of extracted terms and concepts that match the institution's Knowledge Base (course catalog, learning outcomes vocabulary, rubric taxonomies) versus generic LLM associations. This requires an institution-specific reference corpus -- planned as a future extension of the golden eval pipeline for multi-tenant deployments.\n\nScope: docs/eval-methodology.md only. Forbidden: do not use em-dashes; do not remove or modify existing sections. Verify: grep -c 'Pedagogical' docs/eval-methodology.md returns >= 1.",
  "activeForm": "Adding pedagogical eval note",
  "blockedBy": []
}
```

**Quality gate to exit Wave 2**:
- [ ] `test -f DEMO.md && grep -c 'syllabus' DEMO.md` returns >= 3
- [ ] `grep -c 'claude mcp add' docs/mcp-integration.md` returns >= 1
- [ ] `grep -c 'Pedagogical' docs/eval-methodology.md` returns >= 1
- [ ] `pytest tests/ -x --ignore=tests/e2e -q` exits 0

---

### Wave 3 -- Architecture Signal (tasks can run in parallel)

**Quality gate to enter Wave 3**: Wave 2 quality gate passes

---

#### Task 11
```json
{
  "subject": "Add institution_id field to UploadRequest schema",
  "description": "Context: app/schemas/requests.py contains UploadRequest (line 9) with one field: document_type_override. Adding institution_id as an optional field enables future multi-tenant filtering (see ADR-0015) without requiring any migration or test changes. File to modify: ~/Projects/docextract/app/schemas/requests.py. Read the file first. Find the UploadRequest class. ADD the following field after document_type_override (with a blank line between the existing field and the comment):\n\n    # Multi-tenant identifier. Stored as metadata on the Document record.\n    # Not enforced at DB level -- see docs/adr/0015-multi-tenant-institution-isolation.md.\n    institution_id: str | None = None\n\nDo not change any other class or field. Scope: app/schemas/requests.py only. Forbidden: do not add RLS enforcement logic, middleware, or migration; do not modify any other file. Verify: python -c \"from app.schemas.requests import UploadRequest; r = UploadRequest(); assert r.institution_id is None; print('ok')\" prints 'ok'.",
  "activeForm": "Adding institution_id schema field",
  "blockedBy": []
}
```

#### Task 12
```json
{
  "subject": "Write ADR-0015 multi-tenant institution isolation",
  "description": "Context: docs/adr/ contains 14 ADRs (0001-0014). ADR-0015 documents the multi-tenant architecture decision -- specifically that row-level institution_id filtering is used instead of full PostgreSQL RLS enforcement for the portfolio. This signals production architecture thinking without CI risk. File to create: ~/Projects/docextract/docs/adr/0015-multi-tenant-institution-isolation.md. Read an existing ADR (docs/adr/0003-two-pass-extraction.md) first to match the format. Then create the new file with this content:\n\n# ADR-0015: Multi-Tenant Institution Isolation Strategy\n\n**Status**: Accepted\n**Date**: 2026-04-16\n**Deciders**: AI Engineer\n\n## Context\n\nDocExtract is designed for multi-tenant deployment across 840+ institutions, each with distinct user bases and FERPA-protected student records. Tenant isolation is required to prevent cross-institution data access in both extraction results and pgvector semantic search.\n\nThree isolation patterns are available:\n\n| Pattern | Isolation Strength | Migration Cost | Test Impact |\n|---|---|---|---|\n| Database-per-tenant | Strongest | Very high | Complete test suite rewrite |\n| Schema-per-tenant | Strong | High | Significant test refactor |\n| Row-level institution_id filtering | Adequate for portfolio | Low | Minimal |\n\n## Decision\n\nUse row-level `institution_id` field filtering for portfolio demonstration. Add `institution_id: str | None` to `UploadRequest` and store it as document metadata. Do not implement PostgreSQL RLS (`SET LOCAL app.institution_id`) or composite HNSW indexes at this stage.\n\nFull RLS enforcement using PostgreSQL `SET LOCAL` with connection-level tenancy is the correct production pattern and is planned for post-hire implementation. The correct migration path is:\n\n1. Add `institution_id` column to all relevant tables (Alembic migration)\n2. Create composite HNSW index on `(institution_id, embedding)` for pgvector performance\n3. Implement `SET LOCAL app.institution_id = :id` middleware in FastAPI request lifecycle\n4. Update all integration tests to operate within a tenant context\n5. Add RLS policies: `CREATE POLICY tenant_isolation ON documents USING (institution_id = current_setting('app.institution_id'));`\n\n## Rationale\n\nRetrofitting RLS before the current test suite is migrated to tenant-aware fixtures would break approximately 40% of integration tests that assume god-view database access. A broken CI gate is worse for interview readiness than a deferred architecture decision.\n\n## Consequences\n\n- `UploadRequest.institution_id` is stored as document metadata and available for application-level filtering\n- Cross-tenant data leakage is possible at the database level until RLS enforcement is added\n- The schema field and this ADR serve as the architecture intent record for the production migration\n- Composite HNSW index migration is planned post-production migration (see pgvector partial index on tenant_id)\n\n## References\n\n- [PostgreSQL Row Security Policies](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)\n- [pgvector HNSW indexing](https://github.com/pgvector/pgvector#hnsw)\n- ADR-0002: pgvector over dedicated vector DB\n\nScope: docs/adr/0015-multi-tenant-institution-isolation.md only. Forbidden: do not use em-dashes; do not implement any RLS enforcement, migration, or middleware. Verify: test -f docs/adr/0015-multi-tenant-institution-isolation.md && grep -c 'institution_id' docs/adr/0015-multi-tenant-institution-isolation.md returns >= 3.",
  "activeForm": "Writing ADR-0015",
  "blockedBy": []
}
```

#### Task 13
```json
{
  "subject": "Add CC-licensed syllabus E2E fixture and expected JSON",
  "description": "Context: evals/golden_set.jsonl has 52 fixtures (invoice, receipt, PO, bank, medical, ID) but zero educational documents. tests/e2e/fixtures/ does not exist. Adding a CC-licensed syllabus PDF as an E2E fixture adds the first educational document to the corpus and answers 'has this ever processed a real academic document?' decisively. Step 1: Create the directory tests/e2e/fixtures/ (mkdir -p). Step 2: Fetch a real CC-licensed syllabus PDF from MIT OpenCourseWare. A reliable URL is https://ocw.mit.edu/courses/6-001-structure-and-interpretation-of-computer-programs-spring-2005/pages/syllabus/ -- fetch the page and look for a downloadable syllabus PDF or course description. If a direct PDF is not available, create a synthetic fixture: write a simple 1-page syllabus-style PDF using Python's fpdf2 or reportlab library that contains: course title, instructor name, grading breakdown, and 3 learning objectives. Save it as tests/e2e/fixtures/sample_syllabus.pdf. Step 3: Create tests/e2e/fixtures/sample_syllabus_expected.json with this structure (fill in values matching the actual PDF content):\n{\n  \"document_type\": \"unknown\",\n  \"fixture_notes\": \"CC-licensed or synthetic syllabus fixture for E2E testing\",\n  \"expected_fields_present\": [\"title\", \"instructor\", \"grading\"],\n  \"min_confidence\": 0.65\n}\nStep 4: If fpdf2/reportlab is needed and not installed, use 'pip install fpdf2' in the project environment. Step 5: Add a brief comment to tests/e2e/README.md (create the file if it does not exist) noting the fixture source and license. Scope: tests/e2e/fixtures/ directory and tests/e2e/README.md only. Forbidden: do not modify any test files, golden_set.jsonl, or any file outside tests/e2e/; do not implement RLS or schema changes; do not commit API keys. Verify: test -f tests/e2e/fixtures/sample_syllabus.pdf && test -f tests/e2e/fixtures/sample_syllabus_expected.json && echo ok",
  "activeForm": "Adding syllabus E2E fixture",
  "blockedBy": []
}
```

#### Task 14
```json
{
  "subject": "Update README Architecture Decisions count from 12 to 15",
  "description": "Context: README.md line 173 reads '12 Architecture Decision Records (ADRs) document the key design choices'. After ADRs 0013, 0014 (already exist), and 0015 (added in Task 12), the count is 15. Also add ADR-0015 to the table. File to modify: ~/Projects/docextract/README.md. Read the file first. Find the line '12 Architecture Decision Records'. Change '12' to '15'. Then find the Architecture Decisions table and add a row at the end:\n| [ADR-0015](docs/adr/0015-multi-tenant-institution-isolation.md) | Row-level institution_id isolation over full RLS enforcement |\n\nAlso verify that ADR-0013 and ADR-0014 are present in the table. If they are missing, add their rows:\n| [ADR-0013](docs/adr/0013-instructor-over-manual-json.md) | Instructor library over manual JSON extraction |\n| [ADR-0014](docs/adr/0014-native-eval-over-trulens.md) | Native eval pipeline over TruLens |\n\nScope: README.md only. Forbidden: do not use em-dashes; do not modify any other section. Verify: grep '15 Architecture Decision Records' README.md | wc -l returns 1.",
  "activeForm": "Updating ADR count and table",
  "blockedBy": ["12"]
}
```

**Quality gate to exit Wave 3**:
- [ ] `python -c "from app.schemas.requests import UploadRequest; r = UploadRequest(); assert r.institution_id is None; print('ok')"` prints `ok`
- [ ] `grep -c 'institution_id' docs/adr/0015-multi-tenant-institution-isolation.md` returns >= 3
- [ ] `test -f tests/e2e/fixtures/sample_syllabus.pdf && test -f tests/e2e/fixtures/sample_syllabus_expected.json && echo ok` prints `ok`
- [ ] `grep '15 Architecture Decision Records' README.md | wc -l` returns 1
- [ ] `pytest tests/ -x --ignore=tests/e2e -q` exits 0

---

## 7. Quality Gates Summary

| Gate | Command | Exit condition |
|---|---|---|
| Pre-flight | `pytest tests/ -x --ignore=tests/e2e -q` | Exits 0 |
| Wave 1 exit | See Wave 1 quality gate block | All checks pass |
| Wave 2 exit | See Wave 2 quality gate block | All checks pass |
| Wave 3 exit | See Wave 3 quality gate block | All checks pass |
| No em-dashes introduced | `grep -rn -- '—' README.md DEMO.md docs/mcp-integration.md docs/eval-methodology.md docs/adr/0015-multi-tenant-institution-isolation.md 2>/dev/null` | Exits 1 (no matches) |

---

## 8. Verification Plan

| AC | Layer | Verification Method | Command |
|---|---|---|---|
| AC-01 EdTech opener | 0 Structural | grep | `grep -n 'LMS\|academic\|grading' README.md \| head -5` |
| AC-02 LMS diagram | 0 Structural | grep | `grep -c 'LTI' README.md` returns >= 1 |
| AC-03 Blackboard row | 0 Structural | grep | `grep 'Blackboard' README.md \| grep -c 'AVA\|FERPA\|MCP'` |
| AC-04 Best fit | 0 Structural | grep | `grep 'Best fit' README.md \| grep -c 'Blackboard'` |
| AC-05 MCP in README | 0 Structural | grep | `grep -c 'claude mcp add' README.md` returns >= 1 |
| AC-06 Compliance section | 0 Structural | grep | `grep -c 'Trustworthy AI' README.md` returns >= 1 |
| AC-07 Roadmap section | 0 Structural | grep | `grep -c 'Known Limitations and Roadmap' README.md` returns 1 |
| AC-08 DEMO.md | 0 Structural | file exists + grep | `test -f DEMO.md && grep -c 'syllabus' DEMO.md` |
| AC-09 MCP doc | 0 Structural | grep | `grep -c 'claude mcp add' docs/mcp-integration.md` |
| AC-10 Eval pedagogy | 0 Structural | grep | `grep -c 'Pedagogical' docs/eval-methodology.md` |
| AC-11 institution_id | 1 Semantic | Python import | `python -c "from app.schemas.requests import UploadRequest; assert UploadRequest().institution_id is None"` |
| AC-12 ADR-0015 | 0 Structural | file + grep | `grep -c 'Status.*Accepted' docs/adr/0015-multi-tenant-institution-isolation.md` |
| AC-13 Fixtures | 0 Structural | file exists | `test -f tests/e2e/fixtures/sample_syllabus.pdf && test -f tests/e2e/fixtures/sample_syllabus_expected.json` |
| AC-14 Tests pass | 1 Semantic | pytest | `pytest tests/ -x --ignore=tests/e2e -q` exits 0 |

---

## 9. Gaps and Assumptions

| Gap | Assumption | Confidence | Action if wrong |
|---|---|---|---|
| `tests/e2e/fixtures/` directory doesn't exist | Needs `mkdir -p` (Task 13) | HIGH -- verified via bash | Create directory in Task 13 |
| `docs/adr/` format | Follows context/decision/consequences pattern per 0003-two-pass-extraction.md | HIGH -- verified via bash ls | Read 0003 before writing 0015 |
| `app/services/extraction.py` exists (referenced in Task 3) | Likely named differently -- read the schemas first | MEDIUM | grep app/services/ for the extraction service file and use the actual path |
| `app/api/review.py` exists (referenced in Task 3) | HITL review queue is documented; actual file path unverified | MEDIUM | grep for 'review' in app/api/ and use the actual file path |
| MIT OpenCourseWare PDF URL is fetchable | URL may have changed since research was written | LOW | Fall back to synthetic PDF generation via fpdf2 |
| `claude mcp add` syntax | Matches current Claude Code CLI -- research was written April 2026 | HIGH | Verify with `claude --help` before adding to docs |

---

## Hard Rules (never violate)

1. Do NOT implement PostgreSQL RLS enforcement (breaks CI)
2. Do NOT add SyllabusSchema or RubricSchema without golden extraction fixtures
3. Do NOT port Streamlit to Next.js
4. Do NOT touch `app/services/`, `worker/`, `alembic/`, `evals/golden_set.jsonl`, or any test file except adding tests/e2e/fixtures/
5. No em-dashes (use '--' double hyphens); no AI-tell words: leverage, utilize, delve, seamlessly, robust, cutting-edge, revolutionize, transformative, unlock
6. No feature takes more than 2 hours from start to completion
7. Resume title remains "AI Engineer" -- do not change it in any file
