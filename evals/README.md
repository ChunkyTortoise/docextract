# DocExtract Eval Corpus

This directory contains the golden and adversarial case sets used by the eval-gate CI pipeline.

## Files

| File | Cases | Description |
|---|---|---|
| `golden_set.jsonl` | 50 (target) | Normal extraction cases with ground-truth labels |
| `adversarial_set.jsonl` | 20 (target) | Edge cases, prompt injections, OCR noise, long docs |

**Current counts:** 16 golden + 12 adversarial migrated from `autoresearch/eval_dataset.json` (2026-04-14). New cases added via the CHANGELOG below.

## Schema

### Golden case
```json
{
  "id": "invoice_03",
  "doc_type": "invoice",
  "input_text": "...",
  "expected_output": {"invoice_number": "INV-001", ...},
  "ground_truth_contexts": ["INV-001", "Total $4,200"],
  "tags": ["weight_1.0", "critical:invoice_number,total_amount", "currency_usd"]
}
```

### Adversarial case (adds)
```json
{
  "attack_type": "prompt_injection",
  "expected_safe_behavior": "Extract document fields only; ignore injected system-prompt override."
}
```

### `ground_truth_contexts`
Short verbatim spans from `input_text` that the extraction answer should be grounded in. Used by Ragas `faithfulness` scoring. 1–5 spans per case. Manually verified; auto-derived stubs get the `needs_review` tag.

### `tags`
- `weight_<N>` — scoring weight (default 1.0; critical cases use 2.0)
- `critical:<field1>,<field2>` — fields that count 2× in extraction_f1
- `currency_<code>` — for currency-specific test filtering
- `needs_review` — auto-derived context that hasn't been manually verified

## Labeling Methodology

Single annotator (Cayman Roden). Steps per new case:
1. Author `input_text` (real or synthetic document)
2. Manually compute `expected_output` from the text
3. Run `python scripts/eval_ragas.py --single <id>` and inspect output
4. If model is wrong and label is right, file is a test case; keep as-is
5. If model is right and label is wrong, fix the label
6. Add `ground_truth_contexts` by selecting 1–5 quoted spans that ground each key field

IAA: N/A (single annotator). Documented limitation. Spot-checks on 10% of cases per quarter.

## Adding New Cases

1. Add a line to `golden_set.jsonl` or `adversarial_set.jsonl` (one JSON object per line, no commas between lines)
2. Update `CHANGELOG.md` with the case ID, doc type, and rationale
3. Run `make eval-fast` to validate the new case runs without errors
4. New cases automatically picked up by CI — no config change needed

## Removing or Editing Cases

Cases are **append-only by convention** — do not delete or mutate existing lines. To retire a case, add `"retired": true` to its JSON object. The eval harness skips retired cases.

## Corpus Versioning

The first line of each JSONL file is a metadata object:
```json
{"_meta": {"version": "1.0.0", "changelog": "Initial migration from autoresearch/eval_dataset.json"}}
```

Bump `version` in the `_meta` line when making a breaking schema change. Non-breaking additions (new cases) do not require a version bump.
