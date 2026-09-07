# Held-out live eval protocol

```text
STATUS: PROTOCOL ONLY — PERFORMANCE UNMEASURED
```

This document is a procedure. It does not contain a held-out live accuracy number. Do not cite this file as a measured result.

Related:

- Scoring and missing-field rules: [eval-boundary.md](eval-boundary.md)
- Always-on vs paid live paths: [eval-methodology.md](eval-methodology.md)
- Credit / metering gate: [metering-runbook.md](metering-runbook.md)
- Ledger after a funded, approved publish: `docs/portfolio-metrics.yaml` (METRICS-SOT)

This PR does **not** run live API evals. `docs/metering-runbook.md` records that `scripts/benchmark.py --limit 1` previously failed solely with HTTP 400 `credit balance is too low`. Funding is not authorized here.

## 1. Purpose

Establish **fresh model quality** on documents that are **not** the 28-fixture offline replay denominator.

Astra requirement: more offline replay runs alone do not establish fresh model quality. Replay scores committed JSON in `autoresearch/golden_responses/`. It does not call a live model. Repeating `python scripts/eval_offline_replay.py --floor 0.85` cannot answer "how does the current extractor do on unseen documents?"

This protocol is also **separate from the 202-case authoring corpus** (`evals/golden_set.jsonl` 151 lines + `evals/adversarial_set.jsonl` 51 lines). Those JSONL files are inventory and Promptfoo/Ragas inputs. Scoring them, or replaying fixtures whose IDs overlap them, is not a held-out live eval.

Until a funded run is logged, held-out live performance stays **unmeasured**.

## 2. Relation to existing signals

| Signal | What it is | Denominator | Result status | API cost |
|---|---|---|---|---|
| Offline replay | `python scripts/eval_offline_replay.py --floor 0.85` scores committed `autoresearch/golden_responses/*.json` with `score_extraction` | 28 fixtures; `autoresearch/baseline.json` `overall_score` 0.95546 rounded to **Measured 95.5%** | Measured (CI badge) | Zero |
| This held-out live protocol | Live `extract()` on a predeclared untouched test partition; same `score_extraction` rubric | Partition declared before scoring; not the 28 fixtures; not the 202-case authoring inventory | **Unmeasured** until a funded run is logged | Paid (Anthropic) |
| Optional Promptfoo / Ragas / LLM-judge | Conditional jobs in `.github/workflows/eval-gate.yml` (`live`) | Authoring JSONL / generated Promptfoo cases | Optional CI; skipped when `ANTHROPIC_API_KEY` is absent; not this protocol | Paid when the key is present |

Do not substitute one row for another:

- Offline replay is the public 95.5% claim. Leave that wording unchanged.
- Promptfoo / Ragas / LLM-judge are extra CI jobs, not a held-out live grade.
- This protocol does not replace the badge driver.

## 3. Document sources

Public or synthetic documents only. No client private documents. No production customer PDFs. No real-person identity scans.

Allowed:

- Synthetic invoices, receipts, purchase orders, and similar text authored for this partition (same shape as cases in `evals/golden_set.jsonl`: `input_text` plus expected fields). Prefer invented vendors and amounts.
- Clearly licensed public samples (license name, URL, and permitted use recorded in the partition manifest before scoring). If a public set such as ICDAR SROIE is used, map fields into the `score_extraction` expected schema first. `scripts/benchmark_sroie.py` scores `company` / `date` / `address` / `total` and is **not** this protocol's primary rubric.

Constraints:

- Every test case `id` must be new. Do not reuse IDs from `autoresearch/eval_dataset.json`, `autoresearch/eval_dataset_72.json`, `evals/golden_set.jsonl`, or `evals/adversarial_set.jsonl`.
- Test documents must not be the 28 committed fixture files under `autoresearch/golden_responses/`.
- Do not copy authoring-corpus `input_text` into the held-out test file and relabel it.
- Record PII policy: synthetic names only, or public-sample fields already in the licensed set. Do not add real SSNs, card numbers, or medical identifiers.
- Store source license and origin on each case (manifest `source` / `license` fields).

Suggested layout when a set is authored (not created in this protocol-only change):

```text
evals/held_out_live/partition_manifest.json
evals/held_out_live/train_dev.json
evals/held_out_live/test.json
```

Case schema for `train_dev.json` and `test.json` matches `autoresearch/eval_dataset.json`:

```json
{
  "id": "holdout_invoice_001",
  "doc_type": "invoice",
  "weight": 1.0,
  "critical_fields": ["invoice_number", "total_amount", "vendor_name"],
  "input_text": "...",
  "expected": {}
}
```

## 4. Partitioning

Predeclare train/dev vs **untouched test** before any scoring.

1. Choose case IDs and file paths. Write `evals/held_out_live/partition_manifest.json` with those paths.
2. Hash the files. Commit the manifest (and the locked files) **before** the live run.
3. Score **test only**. Train/dev may be used later for prompt work; they are not the published held-out denominator.
4. After lock, do not open test `expected` fields to tune prompts, few-shot examples, or routers. The scorer reads `expected` at run time; humans and prompt diffs must not.

Peeking is forbidden:

- No test-set error analysis that feeds a prompt edit before the run artifact is frozen.
- No replacing a hard test case after seeing a live miss.
- No scoring train/dev and reporting that number as held-out live.

Record hashes before the run:

```bash
git rev-parse HEAD
sha256sum evals/held_out_live/partition_manifest.json \
          evals/held_out_live/train_dev.json \
          evals/held_out_live/test.json
```

Manifest fields (minimum):

```json
{
  "protocol": "docs/held-out-live-eval-protocol.md",
  "declared_at": "ISO-8601",
  "declared_git_sha": "<full SHA>",
  "train_dev_path": "evals/held_out_live/train_dev.json",
  "test_path": "evals/held_out_live/test.json",
  "train_dev_sha256": "<hex>",
  "test_sha256": "<hex>",
  "test_case_count": "<integer; set only when the partition is declared>",
  "sources": [],
  "status": "PROTOCOL ONLY — PERFORMANCE UNMEASURED"
}
```

Leave `test_case_count` unset (or a placeholder) and `sources` empty until a real partition is declared. Do not invent a count in the manifest.

Verify hashes at run start. Abort if `test.json` does not match `test_sha256`.

## 5. Predeclared rubric

Primary metric: **weighted field-level accuracy** from `score_extraction` in `autoresearch/eval.py`. Critical fields weight `2.0`; other expected fields weight `1.0`. Do not call the result F1.

Normalization and missing-field rules are not restated here. Use [eval-boundary.md](eval-boundary.md) (section "Scoring: `score_extraction`") as the contract:

- Expected keys only; extra extracted keys ignored
- Null expected + null extracted: `1.0`; null expected + non-null: `0.5`; non-null expected + null: `0.0`
- Numerics: 1% relative tolerance (`0` is exact match only)
- Strings: `.strip()` then normalized Levenshtein
- Lists: best-pair alignment over expected items

Case-level overall for a run uses the same weight mean as replay: `sum(case.weight * case.score) / sum(case.weight)`.

Secondary (optional, labeled secondary; not the headline):

- Completeness: `score_completeness` in `autoresearch/eval.py` (ratio of expected non-null fields that are non-null in the extraction)
- Hallucination count and format validity from the same module, if logged

Do not promote completeness (or Promptfoo / Ragas / LLM-judge scores) to the primary held-out number.

## 6. Execution steps when funded

Do not run these steps in this protocol-only change. Credit is not authorized.

### 6.1 Confirm funding and git identity

Follow [metering-runbook.md](metering-runbook.md). The metering smoke historically is:

```bash
.venv/bin/python scripts/benchmark.py --limit 1
```

That command loads `autoresearch/eval_dataset_72.json` and is **not** the held-out test. Use it only as a credit/harness check. A credit-balance error means stop; do not invent numbers.

Record:

```bash
date -u +%Y-%m-%dT%H:%M:%SZ
git rev-parse HEAD
git status --porcelain
```

Prompts and extractor code must match the SHA you log. Model IDs come from `EXTRACTION_MODELS` (see `.env.example`) and from each `extract()` result.

### 6.2 Confirm the partition is locked

```bash
sha256sum evals/held_out_live/test.json
# must equal partition_manifest.json test_sha256
```

### 6.3 Live extract + `score_extraction` (primary)

`python -m autoresearch.eval` calls `app.services.claude_extractor.extract` unless `--golden` or `--dry-run` is set. It scores with `score_extraction`. Point it at the locked test file:

```bash
python -m autoresearch.eval --dataset evals/held_out_live/test.json
```

Do **not** pass `--golden` (that replays fixtures). Do **not** pass `--dry-run` (that uses mocks). Do **not** write held-out predictions into `autoresearch/golden_responses/`; that directory is the 28-fixture CI denominator.

`scripts/benchmark.py` is the cost/latency metering harness for the 72-case file. It also **writes** `autoresearch/golden_responses/<id>.json`. Do not run it unchanged against the 72-case corpus and call the output held-out live. For held-out cost and latency, reuse its measurement method (in-memory `llm_tracer` traces priced by `app.services.cost_tracker.CostTracker`, wall clock per document) on the locked test partition, and write a **separate** artifact.

### 6.4 Artifact (required fields)

Write one JSON file, for example `eval_artifacts/held_out_live/<YYYYMMDD>/run.json` (that directory is gitignored until someone chooses to commit it after publish approval). Required keys:

| Field | Source |
|---|---|
| `date` | UTC timestamp of the run |
| `git_sha` | `git rev-parse HEAD` |
| `model_ids` | `EXTRACTION_MODELS` plus per-case `model` from `extract()` |
| `case_count` | Number of test cases scored |
| `cost` | Sum and per-document USD from priced traces (measured, not `docs/cost-model.md`) |
| `latency` | Per-document wall clock; p50 / p95 if N allows |
| `command` | Exact argv |
| `artifact_path` | Path of this file |
| `partition_manifest_sha256` | Hash of the locked manifest |
| `test_sha256` | Hash of `test.json` at run start |
| `primary_metric` | `"weighted_field_level_accuracy"` via `score_extraction` |
| `primary_score` | Only after the funded run; omit until then |

Also keep stdout/stderr of the command.

### 6.5 Publish gate (human)

After the artifact exists:

1. Update METRICS-SOT and `docs/portfolio-metrics.yaml` with a **new** row (new `id`, not a rewrite of `extraction_accuracy` 95.5%). Set `status: measured` only for the held-out live run.
2. Cayman types **yes** to publish the number.
3. Only then mention the number in README / site copy. Do not change the existing **Measured 95.5%** 28-fixture claim. That claim stays the offline replay result.

Until those three happen, every surface keeps:

```text
STATUS: PROTOCOL ONLY — PERFORMANCE UNMEASURED
```

## 7. Explicit status

```text
STATUS: PROTOCOL ONLY — PERFORMANCE UNMEASURED
```

True until all of the following:

- A funded live run on the locked test partition is logged with the fields in section 6.4
- METRICS-SOT and `docs/portfolio-metrics.yaml` include that run as `status: measured`
- Cayman has typed yes to publish the number

There is no held-out live accuracy figure in this repository today. Do not fill one in.

## 8. Non-goals

- Do not treat another offline replay as held-out live. `python scripts/eval_offline_replay.py --floor 0.85` remains the 28-fixture badge driver.
- Do not treat `python -m autoresearch.eval --golden` as held-out live.
- Do not quote modeled cost or latency from `docs/cost-model.md` as measured held-out live results. Modeled stays modeled until a metered artifact exists (`docs/metering-runbook.md`, `docs/runbooks/measured-cost-latency.md`).
- Do not publish a 202-case live accuracy. The authoring corpus is not this protocol's test partition.
- Do not publish a 72-case `scripts/benchmark.py` sweep as held-out live. That file overlaps the fixture IDs and is a metering corpus, not this partition.
- Do not invent or round a new accuracy percentage in README, `site/`, or this protocol.
- Do not merge this protocol as if the run had already happened.
