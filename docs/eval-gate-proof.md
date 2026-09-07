# Eval Gate Proof

This note records that the always-on eval gate detects what it claims, using the public intentional-red PR rather than a new red branch. It is CONT-RA6 evidence, not a new accuracy claim.

Public 95.5% wording stays in the README: measured weighted field-level accuracy on the 28-fixture offline replay.

## Public red PR

- PR: https://github.com/ChunkyTortoise/docextract/pull/32
- Branch: `demo/eval-gate-regression`
- Head: `21d4e802f721b1974e1d3b9c3d8ca6a0c77f25d3`
- Keep open; do not merge.

Related:
- Always-on job definition: `.github/workflows/eval-gate.yml` (`offline`)
- Replay command: `python scripts/eval_offline_replay.py --floor 0.85`
- Committed baseline: `autoresearch/baseline.json` (`overall_score` 0.95546, `case_count` 28)
- Methodology: [eval-methodology.md](eval-methodology.md)
- Replay vs 202-case authoring corpus: `docs/eval-boundary.md` (draft [PR #44](https://github.com/ChunkyTortoise/docextract/pull/44); not merged here)

## What #32 changed

Two commits on that head:

1. `91ff4c35b51bc05111cd4b3e717800f4317458cd` rewrote `prompts/extraction/v1.1.0.txt`: precision and `null` language became inference / guessing language.
2. `21d4e802f721b1974e1d3b9c3d8ca6a0c77f25d3` corrupted eight `autoresearch/golden_responses/*.json` fixtures. Vendor or merchant strings became `WRONG_VENDOR_EVAL_GATE_DEMO`. Totals (and some subtotals) became `0.01`. Each file set `_demo_regression: true`.

Corrupted fixtures: `invoice_01`, `invoice_02`, `invoice_discount`, `invoice_foreign_currency`, `invoice_ocr`, `purchase_order_01`, `receipt_01`, `receipt_sparse`.

`scripts/eval_offline_replay.py` scores `parsed_extraction` in those JSON files against `autoresearch/eval_dataset_72.json`. It does not call a model and does not read the extraction prompt.

## Honesty: fixtures vs prompt

Offline replay scores **committed fixtures**, not a live model run.

On #32 the badge-driving job failed because those fixtures were intentionally wrong, not because the prompt text alone changed predicted outputs. The prompt-only parent (`91ff4c3`) still passes the same replay command: fixtures were intact, so the combined score still matched the committed baseline floor check.

Prompt degradation matters for **live / paid** stages (Promptfoo, Ragas, LLM-judge, multi-provider panel) when API keys are present. Those jobs were **skipped** on the recorded #32 run (no key). This note does not claim a live-model failure for the prompt edit.

## Proof 1: Wrong extraction is scored incorrectly

Intent: a bad extraction must receive a low field-level score.

On #32, vendor / merchant and total fields in eight recorded fixtures were replaced with values that do not match the expected fields in `eval_dataset_72.json`. `score_extraction` then lowered those case scores. The combined replay result dropped below `--floor 0.85`.

That is fixture corruption, which is the correct way to trip a **replay** gate. A prompt-only edit cannot change this job's inputs.

CI log (Offline replay job on head `21d4e802`): `FAIL: combined F1 0.8432 < floor 0.85`. That line is a public check-run quote, not a new README metric.

Job: https://github.com/ChunkyTortoise/docextract/actions/runs/29670515963/job/88148512559

Pytest on the same head also executed and failed two fixture-backed tests that require the replay to pass (`test_offline_replay_passes_deterministically`, `test_field_f1_scorer_matches_offline_gate`). That is the `test` job, not the Eval Gate badge driver.

## Proof 2: The relevant regression fails the intended check

The always-on merge signal is **Offline replay (deterministic, no key)** in `eval-gate.yml`. On #32 that job ran and concluded **FAILURE**.

Eval-gate run: https://github.com/ChunkyTortoise/docextract/actions/runs/29670515963

Companion CI run on the same head (lint / security / docker-build success; `test` failure): https://github.com/ChunkyTortoise/docextract/actions/runs/29670515973

Live eval and Multi-provider judge were skipped (no key). They are not the always-on gate.

## Proof 3: The corrected version passes

Intact fixtures on `main` pass the same command:

```bash
python scripts/eval_offline_replay.py --floor 0.85
```

That compares the 28 committed fixtures to `autoresearch/baseline.json` (0.95546 / 28) with `--floor 0.85`. Exit 0 is the green path. Restoring the eight corrupted files on #32 would return the replay to this path; `main` already has the intact files.

Green Eval Gate badge: https://github.com/ChunkyTortoise/docextract/actions/workflows/eval-gate.yml

Example green `main` push after PR #43 (`796c9043fb5554186d5a5b82d3534c11d349da06`, 2026-09-07):

- Eval-gate: https://github.com/ChunkyTortoise/docextract/actions/runs/34085439404 (Offline replay success; Live eval skipped; Multi-provider skipped)
- CI: https://github.com/ChunkyTortoise/docextract/actions/runs/34085439409 (lint, security, test, docker-build, Eval golden, publish: success)

## Proof 4: Replayed vs executed vs skipped

**Replayed** means the job scored committed recorded JSON. No model API call.

**Executed** means CI ran the job.

**Skipped** means the workflow did not run the job (missing key, or a needed job failed).

| Stage | Method | #32 head `21d4e802` | Typical `main` push (`796c904`, 2026-09-07) |
|---|---|---|---|
| Precheck (key availability) | Executed (inspects whether secrets are set) | Executed, success | Executed, success |
| Offline replay (deterministic, no key) | **Replayed** fixtures; badge driver | **Executed, FAILURE** | **Executed, success** |
| Live eval (Promptfoo + Ragas + LLM-judge) | Would **execute** live model calls | **Skipped** (no `ANTHROPIC_API_KEY`) | **Skipped** (no `ANTHROPIC_API_KEY`) |
| Multi-provider judge panel | Would **execute** live model calls | **Skipped** (no Anthropic + OpenAI keys) | **Skipped** (no Anthropic + OpenAI keys) |
| lint | Executed | Executed, success | Executed, success |
| security | Executed | Executed, success | Executed, success |
| docker-build | Executed | Executed, success | Executed, success |
| test | Executed pytest | Executed, FAILURE | Executed, success |
| Eval (golden, no API calls) | **Replayed** fixtures via `scripts/run_eval_ci.py --ci` | **Skipped** (`needs: test`) | Executed, success |
| publish | Executed | Skipped (`needs: test`) | Executed, success |

On both the recorded #32 run and a normal `main` push, paid live stages were skipped. The always-on difference is Offline replay: fail on corrupted fixtures, pass on intact fixtures.

## Reproduce

Green (`main`, intact fixtures):

```bash
python scripts/eval_offline_replay.py --floor 0.85
```

Expect exit 0 and a PASS line vs `autoresearch/baseline.json`.

Red (existing #32; do not merge):

```bash
git fetch origin pull/32/head
git switch --detach 21d4e802f721b1974e1d3b9c3d8ca6a0c77f25d3
python scripts/eval_offline_replay.py --floor 0.85
```

Expect non-zero exit and a FAIL line against `--floor 0.85`.

Prompt-only parent (same replay, intact fixtures):

```bash
git fetch origin pull/32/head
git switch --detach 91ff4c35b51bc05111cd4b3e717800f4317458cd
python scripts/eval_offline_replay.py --floor 0.85
```

Expect exit 0. This is the fixture-vs-prompt split: the offline gate does not see the prompt file.

## What this does not prove

- A live extractor run against the degraded prompt. Those jobs were skipped.
- A new field-level accuracy number. Public 95.5% remains the 28-fixture baseline on `main`.
- Held-out freshness of the 28 recorded fixtures. See `docs/eval-boundary.md` after PR #44 for that boundary.
