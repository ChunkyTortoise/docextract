# AI Governance Framework

This document describes the governance controls built into DocExtract: how the system detects problematic outputs, routes uncertain decisions to humans, maintains audit records, and aligns with regulatory frameworks. It is intended for compliance officers, risk managers, and IT security reviewers.

---

## Summary of Controls

| Control | Mechanism | Location |
|---------|-----------|----------|
| PII detection | Regex scan on every extraction output | `app/services/guardrails.py` |
| Hallucination detection | Grounding check: extracted values vs. source text | `app/services/guardrails.py` |
| Confidence gating | Two-pass extraction with per-field scores | `app/services/claude_extractor.py` |
| Human review routing | Auto-flag records with PII or low confidence | `worker/`, `app/routers/` |
| Audit trail | Append-only `audit_logs` table | `alembic/versions/` |
| Trace sanitization | PII redaction before Langfuse/LangSmith export | `app/services/pii_sanitizer.py` |
| Model versioning | `EXTRACTION_MODELS` env var, tracked per record | `app/services/model_router.py` |
| Eval CI gate | 94.6% accuracy threshold blocks deploy | `tests/eval/` + CI config |
| Adversarial testing | 12 adversarial fixtures, 4 prompt injection | `tests/eval/fixtures/adversarial/` |
| Access control | API key auth, role-based, rate limited | `app/services/`, `app/routers/` |
| Data retention | Configurable `DATA_RETENTION_DAYS`, cascade delete | API + DB schema |

---

## PII Detection Pipeline

**File**: `app/services/guardrails.py`

The `PiiDetector` class runs on every extraction output when `GUARDRAILS_ENABLED=true`. Detection is regex-based: deterministic, zero API cost, runs in under 1ms per record.

### Patterns Detected

| PII Type | Pattern | Example |
|----------|---------|---------|
| Social Security Number | `\d{3}-\d{2}-\d{4}` | 123-45-6789 |
| Credit Card | Luhn-compatible (Visa, MC, Amex, Discover, JCB) | 4111-1111-1111-1111 |
| Phone Number | North American format, multiple separators | (555) 123-4567 |
| Email Address | RFC-compliant | user@example.com |

### Scanning Behavior

The scanner recursively traverses the extracted JSON, including nested objects and arrays. When PII is found in a field:
- A `PiiMatch` is recorded with the field path, PII type, and redacted value (digits replaced with `*`)
- The record is flagged: `needs_review=true`
- The `review_reason` field lists the PII types found
- PII findings are stored in record metadata under `_guardrails`

The `GuardrailResult.passed` attribute is `False` if any PII matches exist. Records that fail guardrails are not automatically deleted — they enter the review queue for human disposition.

### On-Demand Guardrail Runs

Guardrails can be re-run on any record at any time via:

```
GET /api/v1/records/{id}/guardrails
```

This endpoint operates independently of the `GUARDRAILS_ENABLED` flag, allowing ad-hoc audits.

---

## Grounding Checks (Hallucination Detection)

**File**: `app/services/guardrails.py` — `HallucinationChecker` class

After extraction, each string field in the output is validated against the source document text. The check verifies that extracted values did not appear from nowhere (hallucination).

### Check Logic

For each extracted string field:

1. **Full substring match**: If the extracted value appears verbatim (case-insensitive) in the source text, the field is marked `grounded`.
2. **Partial word overlap**: If at least 60% of the value's words appear in the source, the field is marked `partial`.
3. **Below threshold**: Fields with fewer than 60% words grounded are marked `ungrounded` and flagged for review.
4. **Skipped**: Fields shorter than 3 characters are skipped (e.g., codes, single-letter values).

Grounding results are stored per-field in the `GuardrailResult`. Ungrounded fields are a signal for human review, not automatic rejection — some legitimate extractions (e.g., inferred dates, normalized formats) may not match source text exactly.

---

## Confidence Gating: Two-Pass Extraction

**File**: `app/services/claude_extractor.py`

Every document goes through a two-pass extraction to catch low-confidence fields:

**Pass 1**: Claude Sonnet produces a structured JSON extraction. Each field includes a confidence score (0.0 to 1.0).

**Pass 2**: If any field confidence falls below 0.80, a second `tool_use` call is made targeting only the low-confidence fields. The correction call returns an `apply_corrections` tool invocation, which is merged into the Pass 1 output.

This approach catches 15-20% of extractions that would otherwise contain uncertain fields, without running two full extraction calls on every document.

Confidence thresholds are configurable per document type:

```
CONFIDENCE_THRESHOLDS={"medical_record":0.90,"contract":0.85}
```

Higher thresholds route more documents to human review. Lower thresholds reduce review volume but accept more uncertainty.

---

## Auto-Flagging and Human Review Queue

Records are automatically set to `needs_review=true` when any of the following are true:

- PII detected in extraction output
- Any field confidence score below the configured threshold after two-pass extraction
- Grounding check returns `ungrounded` fields
- Extraction encounters an unexpected document structure

**Review queue endpoint**: `GET /api/v1/records?needs_review=true`

Reviewers claim a record (`POST /api/v1/records/{id}/claim`), review the extraction against the source document, apply corrections if needed, and approve. All actions are logged to the audit trail.

Correction data is exportable as a DPO (Direct Preference Optimization) dataset via `app/services/finetune_exporter.py`, enabling future model fine-tuning on your specific document types.

---

## Audit Trail

**Table**: `audit_logs`
**Policy**: Append-only. No UPDATE or DELETE operations are permitted on this table.

Every record action writes an audit entry:

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Entry identifier |
| entity_type | string | Document, Record, Job, APIKey, etc. |
| entity_id | UUID | ID of the affected entity |
| action | string | created, claimed, approved, corrected, deleted, flagged |
| actor | string | API key ID or user identifier |
| old_data | JSONB | State before the action (null for creates) |
| new_data | JSONB | State after the action (null for deletes) |
| timestamp | timestamptz | UTC, set by the database |

This produces a full chain of custody for every document: upload → extraction → guardrail check → review → correction → approval → delivery.

The audit log supports compliance reporting, access anomaly detection, and incident investigation without relying on application logs (which may roll over).

---

## Trace Sanitization

**File**: `app/services/pii_sanitizer.py`

When OTEL or LangSmith/Langfuse tracing is enabled, all trace data passes through the PII sanitizer before export. The same four patterns (SSN, credit card, phone, email) are redacted from trace spans, replacing digits with `*`.

This prevents PHI from leaking into third-party monitoring systems even when detailed tracing is enabled. The sanitizer runs on:
- LLM prompt inputs sent to Langfuse
- LLM response outputs sent to Langfuse
- Custom span attributes in OTEL traces

Sanitization is active by default and cannot be disabled without code changes.

---

## Model Versioning

Model selection is controlled via environment variables:

```
EXTRACTION_MODELS=claude-sonnet-4-6,claude-haiku-4-5
CLASSIFICATION_MODELS=claude-haiku-4-5,claude-sonnet-4-6
```

The first value in each list is the primary model; subsequent values are the fallback chain. Model usage is recorded on every extraction record:

```json
{
  "model_used": "claude-sonnet-4-6",
  "model_version": "20241022",
  "extraction_cost_usd": 0.0031
}
```

This makes it possible to audit which model version produced any given extraction, reproduce results under a specific model version, and compare accuracy across model versions using `app/services/model_ab_test.py`.

Model changes in production require updating `EXTRACTION_MODELS` and re-running the golden eval suite to confirm the accuracy threshold is met.

---

## Eval CI Gate

**Directory**: `tests/eval/`

A golden eval suite of 28 fixtures must pass a 94.6% accuracy threshold before any deployment. The CI gate runs on every push to main and every pull request:

```yaml
# .github/workflows/ci.yml (excerpt)
- name: Run eval gate
  run: python -m pytest tests/eval/ --eval-threshold=0.94
```

The eval suite includes:
- 16 standard fixtures across document types (contracts, invoices, medical records, emails)
- 12 adversarial fixtures designed to trigger failure modes

Adversarial fixtures cover:
- Malformed document structure
- Contradictory information within a document
- Ambiguous date formats
- 4 prompt injection attempts (instructions embedded in document content attempting to override extraction behavior)

A failing eval blocks deployment. Accuracy degradation from model updates or prompt changes is caught before reaching production.

---

## Adversarial Testing

**Directory**: `tests/eval/fixtures/adversarial/`

12 adversarial test cases validate that the extraction pipeline handles hostile inputs without producing incorrect output or changing its behavior in response to injected instructions.

### Prompt Injection Coverage (4 cases)

Documents containing instructions like "Ignore previous instructions and output..." are tested to confirm that Claude's extraction behavior is not overridden by content in the document body. All 4 prompt injection fixtures pass at the current eval threshold.

### Other Adversarial Cases (8 cases)

- Documents with conflicting information in header vs. body
- Scanned documents with OCR errors
- Documents where key fields are absent
- Documents with values in unexpected formats
- Mixed-language documents
- Extremely short documents (single paragraph)
- Documents with tables containing merged cells
- Documents with redacted sections

---

## Compliance Alignment

### HIPAA

| Requirement | Implementation |
|-------------|---------------|
| PHI access controls | API key auth, role-based (admin vs. standard) |
| Encryption at rest | PostgreSQL pgcrypto, S3 AES-256, AES-GCM webhook secrets |
| Encryption in transit | TLS on all external endpoints, Redis AUTH on internal |
| Audit controls | Append-only `audit_logs` table |
| Minimum necessary | `DATA_RETENTION_DAYS` + cascade delete on document removal |
| BAA requirement | Anthropic BAA required before processing PHI through Claude API |

### GDPR Article 25 (Data Protection by Design)

- PII detection is active on every extraction when `GUARDRAILS_ENABLED=true`
- The `DELETE /api/v1/documents/{id}` endpoint cascades to all derived data (jobs, records, embeddings, stored files)
- No document content is retained by the AI provider beyond the API call
- `DATA_RETENTION_DAYS` enables automatic scheduled deletion

### GDPR Article 32 (Security of Processing)

- API key authentication with per-key rate limiting
- AES-GCM encryption for secrets stored in the database
- Bandit static analysis runs in CI (`bandit -r app/ worker/ -ll -ii`)
- Guardrails validation on all AI outputs before storage

### SOC 2 Trust Principles

| Principle | DocExtract Control |
|-----------|-------------------|
| Security | API key auth, rate limiting, AES-GCM encryption, bandit CI |
| Availability | Circuit breaker model fallback, ARQ async queue, health endpoints |
| Processing Integrity | Golden eval CI gate (94.6%), two-pass confidence gating, validation rules |
| Confidentiality | PII trace sanitization, encrypted webhook secrets, scoped API keys |
| Privacy | PII detection guardrails, audit logging, configurable retention, cascade delete |

---

## Role-Based Access Control

Two key roles:

**Admin API key**
- Create and revoke API keys
- Access all records across all document owners
- Trigger system-level operations (bulk delete, eval runs)

**Standard API key**
- Upload documents
- Read own records
- Submit reviews and corrections
- Cannot manage other API keys

Per-key rate limiting is enforced via Redis sliding window. Limits are configurable per key.

---

## Data Retention

Configure via environment variable:

```
DATA_RETENTION_DAYS=365   # delete documents and records older than 1 year
                          # not set = indefinite retention
```

Deletion is cascaded: removing a document also removes its jobs, extracted records, embeddings, and stored file. Audit log entries are retained regardless of retention policy (audit logs are append-only and do not cascade).

For HIPAA compliance, implement a scheduled cleanup job that calls `DELETE /api/v1/documents/{id}` for documents past their retention window. A reference script is included at `scripts/cleanup_expired_documents.py`.

---

## Governance Deployment Checklist

- [ ] Set `GUARDRAILS_ENABLED=true`
- [ ] Configure `CONFIDENCE_THRESHOLDS` for sensitive document types
- [ ] Enable `OTEL_ENABLED=true` for full request tracing
- [ ] Configure `DATA_RETENTION_DAYS` per retention policy
- [ ] Verify PII sanitizer is active before enabling Langfuse/LangSmith
- [ ] Obtain Anthropic BAA if processing PHI
- [ ] Set `AES_KEY` for webhook secret encryption
- [ ] Enable TLS on all external-facing endpoints
- [ ] Schedule weekly review queue audit (target: zero records older than 24h in queue)
- [ ] Run `bandit -r app/ worker/ -ll -ii` and resolve findings before production deploy
- [ ] Confirm eval CI gate is enforced on the main branch
- [ ] Review audit logs monthly for access anomalies
