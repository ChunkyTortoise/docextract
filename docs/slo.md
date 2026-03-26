# Service Level Objectives (SLOs)

## Overview

These SLOs define the reliability targets for DocExtract AI in a production environment. They inform alerting thresholds, capacity planning, and incident response priorities.

## Extraction Quality

| Metric | Target | Measurement | Rationale |
|--------|--------|-------------|-----------|
| Field-level accuracy | >= 92% | Golden eval suite (28 fixtures, CI-gated) | Baseline established from SROIE benchmark; 2% regression tolerance |
| Pass 2 correction rate | 15-20% of extractions | Two-pass pipeline metrics | Below 10% suggests thresholds too lenient; above 30% suggests prompt degradation |
| Confidence calibration | Brier score < 0.15 | Per-document-type confidence vs actual accuracy | Confidence scores should be meaningful, not inflated |

## Latency

| Metric | Target | Conditions |
|--------|--------|------------|
| Single-page extraction (p50) | < 3s | Sonnet primary, no correction pass |
| Single-page extraction (p95) | < 8s | Includes ~20% correction pass probability |
| Single-page extraction (p99) | < 15s | Includes circuit breaker failover |
| Multi-page extraction (p95) | < 45s | 10-page PDF, page-by-page streaming |
| Semantic search (p95) | < 200ms | pgvector HNSW, 768-dim embeddings |
| Classification (p95) | < 2s | Haiku primary |

## Availability

| Metric | Target | Error Budget |
|--------|--------|-------------|
| API uptime (monthly) | 99.5% | ~3.6 hours/month of allowed downtime |
| Worker availability | 99.0% | Queue absorbs short outages via Redis persistence |
| Search availability | 99.5% | pgvector backed by PostgreSQL |

## Circuit Breaker

| Metric | Target |
|--------|--------|
| Recovery time (model restoration) | < 60s after provider recovery |
| Fallback success rate | > 95% of requests served via fallback model |
| False-open rate | < 1% (circuit should not open on transient errors) |

## Cost

| Metric | Target |
|--------|--------|
| Cost per extraction (Sonnet) | < $0.03 per single-page document |
| Cost per extraction (Haiku fallback) | < $0.005 per single-page document |
| Cost per 1,000 documents | < $25 (blended, assuming 80% Sonnet / 20% Haiku) |
| Embedding cost per document | < $0.001 (Gemini embedding) |

## Monitoring

These SLOs are tracked via:
- **Prometheus metrics**: `llm_call_duration_ms`, `llm_calls_total`, `circuit_breaker_state`
- **Golden eval CI gate**: Runs on every PR, blocks merge on regression
- **RAGAS evaluation**: Context recall, faithfulness, answer relevancy (main branch)
- **Cost tracker**: Per-request USD computation via `llm_traces`

See [Prometheus alert rules](../deploy/prometheus/alerts.yml) for automated alerting on SLO breaches.

## Revision History

| Date | Change | Rationale |
|------|--------|-----------|
| 2026-03-24 | Initial SLO document | Establish baseline targets from existing metrics |
