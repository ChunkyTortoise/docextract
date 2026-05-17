# Eval Failure Analysis

This note lists the failure modes DocExtract is designed to catch, the current mitigation, and the next test or experiment that would make the system stronger.

## Failure Modes

| Failure mode | What breaks | Current detection or mitigation | Next experiment |
|---|---|---|---|
| OCR noise | Characters collapse, totals lose digits, and IDs become partially unreadable. | Adversarial OCR-noise cases require best-effort extraction with nulls for unreadable fields. Low-confidence outputs enter review. | Add page-image fixtures for the worst OCR cases and compare Tesseract vs vision extraction. |
| Ambiguous dates | Dates like `03/04/24` can be parsed as US or non-US formats. | Golden cases include ambiguous and non-US date formats; validators check schema and critical fields. | Add locale hints to classification and measure field-level date accuracy by document type. |
| Missing totals | Invoices may contain subtotal, tax, partial payment, credit memo, or balance due without a clear final total. | Golden invoice cases include partial payment and credit memo examples; business validation flags inconsistent totals. | Add arithmetic consistency scoring to eval output and route mismatches to human review. |
| Prompt injection | Source text may contain instructions to ignore the schema or exfiltrate data. | Promptfoo assertions block injection artifacts; adversarial cases include prompt-injection text. | Add provider-specific judge checks for instruction-following leakage. |
| Non-USD currency | Currency symbols and decimal separators can be misread or normalized incorrectly. | Golden cases include EUR, JPY, and MXN examples; expected outputs preserve currency. | Add a currency-normalization eval slice with locale-specific decimal separators. |
| Identity documents | IDs have high privacy risk and lower tolerance for field errors. | Identity documents use a higher confidence threshold and PII guardrails. | Expand identity cases and report per-field precision for document number, name, and expiration date. |
| Long multi-page documents | Important fields may be split across pages or buried in appendices. | Worker emits page-level progress events; chunking keeps extraction within configured limits. | Add a long-document eval split and measure recall as page count increases. |
| PII handling | Raw SSNs, card numbers, phones, or emails can leak into traces. | `sanitize_for_trace` redacts supported PII patterns before external tracing; guardrails detect PII in outputs. | Add trace-sanitization regression cases for nested JSON and list payloads. |

## How To Use This In Review

When an eval score drops, map the failed case to one of these modes first. If it is a known mode, add a regression case before changing prompts. If it is a new mode, add the failure to this document with the mitigation and acceptance test.
