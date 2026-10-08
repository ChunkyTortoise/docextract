# Cost Model

## Token Cost Comparison

Unverified planning assumptions per 1,000 tokens, retained only to illustrate the estimates below. Neither the numeric prices nor their mappings to model names are established provider quotes, historical or current. They are not observed billing; verify provider terms before budgeting.

| Model | Input | Output | Best For |
|-------|-------|--------|----------|
| Claude Sonnet 4.6 | $0.003 | $0.015 | Complex extraction, high accuracy |
| Claude Haiku 4.5 | $0.00025 | $0.00125 | Classification, simple queries |
| Claude Opus 4.6 | $0.015 | $0.075 | Evaluation, edge cases |

Classification defaults to Haiku-first (failover chain in config); extraction uses Sonnet. A z-test A/B tool lives in `app/services/model_ab_test.py` for offline model comparison; it is not wired as a live traffic split.

## Per-Operation Costs

Illustrative cost and latency assumptions. Cost figures depend on unverified model-price mappings and token-count assumptions; latency figures are separate design estimates, not derived from prices or measured wall times:

| Model | Operation | Avg Cost/Request | Avg Latency (modeled) |
|-------|-----------|-----------------|-------------|
| claude-sonnet-4-6 | Extraction (2-pass) | $0.004-$0.012 | 1.8s |
| claude-haiku-4-5 | Classification | $0.0003-$0.001 | 0.4s |

**Model routing strategy:** Classification defaults to Haiku-first and extraction to Sonnet-first. Reranking uses local TF-IDF, not an LLM. The feature-flagged runtime judge tries Gemini 2.5 Flash first and falls back to the configured classification model (Haiku by default); it is disabled by default. Judge cost and latency are unmeasured. See [ADR-0018](adr/0018-independent-judge-and-multi-provider-router.md) and [ADR-0019](adr/0019-reranker-and-agentic-reflection.md). Use `model_ab_test.py` to compare models offline; do not treat allocation as a measured live split until an experiment is recorded.

## Cost Calculator

Illustrative planning estimates, not measured workload averages. Prices, model-price mappings, token counts and correction overhead are unverified assumptions.

| Document Type | Model | Avg Tokens | Cost/Doc | Cost/1,000 |
|--------------|-------|------------|----------|------------|
| Invoice (1 page) | Sonnet | ~2,500 | $0.025 | $25.00 |
| Invoice (1 page) | Haiku (fallback) | ~2,500 | $0.004 | $4.00 |
| Receipt | Sonnet | ~1,200 | $0.012 | $12.00 |
| Multi-page PDF (10p) | Sonnet | ~15,000 | $0.150 | $150.00 |

*The retained calculation uses the unverified planning prices and model-price mappings above, plus assumed ~20% correction overhead. Actual correction frequency, embedding cost and per-document cost remain unmeasured.*

## Monitoring

Cost monitoring: `/api/v1/metrics` (Prometheus) + Cost Dashboard in Streamlit frontend.

Track live cost-per-query in the [Cost Dashboard](../frontend/pages/cost_dashboard.py).
