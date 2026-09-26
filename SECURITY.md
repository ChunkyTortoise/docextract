# Security

DocExtract AI implements defense-in-depth across authentication, transport, storage, and rate limiting.

## Authentication

- **API key hashing**: API keys are HMAC-SHA256 hashed with `API_KEY_SECRET` before storage. Raw keys are returned only once and are never written to the database.
- **Admin vs user roles**: Admin endpoints require a separate elevated key. User keys cannot access key management routes.

## Secrets Management

- **AES-GCM encrypted webhook secrets**: Webhook signing secrets are encrypted at rest using AES-256-GCM. The encryption key is loaded from `AES_KEY` (base64-encoded 32-byte key), never hardcoded.
- **Keyed hashing**: `API_KEY_SECRET` (32+ chars, env-only) is used for HMAC hashing of all API keys.

## Webhook Security

- **HMAC-SHA256 signatures**: All outbound webhook payloads include an `X-Signature-256` header signed with the per-endpoint secret. Recipients validate before processing.
- **4-attempt exponential backoff**: Delivery retries back off to prevent thundering-herd behavior on webhook endpoint failures.

## Rate Limiting

- **Sliding-window per-API-key limiter**: Enforced in Redis with `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` response headers.
- **Configurable limits**: Default limits are set at the middleware layer; can be tuned per deployment without code changes.

## Input Validation

- **Pydantic v2 on all boundaries**: Every request body, query parameter, and path parameter is validated before reaching service code. No raw dict access.
- **MIME-type detection**: Uploaded files are verified by magic bytes, not just file extension. Unsupported types are rejected at ingestion.
- **Max upload size**: Configurable via `MAX_FILE_SIZE_MB` (default: 50MB). Requests exceeding this are rejected before processing begins.

## Data Storage

- **Logging scope**: Routine pipeline logs use job IDs and metadata. Provider and validation errors may contain source values; restrict log access and retention.
- **SHA-256 deduplication**: The server hashes uploaded bytes. Normal uploads select the newest matching document and job; `?force=true` bypasses reuse. The soft check does not prevent concurrent duplicate uploads.
- **Pluggable storage backends**: Local filesystem or Cloudflare R2. R2 credentials are env-only and never committed.
- **PII redaction at persistence**: `PII_REDACTION_ENABLED` (default OFF in code) replaces PII values with redaction tokens before records are stored or returned. The render.yaml and fly.toml deploy profiles set it to `true` (both also ship `DEMO_MODE=true` for the demo UI; unset it for a demo-free production deployment). The k8s configmap and ecs.tf do not set it yet. The detect-and-flag boundary is separate (`GUARDRAILS_ENABLED`).

## Operational Endpoints

- **/metrics (Prometheus)**: Mounted only when `OTEL_ENABLED=true` (default OFF). When enabled it serves metrics unauthenticated at the API root; point an internal collector at it or add an auth boundary before enabling on a public deployment.

## Prompt-Injection Defense

- **Fenced untrusted content**: Extracted document text and caller-supplied doc-type hints are wrapped in an untrusted fence so injected instructions are far less likely to steer the model. This is heuristic mitigation, not a guarantee (ADR-0020 instruction hierarchy).
- **Defense system clause**: Both the text and vision extraction paths carry a defense clause in the system block.
- **Output sanitization**: Text and vision extraction strip known exfiltration keys before persistence. Allowed field values can still contain injected content. The pattern scanner is a library hook and is not called by the current pipeline.

## Reporting Security Issues

Open a private GitHub Security Advisory at [github.com/ChunkyTortoise/docextract/security/advisories](https://github.com/ChunkyTortoise/docextract/security/advisories).

## PII and data handling

- Document text and extracted records are stored in your configured PostgreSQL instance and object storage. Treat both as containing personal data.
- `pii_redaction_enabled` defaults to **off** (a deployment decision). When enabled, the worker redacts record fields, raw text, embedding text, and optional graph input before persistence. Original uploads still contain the original data.
- Completion/review webhooks contain job and record identifiers, status, and document type. Deliveries run as deferred ARQ jobs and are signed with HMAC-SHA256. Signing secrets remain AES-GCM ciphertext in storage and Redis, and are decrypted inside each delivery attempt.
- No automatic data retention or deletion is implemented. Older docs mentioned `DATA_RETENTION_DAYS` and `STORE_DOCUMENTS`; those have no implementation. Enforce retention at the database and storage layer.

## Known limitations

- Document deduplication is a soft check. Extraction records have a separate one-record-per-job constraint; migration 013 keeps the earliest record for a job and removes later duplicates. Review and back up existing duplicate data before applying it.
- Error logs can include fragments of raw model output. Regex redaction is incomplete and does not make documents anonymous.
