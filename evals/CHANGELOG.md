# Eval Corpus Changelog

All additions, retirements, and schema changes to `golden_set.jsonl` and `adversarial_set.jsonl`.

---

## [1.1.0] — 2026-04-15

**Corpus expansion** 28 → 72 cases. All `ground_truth_contexts` replaced with manually-selected verbatim spans. Zero `needs_review` tags remaining.

### Golden set: 16 → 51 cases

| Batch | IDs | Count |
|---|---|---|
| W2 anchors | invoice_03_partial_payment, medical_pediatric_visit | 2 |
| G1 invoice | invoice_04_saas through invoice_b2b_po | 9 |
| G2 receipt | receipt_02_gas_station through receipt_09_tip_adjusted | 8 |
| G3 purchase_order | purchase_order_02_multi_item through purchase_order_07_emergency | 6 |
| G4 bank_statement | bank_statement_02_mxn through bank_statement_05_overdraft | 4 |
| G5 medical_record | medical_record_03_lab_results through medical_record_05_surgery_note | 3 |
| G6 identity_document | identity_passport_02_mex, identity_drivers_license_01 | 2 |
| G7 edge-valid | doc_short_valid | 1 |

Final distribution: invoice ×18, receipt ×10, purchase_order ×8, bank_statement ×6, medical_record ×6, identity_document ×3.

### Adversarial set: 12 → 21 cases

| New attack type | IDs | Count |
|---|---|---|
| pii_leak | adv_pii_credit_card_in_receipt, adv_pii_ssn_in_medical, adv_pii_dob_in_identity, adv_pii_phi_in_bank_statement | 4 |
| hallucination_bait | adv_hallucinate_missing_vendor, adv_hallucinate_missing_total, adv_hallucinate_blank_lineitems, adv_hallucinate_partial_date | 4 |
| prompt_injection (new vector) | adv_prompt_injection_tool_call | 1 |

### Ground truth context fix

All 28 original cases had auto-derived sliding-window regex stubs. Replaced with manually-selected verbatim spans from each case's `input_text`. This enables accurate Ragas `context_precision` measurement.

### Diversity guardrails applied

- OCR noise: invoice_04_saas, receipt_02_gas_station, receipt_04_retail_clothing, bank_statement_04_wire_transfer
- Non-English names/scripts: invoice_05_eur_web_dev (Ethiopian client), invoice_08_prepaid_deposit (Ghanaian names), bank_statement_02_mxn (Spanish), medical_record_03 (Ghanaian), medical_record_04 (Latina), medical_record_05 (Arabic/Chinese), purchase_order_07 (South Asian), receipt_04 (Japanese), identity_passport_02_mex (Spanish)
- Non-USD currencies: EUR (invoice_05), JPY (adv_hallucinate_blank_lineitems), MXN (bank_statement_02)
- Negative/edge amounts: invoice_10_credit_memo (-$1,650), receipt_07_refund (-$119.33), bank_statement_05_overdraft

### Baseline regen status

The multi-metric baseline (`autoresearch/baseline.json`, written by `eval_gate.py --accept-baseline`) requires running `make eval` which calls the Anthropic API for extraction scoring. Blocked pending API credit top-up.

Current `autoresearch/baseline.json` reflects the **legacy 28-case golden eval** (overall_score: 0.9555, case_count: 28, last updated 2026-04-15). This is the v1.0.0 floor from `run_eval_ci.py`, NOT the multi-metric harness baseline.

Action required: run `make eval && make eval-baseline` after topping up API credits. The post-expansion score is expected to drop below 0.9555 because the 9 new adversarial cases (pii_leak, hallucination_bait) are harder. This is expected expansion behavior, not a prompt regression.

---

## [1.0.0] — 2026-04-14

**Initial migration** from `autoresearch/eval_dataset.json` (28 cases, bespoke JSON format) to industry-standard JSONL.

**Migrated to `golden_set.jsonl`** (16 cases):
- invoice_01, invoice_02, invoice_ocr, invoice_foreign_currency, invoice_discount
- receipt_01, receipt_sparse
- purchase_order_01, purchase_order_large
- bank_statement_01, bank_statement_empty
- identity_passport
- medical_record_01, medical_multi_icd
- doc_empty, doc_truncated

**Migrated to `adversarial_set.jsonl`** (12 cases):
- `prompt_injection` (4): adv_prompt_injection_system, adv_prompt_injection_hidden, adv_prompt_injection_roleplay, adv_prompt_injection_data_exfil
- `ocr_noise` (4): adv_corrupted_pdf, adv_scanned_table, adv_handwritten_receipt, adv_mixed_language
- `edge_case` (3): adv_blank_page, adv_duplicate_fields, adv_redacted_statement
- `long_document` (1): adv_long_document

**Schema additions vs old format:**
- `expected_output` (renamed from `expected`)
- `ground_truth_contexts` (new — auto-derived; needs manual review)
- `tags` (encodes weight + critical_fields + currency)
- `attack_type` + `expected_safe_behavior` (adversarial only)

**Note:** `ground_truth_contexts` fields are auto-derived stubs. Manual review and improvement is tracked as Day 1 follow-up task.

**Migration script:** `scripts/migrate_fixtures_to_jsonl.py`
