# Performance Baselines

Baseline measurements for DocExtract extraction pipeline. Updated 2026-03-24.

## Token Usage by Document Type

Average tokens per extraction (Sonnet primary model, single-page documents):

| Document Type | Avg Input Tokens | Avg Output Tokens | Total Tokens | Notes |
|---------------|-----------------|-------------------|-------------|-------|
| Invoice | ~1,200 | ~400 | ~1,600 | Standard format, 5-15 fields |
| Receipt | ~600 | ~250 | ~850 | Shorter documents, fewer fields |
| Purchase Order | ~1,800 | ~600 | ~2,400 | Higher due to line item tables |
| Bank Statement | ~2,200 | ~700 | ~2,900 | Transaction lists increase token count |
| Medical Record | ~1,500 | ~500 | ~2,000 | Diagnoses/medications add complexity |
| Identity Document | ~400 | ~200 | ~600 | Shortest documents, fixed fields |

**Two-pass overhead**: When Pass 2 correction fires (~15-20% of extractions), add ~800 input + ~300 output tokens.

## Latency Distribution

Measured under typical load (< 10 concurrent extractions):

| Operation | p50 | p95 | p99 | Conditions |
|-----------|-----|-----|-----|------------|
| Single-page extraction | 2.1s | 6.8s | 13.2s | Sonnet primary, includes Pass 2 probability |
| Multi-page extraction (10 pages) | 18s | 38s | 52s | Page-by-page streaming via SSE |
| Document classification | 0.8s | 1.6s | 2.4s | Haiku primary |
| Semantic search | 45ms | 120ms | 180ms | pgvector HNSW, 768-dim, ~10K documents |
| Embedding generation | 0.3s | 0.8s | 1.2s | Gemini embedding, single document |

**Circuit breaker failover**: Adds ~2-4s to p99 when primary model is unavailable (breaker open, fallback model used).

## Cost per Extraction

Based on Anthropic pricing (as of 2026-03):

| Model | Input Cost/1K | Output Cost/1K | Avg Cost/Extraction | Notes |
|-------|--------------|----------------|--------------------|----|
| Claude Sonnet 4.6 | $0.003 | $0.015 | ~$0.010 | Primary extraction model |
| Claude Haiku 4.5 | $0.00025 | $0.00125 | ~$0.001 | Fallback/classification model |
| Gemini Embedding | ~$0 | $0 | ~$0 | Free tier covers typical volume |

**Blended cost per document**: ~$0.012 (80% Sonnet / 20% Haiku fallback, includes classification + embedding).

**Monthly cost estimates**:
| Volume | Blended Cost | Notes |
|--------|-------------|-------|
| 1,000 docs | ~$12 | Small business |
| 10,000 docs | ~$120 | Mid-market |
| 100,000 docs | ~$1,200 | Enterprise (volume discounts may apply) |

## Model Comparison: Sonnet vs Haiku

| Metric | Sonnet 4.6 | Haiku 4.5 | Delta |
|--------|-----------|-----------|-------|
| Field-level accuracy | 92.6% | ~78% | +14.6% |
| Completeness | 0.95 | 0.82 | +0.13 |
| Hallucination rate | ~2% | ~8% | -6% |
| Avg latency (p50) | 2.1s | 0.9s | +1.2s |
| Cost per extraction | $0.010 | $0.001 | 10x |

**When Haiku is used**:
- Document classification (all documents)
- Extraction fallback when Sonnet circuit breaker is open
- Cost-sensitive batch processing (acceptable accuracy tradeoff)

**When Sonnet is preferred**:
- Primary extraction (quality-critical)
- Correction pass (Pass 2 tool_use)
- High-value documents (medical, financial)

## Accuracy by Document Type

From golden eval suite (24 fixtures, baseline 2026-03-24):

| Document Type | Cases | Accuracy | Hardest Case |
|---------------|-------|----------|-------------|
| Invoice | 11 | 0.950 | `invoice_ocr` (OCR artifacts) |
| Receipt | 3 | 0.821 | `receipt_sparse` (minimal info) |
| Purchase Order | 3 | 0.964 | `purchase_order_large` (10 line items) |
| Bank Statement | 3 | 0.916 | `adv_redacted_statement` (redactions) |
| Medical Record | 2 | 0.989 | `medical_multi_icd` (4 ICD codes) |
| Identity Document | 1 | 0.814 | `identity_passport` (date format conversion) |

## Error Budget

Based on SLO targets (see `docs/slo.md`):

| SLO | Target | Current | Budget Remaining |
|-----|--------|---------|-----------------|
| Accuracy | >= 92% | 92.6% | 0.6% before breach |
| API uptime | 99.5% | N/A | ~3.6 hrs/month |
| Extraction p95 | < 8s | 6.8s | 1.2s headroom |
| Search p95 | < 200ms | 120ms | 80ms headroom |
| Brier score | < 0.15 | ~0.05 | 0.10 headroom |
