# Evaluation Harness Guide

## Overview

DocExtract uses a golden eval harness to measure extraction quality and prevent regressions. The harness runs without API calls by replaying recorded model responses against ground-truth fixtures.

## Architecture

```
autoresearch/
├── eval.py                 # Scoring engine: field-level accuracy, Brier score, calibration
├── eval_dataset.json       # 28 test fixtures (16 standard + 12 adversarial)
├── golden_responses/       # Recorded model outputs (one JSON per fixture)
├── fixtures.py             # Golden response loader
├── reporter.py             # Report generation (JSON, Markdown, delta comparison)
├── baseline.json           # Current accuracy baseline for CI regression gate
└── results.tsv             # Append-only score history

scripts/
└── run_eval_ci.py          # CI gate: runs golden eval, checks regression, outputs markdown
```

### Data Flow

```
eval_dataset.json ──► eval.py loads cases
                         │
                         ├── --golden mode: load golden_responses/*.json
                         ├── --dry-run mode: generate mock extractions
                         └── default mode: call Claude API (requires ANTHROPIC_API_KEY)
                         │
                         ▼
                    score_extraction() per case
                         │
                         ▼
                    CaseResult (score, completeness, hallucinations, format_valid, confidence)
                         │
                         ▼
                    Aggregate: weighted mean, Brier score, calibration curve, model comparison
```

## How to Run

```bash
# Golden eval (no API calls, uses recorded responses)
python -m autoresearch.eval --golden

# Dry-run (mock extractions for testing harness changes)
python -m autoresearch.eval --dry-run

# Live eval (calls Claude API, requires ANTHROPIC_API_KEY)
python -m autoresearch.eval

# CI regression gate
python scripts/run_eval_ci.py

# Update baseline after intentional changes
python scripts/run_eval_ci.py --update-baseline
```

## Adding New Fixtures

### Step 1: Add to eval_dataset.json

```json
{
  "id": "my_new_fixture",
  "doc_type": "invoice",
  "weight": 1.0,
  "critical_fields": ["invoice_number", "total_amount"],
  "input_text": "... raw OCR or extracted text ...",
  "expected": {
    "invoice_number": "INV-001",
    "total_amount": 500.0,
    "vendor_name": "Example Corp"
  }
}
```

**Field reference:**
- `id`: Unique identifier, must match golden response filename
- `doc_type`: One of `invoice`, `receipt`, `purchase_order`, `bank_statement`, `medical_record`, `identity_document`
- `weight`: 0.5-1.0 (lower for edge cases, 1.0 for standard documents)
- `critical_fields`: Fields weighted 2x in scoring
- `input_text`: Raw text as received from OCR/extraction
- `expected`: Ground truth extraction output

### Step 2: Create Golden Response

Create `autoresearch/golden_responses/my_new_fixture.json`:

```json
{
  "case_id": "my_new_fixture",
  "model": "claude-sonnet-4-6",
  "recorded_at": "2026-03-24T00:00:00Z",
  "raw_response": "{\"invoice_number\": \"INV-001\", ...}",
  "parsed_extraction": {
    "invoice_number": "INV-001",
    "total_amount": 500.0,
    "vendor_name": "Example Corp"
  }
}
```

### Step 3: Verify

```bash
python -m autoresearch.eval --golden   # Should include new fixture
python scripts/run_eval_ci.py          # Check regression
```

### Step 4: Update Baseline (if score changed intentionally)

```bash
python scripts/run_eval_ci.py --update-baseline
```

## Metric Definitions

### Field-Level Accuracy (0.0-1.0)
- **Scalars**: Normalized Levenshtein similarity for strings; 1% tolerance for numerics
- **Lists**: Best-pair alignment (each expected item matched to best extracted item)
- **Critical field weighting**: Critical fields weighted 2x, others 1x
- **Overall score**: Weighted mean across all cases (case weight * field score)

### Completeness (0.0-1.0)
Ratio of expected non-null fields that have non-null values in the extraction.

### Hallucination Count
Fields where extracted value appears in neither expected output nor input text. Ignores null/empty values and checks for substring matches.

### Format Validity
Whether the extracted dict passes Pydantic schema validation for the document type.

### Brier Score (0.0-1.0)
`mean((confidence - actual_accuracy)^2)` across all cases. Lower is better.
- 0.0 = perfect calibration (confidence exactly matches accuracy)
- 0.25 = coin-flip calibration
- Target: < 0.15 (see SLO doc)

### Calibration Curve
Bins cases by model confidence and computes actual accuracy per bin. Good calibration = diagonal line (80% confident cases should be ~80% accurate).

## CI Gate Behavior

`run_eval_ci.py` enforces a **2% regression tolerance**:

1. Loads all fixtures and runs golden eval
2. Compares overall score to `baseline.json`
3. If `current_score >= baseline_score - 0.02`: **PASS** (exit 0)
4. If `current_score < baseline_score - 0.02`: **FAIL** (exit 1)
5. First run with no baseline: auto-saves current score as baseline

The CI output includes per-doc-type breakdowns, calibration metrics, and model cost comparison.

## Adversarial Fixtures

8 adversarial test cases stress-test edge conditions:

| Fixture | Challenge | Doc Type |
|---------|-----------|----------|
| `adv_corrupted_pdf` | Null bytes, truncated binary data | invoice |
| `adv_blank_page` | Multi-page document with no content | invoice |
| `adv_scanned_table` | OCR artifacts in table (0/O, l/1 confusion) | invoice |
| `adv_duplicate_fields` | Same invoice scanned twice in one document | invoice |
| `adv_mixed_language` | Spanish/English bilingual invoice | invoice |
| `adv_long_document` | 20 line items, 50+ page reference | purchase_order |
| `adv_handwritten_receipt` | Handwritten with OCR character substitutions | receipt |
| `adv_redacted_statement` | [REDACTED] placeholders throughout | bank_statement |
