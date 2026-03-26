# Building a Production RAG Pipeline That Hiring Managers Can Actually Verify

## The Problem

Most AI engineer portfolios share the same gap: impressive architectures that only exist as README descriptions. 1,155 tests prove correctness at development time, but nothing proves the system works at request time. No live URL. No trace dashboards. No eval regression gates. No cost visibility.

This case study documents how DocExtract went from a well-tested local project to a production system with observable behavior, measurable quality, and resilience patterns that survive real-world failure modes.

## What Changed

### Before: Strong Code, No Production Signal

- 1,155 automated tests, 90%+ coverage
- Agentic RAG with ReAct reasoning, HITL corrections, circuit breaker failover
- Docker, K8s manifests, Terraform IaC all checked in
- Zero live deployments. Zero trace data. Zero eval metrics from real requests.

### After: Observable Production System

- Live API with health monitoring and uptime tracking
- Every extraction, search, and review action traced via Langfuse (model calls, token usage, latency, confidence)
- PII sanitization before any trace leaves the application boundary
- Tiered evaluation CI gates: deterministic schema checks on every PR, LLM-as-a-judge nightly
- Regression threshold: deployment blocks if extraction accuracy drops below 90% (baseline: 94.6%)

## Architecture: The Sync Sidecar Pattern

The key design decision: observability must never slow down the request path.

```
[Client]
    |
    v
[FastAPI API]
    |
    +---> [Extraction Pipeline / ReAct Agent]
    |         |
    |         +---> [Model Router + Circuit Breaker]
    |         |         Sonnet (primary) --> Haiku (fallback)
    |         +---> [pgvector HNSW Search]
    |         +---> [Semantic Cache (Redis)]
    |
    +---> [BackgroundTasks Sidecar]  <-- non-blocking
              |
              +---> [Langfuse Cloud]  (trace, generation, span)
              +---> [PII Sanitizer]   (SSN/CC/phone/email stripped)
              +---> [Cost Tracker]    (USD per request)
```

FastAPI `BackgroundTasks` handle all trace submission after the response is sent. The user sees extraction results immediately. Langfuse receives the full trace (model, tokens, latency, confidence) in the background. PII is stripped before any data leaves the application.

This is the pattern Gemini's deep analysis recommended for portfolio-scale deployments: low complexity (4/10), no message queue overhead, and observable behavior without latency penalty.

## Evaluation: Tiered CI Gates

Production AI systems need two kinds of quality assurance:

### Tier 1: Every Pull Request (Deterministic, Zero API Cost)

- Schema conformance: extraction output matches Pydantic model
- Confidence range: all scores between 0.0 and 1.0
- Field completeness: no golden-set case produces empty extraction
- Citation grounding: extracted values appear in source text (80%+ threshold)
- Baseline accuracy: average score across golden set stays above 90%

These run in GitHub Actions on every PR. No LLM API calls. Cached golden-set assertions only.

### Tier 2: Nightly (LLM-as-a-Judge via DeepEval)

- Contextual precision: does the retrieved context contain relevant information?
- Faithfulness: does the answer stay within the context (no hallucination)?
- Answer relevancy: does the output actually answer the query?

These run on a nightly cron schedule against the same golden dataset. They require API credits and take longer, so they gate release candidates rather than individual PRs.

### Why Two Tiers?

Running LLM-as-a-judge on every PR commit is financially unviable for a solo engineer and introduces non-determinism (tests pass locally, fail in CI due to API jitter). The tiered approach gives fast, reliable feedback on every change while reserving expensive quality checks for nightly validation.

## Resilience: What Breaks in Production

### Circuit Breaker Model Fallback

When Claude Sonnet hits rate limits or latency spikes, the circuit breaker trips and routes to Haiku. State transitions (CLOSED/HALF_OPEN/OPEN) are tracked via Prometheus gauge. Recovery is automatic after configurable cooldown.

### Semantic Cache

Repeat queries hit the embedding similarity cache (cosine threshold 0.95) instead of making redundant LLM calls. Prometheus counters track hit rate and cumulative USD saved. At production traffic patterns, this reduces LLM costs by 30-50%.

### Graceful Degradation

If Redis is unavailable: cache misses, rate limiting disabled, SSE falls back to polling. If Langfuse is unreachable: traces are silently dropped (fire-and-forget). If the primary model is down: circuit breaker routes to fallback. The system always returns a response.

## Cost Model: The Real Numbers

Token pricing is only ~5% of total production AI system costs. The real budget:

| Component | Monthly Cost | Notes |
|---|---|---|
| Hosting (Fly.io, 512MB) | ~$7-15 | Single machine, auto-stop on idle |
| PostgreSQL (Fly managed) | ~$0-7 | Shared CPU, included storage |
| Redis (Upstash on Fly) | ~$0-5 | Usage-based, free tier covers demo traffic |
| Langfuse (cloud free tier) | $0 | 1M spans/month |
| LLM API (Claude) | Variable | ~$0.003-0.01 per extraction |
| **Total** | **$7-27/month** | |

For scale-readiness (not implemented yet, but documented):

| At Scale | What Changes |
|---|---|
| 10x traffic | Add HNSW index on pgvector, PgBouncer for connection pooling |
| 100x traffic | Tail-based sampling (5% success traces, 100% errors), dedicated DB instance |
| Enterprise | CDC (Debezium) for vector sync, Presidio for full PII entity recognition |

## The HITL Data Advantage

Human corrections are not just UX. They are data assets.

DocExtract's review queue captures structured corrections: original extraction, corrected fields, error type, reviewer ID. This creates organic training data for future fine-tuning without the typical $2K-8K dataset curation cost.

The correction loop stores: input document, model output, human correction, corrected fields, and error classification. When correction volume reaches critical mass, this feeds directly into a QLoRA fine-tuning pipeline (DPO pairs already exported in JSONL format).

## Metrics

| Metric | Value |
|---|---|
| Extraction accuracy (golden eval) | 94.6% |
| Test count | 1,155 |
| Code coverage | 87.25% |
| Extraction latency (p50) | ~8s |
| Search latency (p95) | <100ms |
| SSE streaming latency | <500ms |
| Circuit breaker recovery | 60s configurable |
| Semantic cache threshold | 0.95 cosine similarity |

## What I Would Do Differently

1. **Add Langfuse from day one.** Retrofitting observability onto 40+ endpoints is more work than building it in. The Sync Sidecar pattern adds ~10 lines per endpoint.

2. **Start with cloud-managed everything.** Self-hosting Langfuse requires ClickHouse + Redis + S3. For a solo engineer, the cloud free tier (1M spans/month) is the right call.

3. **Tier the eval strategy earlier.** I originally planned to run DeepEval on every PR. At $0.003+ per metric per test case, that's $50-100/month in API costs for a 50-case golden set. The tiered approach (deterministic CI + nightly LLM-judge) is the sustainable pattern.

## Stack

FastAPI, PostgreSQL + pgvector, Redis, Claude API (Sonnet + Haiku), Langfuse, DeepEval, ARQ (async workers), Docker, Kubernetes (Kustomize), AWS Terraform, GitHub Actions CI/CD
