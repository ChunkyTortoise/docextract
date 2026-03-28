# DocExtract AI

**Extract structured data from unstructured documents in seconds -- not hours.**

[![Tests](https://github.com/ChunkyTortoise/docextract/actions/workflows/ci.yml/badge.svg)](https://github.com/ChunkyTortoise/docextract/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/ChunkyTortoise/docextract/graph/badge.svg)](https://codecov.io/gh/ChunkyTortoise/docextract)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688.svg)](https://fastapi.tiangolo.com)
[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://docextract-demo.streamlit.app)

## For Hiring Managers

| If you're evaluating for... | Where to look | Training behind it |
|-----------------------------|--------------|-------------------|
| **AI / ML Engineer** | Agentic RAG ReAct loop ([`app/services/agentic_rag.py`](app/services/agentic_rag.py)), RAGAS evaluation pipeline ([`app/services/ragas_evaluator.py`](app/services/ragas_evaluator.py)), QLoRA fine-tuning pipeline ([`scripts/train_qlora.py`](scripts/train_qlora.py), [`adapters/`](adapters/)), W&B experiment tracking, golden eval CI gate | IBM GenAI Engineering (144h), IBM RAG & Agentic AI (24h), DeepLearning.AI Deep Learning (120h) |
| **Backend / Platform Engineer** | Circuit breaker model fallback ([`app/services/circuit_breaker.py`](app/services/circuit_breaker.py)), async ARQ job queue ([`worker/`](worker/)), K8s/HPA manifests ([`deploy/k8s/`](deploy/k8s/)), Terraform IaC ([`deploy/aws/`](deploy/aws/)), sliding-window rate limiter | Microsoft AI & ML Engineering (75h), Google Cloud GenAI Leader (25h) |
| **Full-Stack AI Engineer** | 14-page Streamlit dashboard ([`frontend/`](frontend/)), SSE streaming progress, MCP tool server ([`mcp_server.py`](mcp_server.py)), interactive demo sandbox | IBM BI Analyst (141h), Google Data Analytics (181h), Microsoft Data Viz (87h) |
| **MLOps / LLMOps Engineer** | Prompt versioning + regression testing ([`app/services/prompt_registry.py`](app/services/prompt_registry.py)), model A/B testing with z-test significance ([`app/services/model_ab_test.py`](app/services/model_ab_test.py)), DeepEval CI gates, cost tracking per request | Duke LLMOps (48h), Google Advanced Data Analytics (200h) |

→ Full cert-to-code mapping: [`docs/certifications.md`](docs/certifications.md) (1,208h across 14 certifications)

## Quickstart

```bash
git clone https://github.com/ChunkyTortoise/docextract.git
cd docextract
cp .env.example .env  # Add ANTHROPIC_API_KEY + GEMINI_API_KEY
docker compose up -d
open http://localhost:8501  # Streamlit UI
```

Services: API at `:8000` (`/docs` for Swagger) | Frontend at `:8501` | PostgreSQL `:5432` | Redis `:6379`

## Demo

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://docextract-demo.streamlit.app)

> First visit may take 30 seconds to wake up. Pre-cached results for invoice, contract, and receipt extraction.

Local demo (no API key needed):

```bash
DEMO_MODE=true streamlit run frontend/app.py
```

## Architecture

```mermaid
graph LR
  A[Browser / API Client] -->|POST /documents| B[FastAPI]
  B -->|enqueue| C[ARQ Worker]
  C -->|classify| D{Model Router}
  D -->|primary| E[Claude Sonnet]
  D -->|fallback| F[Claude Haiku]
  E -->|Pass 2: extract + correct| G[pgvector HNSW]
  B -->|SSE stream stages| A
  G -->|semantic search| B
  B -->|/metrics| H[Prometheus]
  D --- I[Circuit Breaker]
```

## Screenshots

| Upload & Extraction | Extracted Records & ROI |
|---------------------|------------------------|
| ![Upload](docs/screenshots/upload.png) | ![Dashboard](docs/screenshots/dashboard.png) |

### SSE Streaming Demo

![SSE streaming extraction flow](docs/screenshots/sse-streaming-demo.gif)

*Real-time progress: PREPROCESSING > EXTRACTING > CLASSIFYING > VALIDATING > EMBEDDING > COMPLETED*

## Key Capabilities

- **Extraction**: Two-pass Claude pipeline (draft + verify via `tool_use`), 6 document types, 94.6% accuracy on 28-fixture eval suite
- **Search & RAG**: pgvector semantic search (768-dim HNSW), hybrid BM25+RRF retrieval, agentic ReAct loop with 5 tools, map-reduce multi-document synthesis, semantic deduplication cache
- **Reliability**: Circuit breaker (Sonnet to Haiku fallback), dead-letter queue, idempotent retries, HMAC-signed webhooks with 4-attempt retry, SHA-256 upload dedup
- **Observability**: OpenTelemetry traces (Jaeger/Tempo), Prometheus metrics, Grafana dashboards, per-request cost tracking, structured logging
- **Developer Experience**: SSE streaming progress, MCP server integration, prompt versioning (semver), model A/B testing (z-test), 12 ADRs, 90%+ test coverage

## Performance

| Metric | Value |
|--------|-------|
| Document extraction (p50) | ~8s (two-pass Claude) |
| SSE first token (p50) | <500ms |
| Semantic search (p95) | <100ms |
| Extraction accuracy (golden eval) | **94.6%** across 28 fixtures, 6 document types |
| Test suite | ~5s (1,155 tests) |
| Coverage | 90%+ (CI-enforced) |

## Evaluation Results

Measured against 28 hand-crafted golden fixtures (including 12 adversarial cases with 4 prompt injection attacks) covering all 6 document types. Scores are field-level F1. Run in CI on every push.

| Document Type | Accuracy |
|---------------|---------|
| Invoice | 95.0% |
| Purchase Order | 96.4% |
| Bank Statement | 91.6% |
| Medical Record | 98.9% |
| Receipt | 82.1% |
| Identity Document | 81.4% |
| **Overall** | **94.6%** |

```bash
# Reproduce locally (no API calls):
python scripts/run_eval_ci.py --ci
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
frontend/       -- Streamlit 14-page dashboard
alembic/        -- Database migrations (001-010)
scripts/        -- Seed scripts (API keys, sample docs, cleanup)
tests/          -- Unit + integration tests
```

## Architecture Decisions

12 Architecture Decision Records (ADRs) document the key design choices: [docs/adr/](docs/adr/)

| ADR | Decision |
|-----|----------|
| [ADR-0001](docs/adr/0001-arq-over-celery.md) | ARQ over Celery for async job queue |
| [ADR-0002](docs/adr/0002-pgvector-over-dedicated-vector-db.md) | pgvector over Pinecone/Weaviate |
| [ADR-0003](docs/adr/0003-two-pass-extraction.md) | Two-pass Claude extraction with confidence gating |
| [ADR-0006](docs/adr/0006-circuit-breaker-model-fallback.md) | Circuit breaker model fallback chain |
| [ADR-0011](docs/adr/0011-api-key-auth-over-oauth-jwt.md) | API key auth over OAuth/JWT |
| [ADR-0012](docs/adr/0012-pluggable-storage-local-r2.md) | Pluggable storage backend (Local/R2) |

## Production Readiness

Deployed with: Docker Compose / AWS Terraform (RDS + ElastiCache + ECR) / Kubernetes (Kustomize + HPA). Grafana observability. 80% coverage gate. 94.6% eval gate in CI. HIPAA/SOC2 alignment documented.

**Cloud infrastructure** ([`deploy/aws/main.tf`](deploy/aws/main.tf), [`deploy/k8s/`](deploy/k8s/)): Full Terraform IaC for AWS — RDS PostgreSQL, ElastiCache Redis, ECR registry, EC2 with auto-scaling. Kubernetes manifests with Kustomize overlays, Horizontal Pod Autoscaler, and Ingress. Applied from Google Cloud GenAI Leader (25h) coursework.

| Document | Purpose |
|----------|---------|
| [SLO Targets](docs/slo.md) | Latency, availability, quality, cost targets |
| [Common Failure Runbook](docs/runbooks/common-failures.md) | Circuit breaker, Redis, DB, queue, vector index recovery |
| [Security Guide](docs/SECURITY.md) | API keys, webhooks, CORS, data handling |
| [Compliance & Privacy](docs/COMPLIANCE.md) | HIPAA/PHI handling, PII detection, SOC 2 alignment |
| [Architecture](ARCHITECTURE.md) | Full system architecture overview |
| [Case Study](CASE_STUDY.md) | Engineering journey from prototype to production |
| [MCP Integration](docs/mcp-integration.md) | Claude Desktop / agent framework setup |
| [Cost Model](docs/cost-model.md) | Token costs, per-document pricing, volume estimates |
| [Certifications Applied](docs/certifications.md) | 1,208h across 14 certifications mapped to features |

## Deployment

**Render (one-click):** [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/ChunkyTortoise/docextract)

**Kubernetes:** `kubectl apply -k deploy/k8s/` (HPA auto-scaling, nginx ingress, SSE buffering disabled)

**AWS Terraform:** `cd deploy/aws && terraform apply` (EC2 + RDS PostgreSQL 16 + ElastiCache Redis 7, free-tier eligible)

See [deploy/](deploy/) for full manifests and configuration.

## Running Tests

```bash
pytest tests/ -v                      # Full suite (1,155 tests, ~5s)
pytest tests/ -v --run-eval           # Include golden eval (requires API key)
python scripts/run_eval_ci.py --ci    # Deterministic eval (no API key)
```

## Known Limitations

- **Tesseract degradation on handwriting**: OCR accuracy drops significantly on handwritten documents. Set `OCR_ENGINE=vision` to route through Claude's vision API instead.
- **English-only extraction prompts**: Non-English documents may extract with lower accuracy.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, and PR guidelines.

## License

MIT
