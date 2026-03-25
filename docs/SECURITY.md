# Security Guide

## API Authentication

DocExtract uses API key authentication via the `X-API-Key` header. Keys are validated against the `API_KEYS` environment variable (comma-separated list).

### Key Rotation Procedure

1. Generate a new key: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. Add the new key to `API_KEYS` alongside the old key: `API_KEYS=old_key,new_key`
3. Deploy the updated configuration
4. Migrate clients to the new key
5. Remove the old key from `API_KEYS` and redeploy

### Rate Limiting

- Redis sliding-window rate limiter per API key
- Default: 60 requests/minute (configurable via `RATE_LIMIT_PER_MINUTE`)
- Returns `429 Too Many Requests` with `Retry-After` header
- Rate limiting fails **open** if Redis is unavailable (requests proceed without limits)

## Webhook Security

Webhook deliveries are signed with HMAC-SHA256.

### Webhook Secret Management

- Set `WEBHOOK_SECRET` in environment
- Each delivery includes `X-Webhook-Signature` header
- Verify signature before processing: `hmac.compare_digest(expected, received)`
- Rotate by setting a new secret and updating all webhook consumers simultaneously

### Delivery Guarantees

- 4-attempt retry with exponential backoff
- Idempotent delivery (deduplicate by `delivery_id`)
- Failed deliveries logged with full context

## Data Handling

### Document Storage

- Uploaded documents are stored temporarily during processing
- Extracted text and structured records are stored in PostgreSQL
- Embeddings stored in pgvector (768-dimensional, Gemini embedding)
- No raw document bytes are persisted after extraction (configurable)

### Data Retention

- Extracted records: retained indefinitely (configure cleanup via `RETENTION_DAYS`)
- LLM traces: retained for cost tracking and debugging (30-day default)
- Semantic cache entries: TTL-based expiry (configurable via `CACHE_TTL_SECONDS`)

## CORS Configuration

- Default: permissive for development (`CORS_ORIGINS=*`)
- Production: restrict to known frontend domains
- Set via `CORS_ORIGINS` environment variable (comma-separated)

## Dependencies

- **Anthropic API**: API key stored in `ANTHROPIC_API_KEY` env var. Never commit to source.
- **Google Gemini**: Embedding API key in `GOOGLE_API_KEY`. Used only for vector embeddings.
- **PostgreSQL**: Connection string in `DATABASE_URL`. Use SSL in production (`?sslmode=require`).
- **Redis**: Connection string in `REDIS_URL`. Use TLS in production.

## CI Security

- `bandit` static analysis runs on every PR (see `.github/workflows/ci.yml`)
- No secrets in source code (all via environment variables)
- Docker images published to GHCR (GitHub Container Registry) with repository-scoped access
