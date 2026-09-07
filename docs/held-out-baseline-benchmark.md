# Held-out benchmark vs simpler baseline

```text
STATUS: BENCHMARK PLAN / HARNESS ONLY — PERFORMANCE UNMEASURED
```

This document is a plan plus a dry-run harness contract. It does **not** contain a held-out accuracy, latency, or cost number. Do not cite this file as a measured result. Repeating the 28-fixture offline replay does **not** satisfy this benchmark.

Related:

- Held-out live procedure (single-pipeline, unmeasured): [held-out-live-eval-protocol.md](held-out-live-eval-protocol.md)
- Scoring and missing-field rules: [eval-boundary.md](eval-boundary.md)
- Always-on vs paid live paths: [eval-methodology.md](eval-methodology.md)
- Credit / metering gate: [metering-runbook.md](metering-runbook.md)
- Prompt / confidence params: `autoresearch/prompts.yaml` (`version` plus `params.confidence_thresholds`)

This change does **not** run live API evals. `docs/metering-runbook.md` records that `scripts/benchmark.py --limit 1` previously failed solely with HTTP 400 `credit balance is too low`. Funding is not authorized in CONT-RA10.

## 1. Purpose

Compare the **existing two-pass extraction pipeline** (`app.services.claude_extractor.extract`, ADR-0003: Pass 1 extract, Pass 2 correction when confidence is below the per-type threshold) against a **simpler baseline that is still the repo's real Pass 1 path** (same `extract()` call with `correction=False` — no correction pass, no invented second model) on the **same held-out documents** and the **same** `score_extraction` rules from `autoresearch/eval.py` / [eval-boundary.md](eval-boundary.md).

The simpler arm is not a different vendor, a mocked extractor, or a hand-written heuristic. It is Pass 1 of the production Claude extractor with Pass 2 skipped.

**Negative-result policy:** if the simpler (Pass 1 only) arm later matches or beats two-pass on the locked test partition, that is a valid result. Report it. Do not bury it or re-run until two-pass “wins.”

Until a funded run is logged, every cell below stays **UNMEASURED**.

## 2. Relation to existing signals

| Signal | What it is | Denominator | Result status | API cost |
|---|---|---|---|---|
| Offline replay | `python scripts/eval_offline_replay.py --floor 0.85` scores committed `autoresearch/golden_responses/*.json` with `score_extraction` | 28 fixtures; `autoresearch/baseline.json` `overall_score` 0.95546 rounded to **Measured 95.5%** | Measured (CI badge) | Zero |
| RA7 held-out live protocol | Live two-pass `extract()` on a predeclared untouched test partition; same `score_extraction` rubric | Partition declared before scoring; not the 28 fixtures; not the 202-case authoring inventory | **Unmeasured** until a funded run is logged ([protocol](held-out-live-eval-protocol.md)) | Paid (Anthropic) |
| This A/B benchmark (CONT-RA10) | Same locked held-out **test** documents as RA7; **two runners** (`full` = two-pass, `simple` = Pass 1 only); same `score_extraction` | Same untouched test partition; both arms scored with the same rubric | **Unmeasured** (this file) | Paid when funded; not run here |

Do not substitute one row for another:

- Offline replay is the public **Measured 95.5%** claim. Leave that wording unchanged.
- RA7 is a live-quality protocol for the production two-pass path. It is not an A/B vs a simpler extractor.
- This benchmark is not the badge driver. Replaying fixtures, or running `python -m autoresearch.eval --golden`, does not complete it.

## 3. Arms

| Runner id | Code path | Pass 2 correction | Notes |
|---|---|---|---|
| `full` | `extract(text, doc_type, correction=True)` (default) | Yes, when `confidence` is below the per-type threshold | Production two-pass pipeline |
| `simple` | `extract(text, doc_type, correction=False)` | Never | Same Pass 1 prompts, models, retries, and schema path; no correction tool call |

Thresholds for Pass 2 (and for the abstention / low-confidence metric) come from `autoresearch/prompts.yaml`:

- `params.extraction_confidence_threshold` (fallback)
- `params.confidence_thresholds.<doc_type>` (invoice, purchase_order, receipt, bank_statement, identity_document, medical_record, unknown)

Do not invent a “Haiku-only” or regex baseline for this CONT. Do not score `simple` from golden fixtures.

## 4. Metrics to record when funded

Primary metric remains **weighted field-level accuracy** from `score_extraction` (critical fields weight `2.0`). Do not call it F1. Case-level overall uses `sum(case.weight * case.score) / sum(case.weight)`, same as replay.

Fill these only after a funded live run writes an artifact. Until then every value is **UNMEASURED**.

| Metric | `full` (two-pass) | `simple` (Pass 1 only) | Delta (`full` − `simple`) |
|---|---|---|---|
| Field accuracy (overall, weighted) | UNMEASURED | UNMEASURED | UNMEASURED |
| Critical-field failure rate | UNMEASURED | UNMEASURED | UNMEASURED |
| Document-type breakdown | UNMEASURED | UNMEASURED | UNMEASURED |
| Invalid / missing outputs | UNMEASURED | UNMEASURED | UNMEASURED |
| Abstention / low-confidence frequency among accepted outputs | UNMEASURED | UNMEASURED | UNMEASURED |
| End-to-end latency per doc (including retries) | UNMEASURED | UNMEASURED | UNMEASURED |
| Model cost per doc (including retries) | UNMEASURED | UNMEASURED | UNMEASURED |

Definitions (for the future artifact; not results):

- **Field accuracy (overall):** weighted mean of `score_extraction` over the locked test cases (same formula as [eval-boundary.md](eval-boundary.md)).
- **Critical-field failure rate:** among `(case, critical_field)` pairs whose expected value is non-null, the fraction whose per-field `score_extraction` on that key is strictly less than `1.0`.
- **Document-type breakdown:** the overall field-accuracy formula applied within each `doc_type`. Empty types stay UNMEASURED, not zero.
- **Invalid / missing outputs:** fraction of cases with an extractor exception, empty `data`, or `schema_valid is False`.
- **Abstention / low-confidence frequency among accepted outputs:** among cases that produced a parseable extraction (not invalid/missing), the fraction whose model-reported `confidence` is below the per-type threshold from `prompts.yaml`. This is a frequency among accepted outputs, not a second accuracy number.
- **End-to-end latency per doc:** wall clock around `extract()`, including instructor retries and Pass 2 when it runs. Report mean and p95 when N allows; otherwise UNMEASURED.
- **Model cost per doc:** sum of priced in-memory `llm_tracer` traces via `app.services.cost_tracker.CostTracker` (same method as `scripts/benchmark.py`), including retries. Not `docs/cost-model.md`.

Do not copy modeled cost or latency from `docs/cost-model.md` into this table.

## 5. Record fields (every funded artifact)

Each run JSON under `docs/artifacts/held-out-baseline/` must include:

| Field | Source |
|---|---|
| `status` | `BENCHMARK PLAN / HARNESS ONLY — PERFORMANCE UNMEASURED` until publish gate; then `measured` only after Cayman typed yes |
| `date` | UTC timestamp |
| `git_sha` | `git rev-parse HEAD` |
| `model_ids` | `EXTRACTION_MODELS` plus per-case `model_used` from `extract()` |
| `prompt_version` | `version` key in `autoresearch/prompts.yaml` |
| `document_provenance` | partition manifest `sources` plus per-case license/origin |
| `command` | exact argv |
| `artifact_path` | path of this file |
| `run_conditions` | runner ids, `correction` flags, concurrency, whether `--confirm-credit-spend` was set |
| `partition_manifest_sha256` | hash of the locked manifest |
| `test_sha256` | hash of `evals/held_out_live/test.json` at run start |
| `case_count` | number of test cases scored |
| `primary_metric` | `"weighted_field_level_accuracy"` via `score_extraction` |
| `full` / `simple` | per-arm metric objects; omit numeric scores until the funded run |

Also keep stdout/stderr of the command.

## 6. Document sources and partition

Reuse the RA7 layout and constraints. Public or synthetic documents only. New case IDs. No client private documents.

```text
evals/held_out_live/README.md
evals/held_out_live/partition_manifest.json
evals/held_out_live/train_dev.json
evals/held_out_live/test.json
```

Predeclare train/dev vs **untouched test** before any scoring. Hash paths before scoring. Score **test only**. Do not reuse IDs from `autoresearch/eval_dataset.json`, `autoresearch/eval_dataset_72.json`, `evals/golden_set.jsonl`, or `evals/adversarial_set.jsonl`. Do not copy authoring-corpus `input_text` and relabel it.

The committed files in this CONT are stubs (`[]` datasets, undeclared manifest). They are not a scored partition. Adding synthetic cases is a later authoring step; do not commit fake scored results.

Case schema matches `autoresearch/eval_dataset.json` (see the live protocol).

## 7. Harness

```bash
python scripts/held_out_baseline_benchmark.py
python scripts/held_out_baseline_benchmark.py --dry-run
python scripts/held_out_baseline_benchmark.py --scaffold-only
```

These three print the comparison table schema (UNMEASURED cells) and exit 0. They do not call Anthropic.

```bash
python scripts/held_out_baseline_benchmark.py --live --confirm-credit-spend
```

Live path (not run in this CONT):

1. Refuse if `ANTHROPIC_API_KEY` is missing.
2. Refuse if `--confirm-credit-spend` is missing (funding gate; see [metering-runbook.md](metering-runbook.md)).
3. Refuse if `evals/held_out_live/test.json` is empty or hashes do not match a declared manifest.
4. Run `full` then `simple` on each test case; score with `score_extraction`.
5. Write `docs/artifacts/held-out-baseline/<YYYYMMDD>/run.json` (directory is for measured JSON later; none exists today).

Do **not** write held-out predictions into `autoresearch/golden_responses/`.

## 8. Funding and publish gate

Until **all** of the following, keep:

```text
STATUS: BENCHMARK PLAN / HARNESS ONLY — PERFORMANCE UNMEASURED
```

1. Anthropic credit is actually available (not the historical `credit balance is too low` state in [metering-runbook.md](metering-runbook.md)).
2. A live A/B run on the locked test partition is logged with the fields in section 5.
3. Cayman types **yes** to publish the numbers.

Do not merge a “we measured it” claim without that typed yes. Do not invent accuracy, latency, or cost figures to fill the table.

## 9. Explicit non-goals

- Do not treat another offline replay as this benchmark.
- Do not treat RA7’s two-pass-only live protocol as the A/B result.
- Do not publish a 202-case or 72-case `scripts/benchmark.py` sweep as this benchmark.
- Do not change the **Measured 95.5%** 28-fixture wording.
- Do not run live APIs in the plan/harness-only change.
- Retrieval metrics (RA11) are out of scope.
