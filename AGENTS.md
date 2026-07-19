# DocExtract AI

## Stack
FastAPI | SQLAlchemy | pgvector | ARQ (async queue) | Redis | Anthropic | google-genai (Gemini Embedding) | Streamlit | PostgreSQL | Python

## Architecture
3-service document extraction platform: API (FastAPI) + Worker (ARQ) + Frontend (Streamlit). Documents → extract → embed (pgvector) → semantic search. Migrations: `alembic/`. Key fix: migration `002_pgvector_extension.py` uses `sa.Text()` (not `Vector(384)`); `WorkerSettings.redis_settings` must be `RedisSettings.from_dsn(settings.redis_url)`.
- `app/`: FastAPI routes and services
- `worker/`: ARQ job processor
- `frontend/`: Streamlit UI
- `alembic/`: DB migrations (001-012 applied)

## Deploy
Self-hosted via `docker compose up`:
- API: http://localhost:8000
- Worker: ARQ background service
- Frontend: http://localhost:8501
Also supports: Render Blueprint, K8s/Kustomize, AWS Terraform (RDS+ElastiCache)

## Test
```pytest tests/  # 1,366 collected tests (ledger: docs/portfolio-metrics.yaml)```

## Key Env
ANTHROPIC_API_KEY, DATABASE_URL, REDIS_URL, SECRET_KEY
OTEL_ENABLED (default false), EXTRACTION_MODELS, CLASSIFICATION_MODELS

## Learned User Preferences
- Prefer DocExtract evalgate over EnterpriseHub nightly-eval closeout when choosing portfolio/eval ROI for agent time.
- Do not invent secrets, Loom/walkthrough URLs, or fake metrics; Langfuse and Anthropic API keys are human-only gates.
- Hireability orchestration for this repo defaults to A2 (DocExtract showcase-ready, then sibling heroes) + B1 (AI Eng — RAG / evals / DocAI) unless the user changes it.

## Learned Workspace Facts
- Active front-door hireability track is evalgate (spec: `~/Projects/job-search/evalgate-docextract-spec-2026-07-12.md`): versioned corpus, variance-calibrated ship-gate, Langfuse telemetry.
- Evalgate week plan: W1 corpus+Langfuse, W2 variance gate, W3 multi-provider (+ corpus toward ~200), W4 narrative/README packaging.
- Evalgate W1 corpus (120 cases) merged via PR #31; human accept gates remain Langfuse keys on the live demo plus label spot-check.
- Langfuse/Braintrust instrumentation is already on main; live demo traces still need human-supplied Langfuse keys.
- Optional GraphRAG hybrid retrieval lives under `app/services/graph_rag/`, gated by `graph_retrieval_enabled` (search mode `graph`; hybrid can three-way RRF when the flag is on).
