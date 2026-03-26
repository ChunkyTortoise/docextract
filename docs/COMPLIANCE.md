# Compliance & Data Privacy Guide

DocExtract processes documents that may contain protected health information (PHI), personally identifiable information (PII), and financial data. This guide documents the controls, configurations, and procedures for compliance-sensitive deployments.

## PII Detection Guardrails

DocExtract includes a built-in PII detection pipeline (`app/services/guardrails.py`) that scans extraction output for:

| PII Type | Detection Method | Example |
|----------|-----------------|---------|
| Social Security Numbers | Regex (`\d{3}-\d{2}-\d{4}`) | 123-45-6789 |
| Credit Card Numbers | Luhn-compatible regex (Visa, MC, Amex, Discover, JCB) | 4111-1111-1111-1111 |
| Phone Numbers | North American format regex | (555) 123-4567 |
| Email Addresses | RFC-compliant regex | user@example.com |

### Enabling Guardrails

Set `GUARDRAILS_ENABLED=true` in your environment. When enabled:

1. Every extraction runs PII detection on the output
2. Records with detected PII are auto-flagged for human review (`needs_review=true`)
3. PII findings are stored in the record metadata under `_guardrails`
4. The review reason includes the types of PII detected

### Hallucination Grounding

The guardrails also validate that extracted values appear in the source document text (grounding check). Fields where the extracted value does not appear in the source are flagged as "ungrounded," which may indicate hallucination.

### On-Demand Guardrails

Use the `GET /api/v1/records/{id}/guardrails` endpoint to run guardrails on any record at any time, regardless of the `GUARDRAILS_ENABLED` flag.

## PHI Handling (HIPAA Considerations)

DocExtract supports medical record extraction as a document type. Deployments processing PHI must implement the following controls:

### Data Flow

```
Document Upload → Storage (local/R2) → Text Extraction → Claude API → Record DB → Human Review
```

PHI may be present at every stage. The following controls apply:

### Encryption

- **At rest**: PostgreSQL with `pgcrypto` extension. Webhook secrets use AES-GCM encryption (`AES_KEY` env var). Storage backends support encryption (R2: server-side encryption enabled by default).
- **In transit**: All API endpoints should be served over TLS. Internal service communication (API to Worker via Redis) uses Redis AUTH when configured.

### Trace Sanitization

The PII sanitizer (`app/services/pii_sanitizer.py`) runs on all data sent to external observability services (Langfuse, LangSmith). SSNs, credit cards, phone numbers, and emails are redacted before trace export. This prevents PHI from leaking into third-party monitoring systems.

### Audit Trail

Every record action is logged to the `audit_logs` table with:
- Entity type and ID
- Action performed (created, claimed, approved, corrected)
- Actor identifier
- Old and new data snapshots
- Timestamp

Audit log entries are immutable (append-only, no UPDATE or DELETE).

### Access Controls

- API key authentication on all endpoints
- Per-key rate limiting (Redis sliding window)
- Role-based access: Admin keys can create/revoke API keys; standard keys can only read/write records

### Data Retention

- Configure document retention via `DATA_RETENTION_DAYS` (not set = indefinite)
- The `DELETE /api/v1/documents/{id}` endpoint cascades to jobs, records, embeddings, and stored files
- Implement a scheduled cleanup job for HIPAA minimum necessary retention

### BAA Requirements

Processing PHI through Claude requires an Anthropic Business Associate Agreement (BAA). Contact Anthropic sales for BAA availability. Until a BAA is in place, do not send documents containing PHI to the Claude API. Use the `DEMO_MODE=true` flag for evaluation with synthetic data.

## GDPR Compliance Mapping

DocExtract supports GDPR-aligned deployments processing personal data. The following maps core GDPR requirements to specific controls.

### Article 5 — Principles Relating to Processing

| Principle | DocExtract Implementation |
|-----------|--------------------------|
| **Lawfulness, fairness, transparency** | Audit trail records every processing action with actor and timestamp |
| **Purpose limitation** | Document types define permitted extraction fields; no cross-purpose repurposing without explicit config |
| **Data minimisation** | Extraction schemas define exactly which fields to extract; source document not stored if `STORE_DOCUMENTS=false` |
| **Accuracy** | Two-pass confidence gating flags uncertain extractions for human review |
| **Storage limitation** | `DATA_RETENTION_DAYS` env var enforces automatic deletion; cascade delete removes all derived data |
| **Integrity and confidentiality** | AES-GCM encryption for secrets, TLS in transit, pgcrypto at rest, PII sanitized from traces |

### Article 17 — Right to Erasure (Right to be Forgotten)

The `DELETE /api/v1/documents/{id}` endpoint provides full cascade deletion:
- Source document file removed from storage (local filesystem or Cloudflare R2)
- All extraction jobs and records deleted
- All pgvector embeddings purged
- Audit log entries preserved (they record the deletion event, not the deleted content)

For bulk erasure workflows, query records by `source_identifier` field and delete in batches.

### Article 22 — Automated Individual Decision-Making

DocExtract outputs are extracted fields and confidence scores — they are inputs to human decisions, not autonomous decisions. Where DocExtract feeds downstream decision-making systems:

1. Enable the review queue: records with confidence below threshold auto-enter human review before downstream processing
2. Confidence scores are stored per-field in the `records.metadata` JSONB column, providing a machine-readable audit of certainty
3. Grounding checks flag fields where extracted values cannot be located in the source text (potential hallucinations)

### Article 25 — Data Protection by Design and by Default

- `GUARDRAILS_ENABLED=true` is the recommended default for personal data processing
- PII detection runs automatically on extraction output before storage
- Records with detected PII are auto-flagged (`needs_review=true`) before any downstream action
- Extraction schemas can exclude fields entirely if not required for the processing purpose

### Article 32 — Security of Processing

| Measure | Implementation |
|---------|---------------|
| Pseudonymisation | Source identifiers can be external reference IDs (not real names) |
| Encryption | AES-GCM for webhook secrets; TLS required for API; pgcrypto available |
| Confidentiality assurance | Scoped API keys (admin vs standard); rate limiting per key |
| Data restoration | ARQ queue persistence in Redis; PostgreSQL backup procedures in deploy/aws/ |
| Regular testing | CI bandit scan; eval CI gate; automated test suite (1,148 tests) |

### Article 83 — Data Processing Record

DocExtract's `audit_logs` table satisfies Article 30 (records of processing activities) requirements:
- Every create/update/approve/correct action logged
- Actor identifier, entity type, entity ID, timestamp
- Old and new data snapshots
- Append-only (no UPDATE or DELETE on audit_logs)

### GDPR Deployment Checklist

- [ ] Enable `GUARDRAILS_ENABLED=true` before processing personal data
- [ ] Set `DATA_RETENTION_DAYS` to match your retention policy
- [ ] Configure TLS on all external-facing endpoints
- [ ] Document processing purpose in your Article 30 register, referencing DocExtract as the processor
- [ ] If processing EU resident data through Claude, confirm Anthropic's DPA is in place
- [ ] Review `CORS_ORIGINS` to restrict API access to known origins
- [ ] Test the cascade delete endpoint before go-live
- [ ] Enable `OTEL_ENABLED=true` for processing activity visibility

---

## SOC 2 Alignment

| Trust Principle | DocExtract Control |
|----------------|-------------------|
| **Security** | API key auth, rate limiting, AES-GCM encryption, bandit static analysis in CI |
| **Availability** | Circuit breaker model fallback, async queue (ARQ), health endpoints, SLO targets |
| **Processing Integrity** | Golden eval CI gate (94.6% accuracy threshold), validation rules, two-pass confidence gating |
| **Confidentiality** | PII sanitization for traces, encrypted webhook secrets, scoped API keys |
| **Privacy** | PII detection guardrails, audit logging, configurable data retention, document deletion cascade |

## Deployment Checklist for Compliance-Sensitive Environments

- [ ] Set `GUARDRAILS_ENABLED=true`
- [ ] Configure `AES_KEY` for webhook secret encryption
- [ ] Enable TLS on all external-facing endpoints
- [ ] Configure Redis AUTH password
- [ ] Set `DATA_RETENTION_DAYS` per your retention policy
- [ ] Verify PII sanitizer is active for Langfuse/LangSmith (default: enabled)
- [ ] Obtain Anthropic BAA if processing PHI
- [ ] Review and restrict CORS origins (`CORS_ORIGINS`)
- [ ] Enable `OTEL_ENABLED=true` for request tracing and latency monitoring
- [ ] Set `CONFIDENCE_THRESHOLDS={"medical_record":0.90}` for medical documents
- [ ] Run `bandit -r app/ worker/ -ll -ii` and resolve any findings
- [ ] Review audit logs regularly for access anomalies

## Regulatory References

- **HIPAA**: 45 CFR Parts 160, 162, and 164
- **GDPR**: Article 25 (Data Protection by Design), Article 32 (Security of Processing)
- **SOC 2**: AICPA Trust Services Criteria (TSC 2017)
- **EU AI Act**: Article 9 (Risk Management), Article 10 (Data Governance)
