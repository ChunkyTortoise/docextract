# DocExtract AI

## Stack
FastAPI | SQLAlchemy | pgvector | ARQ (async queue) | Redis | Anthropic | google-genai (Gemini Embedding) | Streamlit | PostgreSQL | Python

## Architecture
3-service document extraction platform: API (FastAPI) + Worker (ARQ) + Frontend (Streamlit). Documents → extract → embed (pgvector) → semantic search. Migrations: `alembic/`. Key fix: migration `002_pgvector_extension.py` uses `sa.Text()` (not `Vector(384)`); `WorkerSettings.redis_settings` must be `RedisSettings.from_dsn(settings.redis_url)`.
- `app/`: FastAPI routes and services
- `worker/`: ARQ job processor
- `frontend/`: Streamlit UI
- `alembic/`: DB migrations (001-012 applied)
- `site/`: static marketing front door (eval-first narrative; serve with `python -m http.server --directory site`)

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
LANGFUSE_* (human gate on live demo), OPENAI_API_KEY (optional eval-time multiprovider)

## Learned User Preferences
- Prefer DocExtract evalgate over EnterpriseHub nightly-eval closeout when choosing portfolio/eval ROI for agent time.
- Do not invent secrets, Loom/walkthrough URLs, or fake metrics; Langfuse and Anthropic API keys are human-only gates.
- Hireability orchestration for this repo defaults to A2 (DocExtract showcase-ready, then sibling heroes) + B1 (AI Eng — RAG / evals / DocAI) unless the user changes it.
- Showcase overhaul delivers A→B→C sequentially (evalgate closeout → multi-provider/corpus depth → marketing front door); keep Streamlit demo; no Next.js rewrite.

## Learned Workspace Facts
- Evalgate hireability overhaul is on **main** (PR #31 + follow-ups #33/#35): 200-case corpus v2.0.0, offline variance baseline, OpenAI eval-time provider, `site/`, DEMO_MODE hides synthetic dashboards, red money-shot [PR #32](https://github.com/ChunkyTortoise/docextract/pull/32) (keep open — Offline replay fails intentionally).
- Spec / cont tracker: `~/Projects/job-search/docs/superpowers/specs/2026-07-18-hybrid-cont-checklist.md` + `2026-07-18-s1-docextract-evalgate-closeout-deep-spec.md`. Design spec: `~/Projects/job-search/evalgate-docextract-spec-2026-07-12.md`.
- **Remaining human gates:** Langfuse keys on Render + one live demo trace; Anthropic credits for live N=7 variance + measured cost/latency; optional v2.0.0 ~10% label spot-check; optional 90s video ([docs/media/VIDEO-HUMAN-CHECKLIST.md](docs/media/VIDEO-HUMAN-CHECKLIST.md)).
- Honest claims: 95.5% = 28-fixture offline replay (not F1); cost/latency modeled until metered; GraphRAG = opt-in regex+file store; semantic cache not on extract hot path; GLM removed from default router chains.
- Optional GraphRAG hybrid retrieval lives under `app/services/graph_rag/`, gated by `graph_retrieval_enabled` (search mode `graph`; hybrid can three-way RRF when the flag is on).
