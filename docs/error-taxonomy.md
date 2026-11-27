# Error taxonomy: unsupported extracted values

Source run: `python3 scripts/eval_hallucination.py --verbose` on 2026-11-17, over the 28 committed prediction fixtures in `autoresearch/golden_responses/` (all produced by claude-sonnet-4-6). The scorer checks each extracted field value against the document text in `autoresearch/eval_dataset_72.json` and calls no model.

Result: 482 values scored, 474 grounded (450 exact, 22 within OCR tolerance, 1 by segment match, 1 by token match), 8 unsupported. 24 of 28 cases are fully grounded.

The categories below were assigned by reading each of the 8 unsupported values next to its source text. With n = 8 these are observations, not rates.

| Category | Count | Cases | What happened |
|---|---|---|---|
| Merged line items | 4 | `purchase_order_large` | Source rows 5 ("USB-C Hub", qty 10, $350.00) and 6 ("Webcam HD", qty 5, $600.00) became one row: description "USB-C Hub + Webcam HD", quantity 15, unit price 0.0, total 950.0. All four fields of the fabricated row are unsupported. |
| Wrong number | 2 | `receipt_01`, `purchase_order_01` | Subtotal 21.99 where the receipt says $22.00; line 3 total 650.0 where the purchase order says $675.00. |
| Name substitution from model knowledge | 1 | `medical_multi_icd` | Medication "Semaglutide" where the record says "Ozempic" (the brand name). The value is plausible but not in the document. |
| Paraphrased text field | 1 | `medical_multi_icd` | Diagnosis "Type 2 diabetes with hyperglycemia" where the record says "Type 2 diabetes mellitus with hyperglycemia". |

What each category implies:

- Merged line items: the fabricated row has quantity 15, unit price 0.0 and total 950.0, so a per-row check that quantity times unit price equals the line total would flag it. `_validate_purchase_order` in `app/services/validator.py` checks only that quantities are positive, so this row passes runtime validation today.
- Wrong number: a check that line totals sum to the stated subtotal would flag both. `app/services/validator.py` checks invoice totals against subtotal plus tax minus discount and receipt totals against the sum of items, but not subtotals against line items, and the replay does not run the validator at all.
- Name substitution and paraphrase: the field-level replay gives these partial credit through string similarity, so they lower the score only slightly. The grounding scorer is the check that catches them.

Not covered here: retrieval errors, agent tool-choice errors and prompt-injection outcomes are not measured by any committed artifact (see the README section "Decisions, failures, limits"). Failure modes the eval set is designed around are in [eval-failure-analysis.md](eval-failure-analysis.md).
