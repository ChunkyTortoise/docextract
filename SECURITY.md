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

- **No PII logged**: Extraction jobs log document hashes and job IDs, not file contents or extracted data.
- **SHA-256 deduplication**: Identical file uploads reuse existing jobs. The hash is computed client-side and verified server-side before storage.
- **Pluggable storage backends**: Local filesystem or Cloudflare R2. R2 credentials are env-only and never committed.

## Reporting Security Issues

Open a private GitHub Security Advisory at [github.com/ChunkyTortoise/docextract/security/advisories](https://github.com/ChunkyTortoise/docextract/security/advisories).

## PII and data handling

- Document text and extracted records are stored in your configured PostgreSQL instance and object storage. Treat both as containing personal data.
- `pii_redaction_enabled` defaults to **off** (a deployment decision). When enabled, the worker redacts record fields and raw text before persistence.
- Webhook payloads contain extracted record data. Deliveries are signed with HMAC-SHA256; signing secrets are encrypted at rest with AES-GCM when `AES_KEY` is set.
- No automatic data retention or deletion is implemented. Older docs mentioned `DATA_RETENTION_DAYS` and `STORE_DOCUMENTS`; those have no implementation. Enforce retention at the database and storage layer.

## Known limitations (internal audit, 2026-09-23)

- Deduplication is a soft check with no unique constraint. `?force=true` creates duplicates, and a later normal upload of the same bytes returns 500 until the duplicates are cleaned up.
- With PII redaction enabled, the embedding text and the optional entity graph still receive original text, and error logs can include fragments of raw model output.
