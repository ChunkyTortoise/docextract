# Cost Model

## Token Cost Comparison

Token cost comparison across models (per 1,000 tokens, as of 2026):

| Model | Input | Output | Best For |
|-------|-------|--------|----------|
| Claude Sonnet 4.6 | $0.003 | $0.015 | Complex extraction, high accuracy |
| Claude Haiku 4.5 | $0.00025 | $0.00125 | Classification, simple queries |
| Claude Opus 4.6 | $0.015 | $0.075 | Evaluation, edge cases |

Classification defaults to Haiku-first (failover chain in config); extraction uses Sonnet. A z-test A/B tool lives in `app/services/model_ab_test.py` for offline model comparison; it is not wired as a live traffic split.

## Per-Operation Costs

Modeled estimates (pricing table × typical token counts; not load-tested wall times):

| Model | Operation | Avg Cost/Request | Avg Latency (modeled) |
|-------|-----------|-----------------|-------------|
| claude-sonnet-4-6 | Extraction (2-pass) | $0.004-$0.012 | 1.8s |
| claude-haiku-4-5 | Classification | $0.0003-$0.001 | 0.4s |
| claude-sonnet-4-6 | LLM Judge | $0.002-$0.006 | 1.2s |

**Model routing strategy:** Classification and re-ranking use Haiku (cheaper primary). Full extraction uses Sonnet. LLM judge uses Sonnet for accuracy. Use `model_ab_test.py` to compare models offline; do not treat allocation as a measured live split until an experiment is recorded.

## Cost Calculator

| Document Type | Model | Avg Tokens | Cost/Doc | Cost/1,000 |
|--------------|-------|------------|----------|------------|
| Invoice (1 page) | Sonnet | ~2,500 | $0.025 | $25.00 |
| Invoice (1 page) | Haiku (fallback) | ~2,500 | $0.004 | $4.00 |
| Receipt | Sonnet | ~1,200 | $0.012 | $12.00 |
| Multi-page PDF (10p) | Sonnet | ~15,000 | $0.150 | $150.00 |
| Embedding (any) | Gemini | 768-dim | $0.0004 | $0.40 |

*Costs assume Anthropic March 2026 pricing. Two-pass correction adds ~20% to base cost for low-confidence documents.*

## Monitoring

Cost monitoring: `/api/v1/metrics` (Prometheus) + Cost Dashboard in Streamlit frontend.

Track live cost-per-query in the [Cost Dashboard](../frontend/pages/cost_dashboard.py).
