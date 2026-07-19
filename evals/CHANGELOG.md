# Eval Corpus Changelog

## [2.0.0] — 2026-07-18

**Phase B hireability expansion** 120 → 200 cases. All new `ground_truth_contexts` are verbatim spans from `input_text`.

### Golden set: 87 → 150 cases (+63)

| Batch | IDs | Count |
|---|---|---|
| G14 invoice | invoice_17_freight_forwarder … invoice_28_insurance_premium | 12 |
| G15 receipt | receipt_16_hotel … receipt_26_self_checkout | 11 |
| G16 purchase_order | purchase_order_14_catering … purchase_order_23_consulting_t_and_m | 10 |
| G17 bank_statement | bank_statement_12_savings … bank_statement_21_cad_small_business | 10 |
| G18 medical_record | medical_record_12_dental … medical_record_21_home_health | 10 |
| G19 identity_document | identity_drivers_license_03_tx … identity_green_card_01_us | 10 |

Distribution after expansion: invoice ×36, receipt ×27, purchase_order ×24, bank_statement ×22, medical_record ×22, identity_document ×19.

### Adversarial set: 33 → 50 cases (+17)

| Attack type | IDs | Count |
|---|---|---|
| prompt_injection | adv_prompt_injection_base64, adv_prompt_injection_unicode_homoglyph, adv_prompt_injection_few_shot_poison | 3 |
| pii_leak | adv_pii_bank_account_in_invoice, adv_pii_passport_in_po, adv_pii_insurance_member_id, adv_pii_drivers_license_in_receipt | 4 |
| hallucination_bait | adv_hallucinate_implicit_tax, adv_hallucinate_missing_due_date, adv_hallucinate_line_item_from_header, adv_hallucinate_currency_from_symbol_ambiguity | 4 |
| ocr_noise | adv_ocr_noise_strikethrough, adv_ocr_noise_rotated_margin, adv_ocr_noise_table_wrap | 3 |
| edge_case | adv_edge_conflicting_dates, adv_edge_negative_qty_credit | 2 |
| long_document | adv_long_document_boilerplate | 1 |

### Labeling protocol (Phase B)

- Single annotator (Cayman Roden); IAA N/A — documented limitation.
- Each new case: author `input_text` → manually compute `expected_output` → select 1–5 verbatim `ground_truth_contexts` spans.
- Spot-check ~10% of new labels before citing corpus as interview-defensible hand-verified.
- Regenerate multi-metric baseline after API budget (`make eval && make eval-baseline`).
- Deterministic fixtures remain 28; live-metered remainder grows with corpus (172 pending).

### Follow-ups

- Run `make eval-fast` to validate harness picks up all 200 cases.
- Human spot-check on adversarial safe-behavior rubrics recommended before W3 multi-provider gate.

---

All additions, retirements, and schema changes to `golden_set.jsonl` and `adversarial_set.jsonl`.

---

## [1.2.0] — 2026-07-17

**Evalgate W1 expansion** 72 → 120 cases. All new `ground_truth_contexts` are verbatim spans from `input_text`.

### Golden set: 51 → 87 cases (+36)

| Batch | IDs | Count |
|---|---|---|
| G8 invoice | invoice_11_cad_consulting … invoice_16_late_fee | 6 |
| G9 receipt | receipt_10_pharmacy … receipt_15_parking | 6 |
| G10 purchase_order | purchase_order_08_it_hardware … purchase_order_13_services_sow | 6 |
| G11 bank_statement | bank_statement_06_payroll_heavy … bank_statement_11_business_checking | 6 |
| G12 medical_record | medical_record_06_urgent_care … medical_record_11_allergy_list | 6 |
| G13 identity_document | identity_drivers_license_02_ca … identity_passport_04_jp | 6 |

Distribution after expansion: invoice ×24, receipt ×16, purchase_order ×14, bank_statement ×12, medical_record ×12, identity_document ×9.

### Adversarial set: 21 → 33 cases (+12)

| Attack type | IDs | Count |
|---|---|---|
| prompt_injection | adv_prompt_injection_ignore_previous, adv_prompt_injection_markdown_comment, adv_prompt_injection_json_schema_swap | 3 |
| pii_leak | adv_pii_email_phone_dump, adv_pii_employee_id_badge, adv_pii_mrn_in_invoice | 3 |
| hallucination_bait | adv_hallucinate_missing_currency, adv_hallucinate_missing_customer, adv_hallucinate_ambiguous_total | 3 |
| ocr_noise / edge_case | adv_ocr_noise_column_shift, adv_edge_duplicate_invoice_numbers, adv_edge_zero_total_valid | 3 |

### Follow-ups

- Spot-check ~10% of new labels before citing as interview-defensible hand-verified.
- Regenerate multi-metric baseline after API budget (`make eval && make eval-baseline`).
- Deterministic fixtures remain 28; live-metered remainder grows with corpus.

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
