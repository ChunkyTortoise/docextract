# Performance Baselines

Offline replay evidence and unmeasured operating assumptions for the extraction pipeline. Reconciled 2026-09-25.

## Token Usage by Document Type

Assumed tokens per extraction (Sonnet primary, single-page documents; no metered run):

| Document Type | Avg Input Tokens | Avg Output Tokens | Total Tokens | Notes |
|---------------|-----------------|-------------------|-------------|-------|
| Invoice | ~1,200 | ~400 | ~1,600 | Standard format, 5-15 fields |
| Receipt | ~600 | ~250 | ~850 | Shorter documents, fewer fields |
| Purchase Order | ~1,800 | ~600 | ~2,400 | Higher due to line item tables |
| Bank Statement | ~2,200 | ~700 | ~2,900 | Transaction lists increase token count |
| Medical Record | ~1,500 | ~500 | ~2,000 | Diagnoses/medications add complexity |
| Identity Document | ~400 | ~200 | ~600 | Shortest documents, fixed fields |

**Two-pass overhead**: When Pass 2 correction fires (design target 15-20% of extractions; unmeasured), add ~800 input + ~300 output tokens (modeled).

## Latency Distribution

Modeled (pricing-table × call-distribution / design targets; not reproduced by a committed load run):

| Operation | p50 | p95 | p99 | Conditions |
|-----------|-----|-----|-----|------------|
| Single-page extraction | 2.1s | 4.1s | 13.2s | Sonnet primary, includes Pass 2 probability (modeled) |
| Multi-page extraction (10 pages) | 18s | 38s | 52s | Page-by-page streaming via SSE |
| Document classification | 0.8s | 1.6s | 2.4s | Haiku primary |
| Semantic search | 45ms | 120ms | 180ms | pgvector HNSW, 768-dim, ~10K documents |
| Embedding generation | 0.3s | 0.8s | 1.2s | Gemini embedding, single document |

**Circuit breaker failover**: Adds ~2-4s to p99 when primary model is unavailable (breaker open, fallback model used).

## Cost per Extraction

See the [cost model](cost-model.md) for dated provider rates and an invoice calculation with separate input/output token assumptions. Per-document cost, model fallback frequency, and comparative Sonnet/Haiku accuracy remain unmeasured. The frozen replay score cannot establish a live model comparison.

## Accuracy by Document Type

From the 28-fixture offline replay (case-weighted field-level accuracy; same values as the README table):

| Document Type | Cases | Weighted field accuracy |
|---------------|-------|-----------------------|
| Invoice | 13 | 0.9669 |
| Receipt | 4 | 0.9091 |
| Purchase Order | 3 | 0.9745 |
| Bank Statement | 4 | 0.9613 |
| Medical Record | 3 | 0.9923 |
| Identity Document | 1 | 0.8139 |

Split: 16 golden fixtures at 0.9264 and 12 adversarial fixtures at 1.0. Frozen predictions live in `autoresearch/golden_responses/`; run `scripts/eval_offline_replay.py` to compute scores.

## Error Budget

Based on SLO targets (see `docs/slo.md`):

| SLO | Target | Current | Budget Remaining |
|-----|--------|---------|-----------------|
| Accuracy | >= 92% | 95.5% (28-fixture replay) | 3.5% before breach |
| API uptime | 99.5% | N/A | ~3.6 hrs/month |
| Extraction p95 | < 8s | 4.1s (modeled) | see portfolio-metrics.yaml |
| Search p95 | < 200ms | 120ms (modeled; no committed load run) | 80ms headroom (modeled) |
| Brier score | < 0.15 | unmeasured (offline scorer prints a degenerate 0.0000) | unmeasured |
