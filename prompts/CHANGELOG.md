# Prompt Changelog

All notable changes to production prompts are documented here.
Format: Keep a Changelog; versions follow SemVer per prompt family.

Each prompt file lives at `prompts/<family>/vX.Y.Z.txt` and is registered in
Langfuse as `docextract-<family>` with label `vX.Y.Z` on deploy.
Commits that touch only `prompts/**` are tagged `prompt/<family>-vX.Y.Z`.

---

## [extraction/1.1.0] — 2026-03-22 — @cayman

**Rationale:** Field-level confidence scoring was missing, causing downstream consumers to treat all extractions as equally reliable. Also added explicit date normalization guidance to reduce errors on partial-date receipts (e.g., `Mar '24` was being returned as-is rather than null).

**Diff summary:** +18 lines, -4 lines. No JSON schema changes.

**Eval delta vs baseline (autoresearch/baseline.json, 28-case golden set, overall_score: 0.9555):**

| Metric | Before (v1.0.0 est.) | After (v1.1.0) | Delta |
|---|---|---|---|
| extraction_f1 | 0.938 | 0.956 | +0.018 |
| faithfulness | 0.912 | 0.927 | +0.015 |
| answer_relevancy | 0.884 | 0.889 | +0.005 |
| avg_latency_ms | 1,847 | 1,891 | +44 |

*Note: v1.0.0 column is a pre-harness estimate from `scripts/run_eval_ci.py` (legacy golden runner). The multi-metric harness baseline (Ragas + LLM-judge) requires regeneration after API credit top-up. See `evals/CHANGELOG.md` [1.1.0] for details.*

**Langfuse:** `docextract-extraction@v1.1.0` — push via `python scripts/sync_langfuse.py --family extraction --version 1.1.0 --label production`
**Git tag:** `prompt/extraction-v1.1.0`
**PR:** (to be assigned on merge)

---

## [extraction/1.0.0] — 2026-03-01 — @cayman

**Rationale:** Initial production extraction prompt. Covers all six document types (invoice, receipt, purchase_order, bank_statement, medical_record, identity_document). JSON schema enforcement with explicit null-for-missing-field instruction.

**Langfuse:** `docextract-extraction@v1.0.0`
**Git tag:** `prompt/extraction-v1.0.0`

---

## [classification/1.0.0] — 2026-03-01 — @cayman

**Rationale:** Initial classification prompt. Returns one of six doc_type values + confidence. Used to route documents to the correct extraction prompt family.

**Langfuse:** `docextract-classification@v1.0.0`
**Git tag:** `prompt/classification-v1.0.0`

---

## [search/1.0.0] — 2026-03-01 — @cayman

**Rationale:** Initial re-ranking prompt. Takes a query + N passages, returns a relevance-ordered list of passage indices. Used in the semantic search layer after pgvector ANN retrieval.

**Langfuse:** `docextract-search@v1.0.0`
**Git tag:** `prompt/search-v1.0.0`
