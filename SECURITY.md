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
- **PII redaction at persistence**: `PII_REDACTION_ENABLED` (default OFF in code) replaces PII values with redaction tokens before records are stored or returned. The render.yaml and fly.toml deploy profiles set it to `true` (fly.toml also ships `DEMO_MODE=true` for the demo UI; unset it for a demo-free production deployment). The k8s configmap and ecs.tf do not set it yet. The detect-and-flag boundary is separate (`GUARDRAILS_ENABLED`).

## Operational Endpoints

- **/metrics (Prometheus)**: Mounted only when `OTEL_ENABLED=true` (default OFF). When enabled it serves metrics unauthenticated at the API root; point an internal collector at it or add an auth boundary before enabling on a public deployment.

## Prompt-Injection Defense

- **Fenced untrusted content**: Extracted document text and caller-supplied doc-type hints are wrapped in an untrusted fence so injected instructions are far less likely to steer the model. This is heuristic mitigation, not a guarantee (ADR-0020 instruction hierarchy).
- **Defense system clause**: Both the text and vision extraction paths carry a defense clause in the system block.
- **Output sanitization**: Extracted results pass through sanitize-and-scan before persistence; exfiltration keys are stripped and scan hits are logged.

## Reporting Security Issues

Open a private GitHub Security Advisory at [github.com/ChunkyTortoise/docextract/security/advisories](https://github.com/ChunkyTortoise/docextract/security/advisories).
