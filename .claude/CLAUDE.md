# DocExtract AI

## Stack
FastAPI | SQLAlchemy | pgvector | ARQ (async queue) | Redis | Anthropic | google-genai (Gemini Embedding) | Streamlit | PostgreSQL | Python

## Architecture
3-service document extraction platform: API (FastAPI) + Worker (ARQ) + Frontend (Streamlit). Documents → extract → embed (pgvector) → semantic search. Migrations: `alembic/`. Key fix: migration `002_pgvector_extension.py` uses `sa.Text()` (not `Vector(384)`); `WorkerSettings.redis_settings` must be `RedisSettings.from_dsn(settings.redis_url)`.
- `app/` — FastAPI routes and services
- `worker/` — ARQ job processor
- `frontend/` — Streamlit UI
- `alembic/` — DB migrations (001-010 applied)

## Deploy
Render — 3 live services:
- API: https://docextract-api.onrender.com (srv-d6ijm7buibrs73ad84rg)
- Worker: srv-d6ijm7buibrs73ad84s0
- Frontend: https://docextract-frontend.onrender.com (srv-d6ivqtq4d50c73aq6cu0)
Dev API key: `[set in Render dashboard]`

## Test
```pytest tests/  # 1,060 tests```

## Key Env
ANTHROPIC_API_KEY, DATABASE_URL, REDIS_URL, SECRET_KEY
OTEL_ENABLED (default false), EXTRACTION_MODELS, CLASSIFICATION_MODELS
