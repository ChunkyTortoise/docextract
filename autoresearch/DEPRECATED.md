# autoresearch/ -- Deprecated

This directory contains the legacy eval runner used before the modern `evals/` pipeline was established.

**Do not add new cases here.** Use `evals/golden_set.jsonl` and `evals/adversarial_set.jsonl` instead.

## What's here

| File | Purpose |
|---|---|
| `baseline.json` | 28-case golden set from the original eval run. Still referenced as a historical baseline in README. |
| `eval_dataset.json` | Source data that was migrated to `evals/golden_set.jsonl` via `scripts/migrate_fixtures_to_jsonl.py`. |
| `eval.py` | Legacy eval runner. Superseded by `scripts/run_eval_ci.py` and `promptfooconfig.yaml`. |
| `reporter.py`, `fixtures.py` | Support modules for the legacy runner. |

## Current eval system

| Component | Location |
|---|---|
| Golden cases | `evals/golden_set.jsonl` (52 cases) |
| Adversarial cases | `evals/adversarial_set.jsonl` (22 cases) |
| Promptfoo CI gate | `promptfooconfig.yaml` + `.github/workflows/eval-gate.yml` |
| Online sampling | `worker/judge_tasks.py` (10% of jobs via ARQ) |
| Full eval command | `make eval` |
| Fast eval command | `make eval-fast` |
