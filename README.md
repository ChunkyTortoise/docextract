# DocExtract AI

[![Tests](https://img.shields.io/badge/tests-335%20passing-brightgreen)]()
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688)]()

> Intelligent document extraction API with two-pass Claude analysis, pgvector semantic search, and real-time SSE streaming.

## Architecture

```
Client
  |
  v
FastAPI REST API (/api/v1)
  |  +-- POST /documents/upload  --> SHA-256 dedup --> ARQ queue
  |  +-- GET  /jobs/{id}/events  --> SSE stream (Redis pub/sub)
  |  +-- GET  /records           --> paginated extracted records
  |  +-- GET  /records/search    --> pgvector semantic search
  |
  v
ARQ Worker (async Python)
  |
  +-- 1. MIME detection + routing
  +-- 2. Text extraction (PDF/image/email)
  +-- 3. Document classification
  +-- 4. Two-pass Claude extraction
  |       Pass 1: JSON extraction (claude-sonnet-4-6)
  |       Pass 2: tool_use correction (if confidence < 0.80)
  +-- 5. Business rule validation
  +-- 6. pgvector HNSW embedding (gemini-embedding-2-preview, 768-dim)
  +-- 7. HMAC-signed webhook delivery (4-attempt retry)

PostgreSQL + pgvector           Redis (pub/sub + rate limiting)
          \                       /
           +-- Streamlit Frontend --+
```

## Features

- **6 document types**: PDF, DOCX, CSV, images (PNG/JPEG), email (.eml), and plain text
- **Two-pass Claude extraction**: Pass 1 extracts structured JSON with a confidence score. If confidence < 0.80, Pass 2 fires a `tool_use` correction call for automatic error correction
- **SSE streaming progress**: Real-time job status updates via Server-Sent Events (Redis pub/sub)
- **HNSW vector search**: pgvector semantic search over extracted records (gemini-embedding-2-preview, 768-dim)
- **Human review workflow**: Claim, approve, or correct low-confidence extractions with full audit trail
- **ROI tracking**: Executive report generation with extraction cost/time analytics
- **SHA-256 deduplication**: Identical file uploads return existing job IDs instantly
- **Webhook delivery**: HMAC-SHA256 signed payloads with 4-attempt exponential retry
- **Sliding-window rate limiting**: Per-API-key Redis rate limiter with `X-RateLimit-*` headers
- **AES-GCM encrypted secrets**: Webhook signing secrets encrypted at rest
- **Pluggable storage**: Local filesystem or Cloudflare R2

## API Reference

All endpoints are prefixed with `/api/v1`. Authenticated endpoints require `X-API-Key` header.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | No | Basic health check |
| `GET` | `/health/detailed` | No | Health with DB/Redis/storage status |
| `POST` | `/documents/upload` | Yes | Upload a document for extraction (202) |
| `POST` | `/documents/batch` | Yes | Batch upload multiple documents (202) |
| `DELETE` | `/documents/{document_id}` | Yes | Delete a document and its data |
| `GET` | `/jobs` | Yes | List jobs with optional status filter |
| `GET` | `/jobs/{job_id}` | Yes | Get job status and details |
| `GET` | `/jobs/{job_id}/record` | Yes | Get extracted record for a job |
| `PATCH` | `/jobs/{job_id}` | Yes | Cancel a running job |
| `GET` | `/jobs/{job_id}/events` | Yes | SSE stream of job progress events |
| `GET` | `/records` | Yes | List extracted records (paginated) |
| `GET` | `/records/search` | Yes | Semantic search over records |
| `GET` | `/records/export` | Yes | Stream records as CSV or JSON |
| `GET` | `/records/{record_id}` | Yes | Get a single extracted record |
| `PATCH` | `/records/{record_id}/review` | Yes | Submit review for a record |
| `POST` | `/webhooks/test` | Yes | Send a test webhook payload |
| `GET` | `/stats` | Yes | Aggregate dashboard statistics |
| `POST` | `/api-keys` | Admin | Create a new API key |
| `GET` | `/api-keys` | Admin | List all API keys |
| `DELETE` | `/api-keys/{key_id}` | Admin | Revoke an API key |
| `GET` | `/review/items` | Yes | List review queue items |
| `POST` | `/review/items/{item_id}/claim` | Yes | Claim a review item |
| `POST` | `/review/items/{item_id}/approve` | Yes | Approve a review item |
| `POST` | `/review/items/{item_id}/correct` | Yes | Submit corrections for a review item |
| `GET` | `/review/metrics` | Yes | Review queue metrics |
| `GET` | `/roi/summary` | Yes | ROI summary with date range filter |
| `GET` | `/roi/trends` | Yes | ROI trends by week or month |
| `POST` | `/reports/generate` | Admin | Generate an executive report |
| `GET` | `/reports` | Admin | List generated reports |
| `GET` | `/reports/{report_id}` | Admin | Get a specific report |

## Quickstart

```bash
git clone https://github.com/ChunkyTortoise/docextract.git
cd docextract
cp .env.example .env  # fill in ANTHROPIC_API_KEY + GEMINI_API_KEY at minimum
alembic upgrade head   # apply database migrations
docker-compose up
```

Services start on:
- **API**: http://localhost:8000 (docs at `/docs`)
- **Frontend**: http://localhost:8501
- **PostgreSQL**: localhost:5432
- **Redis**: localhost:6379

Seed a dev API key:

```bash
docker-compose exec api python -m scripts.seed_api_key
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string (asyncpg driver added automatically) |
| `REDIS_URL` | Yes | Redis connection string |
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for Claude extraction |
| `API_KEY_SECRET` | Yes | Secret for hashing API keys (32+ chars) |
| `AES_KEY` | No | Base64-encoded 32-byte key for AES-GCM webhook secret encryption |
| `GEMINI_API_KEY` | Yes | Required for Gemini embeddings |
| `STORAGE_BACKEND` | No | `local` (default) or `r2` |
| `STORAGE_LOCAL_PATH` | No | Local file storage path (default: `./storage/local`) |
| `R2_ACCOUNT_ID` | No | Cloudflare R2 account ID |
| `R2_ACCESS_KEY_ID` | No | Cloudflare R2 access key |
| `R2_SECRET_ACCESS_KEY` | No | Cloudflare R2 secret key |
| `R2_BUCKET_NAME` | No | R2 bucket name (default: `docextract`) |
| `CORS_ORIGINS` | No | JSON array of allowed origins |
| `LOG_LEVEL` | No | Logging level (default: `INFO`) |
| `MAX_FILE_SIZE_MB` | No | Max upload size in MB (default: `50`) |
| `MAX_PAGES` | No | Max PDF pages to process (default: `100`) |
| `OCR_ENGINE` | No | `tesseract` or `paddle` (default: `tesseract`) |
| `EXTRACTION_CONFIDENCE_THRESHOLD` | No | Two-pass threshold (default: `0.8`) |
| `DEMO_MODE` | No | Enable demo mode with read-only access (default: `false`) |
| `DEMO_API_KEY` | No | API key for demo access (default: `demo-key-docextract-2026`) |

## Running Tests

```bash
pytest tests/ -v  # 335 tests, ~2s
```

## Project Structure

```
app/
  api/          -- FastAPI route modules (10 routers)
  auth/         -- API key auth + rate limiting middleware
  models/       -- SQLAlchemy models (8 tables)
  schemas/      -- Pydantic request/response schemas
  services/     -- Extraction, classification, embedding, validation
  storage/      -- Pluggable storage backends (local, R2)
  utils/        -- Hashing, MIME detection, token counting
worker/         -- ARQ async job processor
frontend/       -- Streamlit 6-page dashboard
alembic/        -- Database migrations (001-003)
scripts/        -- Seed scripts (API keys, sample docs, cleanup)
tests/          -- Unit + integration tests
```

## Live Demo

- **API**: https://docextract-api.onrender.com
- **Frontend**: https://docextract-frontend.onrender.com
- **Dev API key**: [set in Render dashboard]
- **Docs**: https://docextract-api.onrender.com/docs

## License

MIT
