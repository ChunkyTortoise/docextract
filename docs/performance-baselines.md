# Performance Baselines

Unverified planning estimates for the DocExtract extraction pipeline, in a document originally dated 2026-03-24. Tables below are design assumptions, not committed live benchmark results. The reproducible extraction replay and its separate denominators are documented in [retrieval-extraction evidence](retrieval-extraction-evidence.md).

## Token Usage by Document Type

Assumed tokens per extraction for planning (Sonnet primary model, single-page documents); not measured averages:

| Document Type | Avg Input Tokens | Avg Output Tokens | Total Tokens | Notes |
|---------------|-----------------|-------------------|-------------|-------|
| Invoice | ~1,200 | ~400 | ~1,600 | Standard format, 5-15 fields |
| Receipt | ~600 | ~250 | ~850 | Shorter documents, fewer fields |
| Purchase Order | ~1,800 | ~600 | ~2,400 | Higher due to line item tables |
| Bank Statement | ~2,200 | ~700 | ~2,900 | Transaction lists increase token count |
| Medical Record | ~1,500 | ~500 | ~2,000 | Diagnoses/medications add complexity |
| Identity Document | ~400 | ~200 | ~600 | Shortest documents, fixed fields |

**Two-pass planning assumption**: Assume correction on ~15-20% of extractions with ~800 additional input and ~300 output tokens. Neither trigger rate nor token overhead is established by a committed live run.

## Latency Distribution

Illustrative latency design estimates, not empirical percentiles. No committed load run reproduces this distribution; a pricing table cannot establish wall time:

| Operation | p50 | p95 | p99 | Conditions |
|-----------|-----|-----|-----|------------|
| Single-page extraction | 2.1s | 4.1s | 13.2s | Sonnet primary, includes Pass 2 probability (modeled) |
| Multi-page extraction (10 pages) | 18s | 38s | 52s | Page-by-page streaming via SSE |
| Document classification | 0.8s | 1.6s | 2.4s | Haiku primary |
| Semantic search | 45ms | 120ms | 180ms | pgvector HNSW, 768-dim, ~10K documents |
| Embedding generation | 0.3s | 0.8s | 1.2s | Gemini embedding, single document |

**Circuit breaker planning assumption**: Allow ~2-4s additional latency during provider failover. This is not an observed p99 change.

## Cost per Extraction

Unverified planning assumptions for prices, model-price mappings and workload. Neither prices nor mappings are established provider quotes, historical or current, and these are not observed billing:

| Model | Input Cost/1K | Output Cost/1K | Avg Cost/Extraction | Notes |
|-------|--------------|----------------|--------------------|----|
| Claude Sonnet 4.6 | $0.003 | $0.015 | ~$0.010 | Primary extraction model |
| Claude Haiku 4.5 | $0.00025 | $0.00125 | ~$0.001 | Fallback/classification model |

**Illustrative blended cost per document**: ~$0.012 under the assumed 80% Sonnet / 20% Haiku allocation and unverified model-price mappings. Provider allocation, classification overhead and embedding cost have not been measured; this figure is not a verified all-in cost.

**Monthly planning examples**: Multiples of the illustrative blended cost above, using the same unverified prices, mappings and allocation assumptions. These are not budget quotes.

| Volume | Blended Cost | Notes |
|--------|-------------|-------|
| 1,000 docs | ~$12 | Small business |
| 10,000 docs | ~$120 | Mid-market |
| 100,000 docs | ~$1,200 | Enterprise (volume discounts may apply) |

## Model Comparison: Evidence Status

No committed paired Sonnet/Haiku run establishes comparative accuracy, completeness, hallucination rate, latency or cost. The extraction replay is a score of frozen prediction fixtures, not a live model comparison.

The default configuration uses Haiku-first classification and Sonnet-first extraction with fallback. This describes routing intent, not observed traffic allocation or a quantified accuracy tradeoff. Runtime judging uses a separate Gemini-first, Claude-fallback path and is disabled by default.

## Extraction Score by Document Type

Use the [README results and methodology](../README.md#methodology--limits) and [evidence note](retrieval-extraction-evidence.md) for the current weighted field-level replay score and per-type counts. Do not combine the replay population with the separate eval authoring corpus or treat it as a live-model accuracy estimate.

## Error Budget

The [SLO document](slo.md) describes targets. Current live accuracy, uptime, latency percentiles and calibration are not established by committed operational measurements, so remaining error budgets cannot be calculated from these design estimates or frozen extraction fixtures.
