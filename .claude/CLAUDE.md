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
Self-hosted via `docker compose up`:
- API: http://localhost:8000
- Worker: ARQ background service
- Frontend: http://localhost:8501
Also supports: Render Blueprint, K8s/Kustomize, AWS Terraform (RDS+ElastiCache)

## Test
```pytest tests/  # 1,155 tests```

## Key Env
ANTHROPIC_API_KEY, DATABASE_URL, REDIS_URL, SECRET_KEY
OTEL_ENABLED (default false), EXTRACTION_MODELS, CLASSIFICATION_MODELS
