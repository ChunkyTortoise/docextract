# Retrieval and Extraction Evidence

This note keeps extraction replay evidence separate from retrieval evidence. It follows the boundaries documented in [Eval Boundary](eval-boundary.md) and [Eval Gate Proof](eval-gate-proof.md).

## Extraction replay

The offline extraction replay was run from detached commit `7b1a515303cff036a8a16670aad39dc10b5b7b7a` with this exact command:

```sh
cd /Users/cave/Projects/clients/.worktrees/docextract-hf-ra11 || exit 1
env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 /Users/cave/Projects/clients/docextract/.venv/bin/python -S scripts/eval_offline_replay.py --floor 0.85 --out /tmp/hero-hf-ra11-offline-replay.json
```

The command exited with status 0. It replayed 28 of 72 lookup cases and reported:

| Result | Value |
|---|---:|
| Combined weighted field-level extraction score | 0.9555 |
| Golden fixture score | 0.9264 |
| Adversarial fixture score | 1.0 |
| Baseline score | 0.95546 |
| Floor | 0.85 |
| Pending fixtures | 44 |

The JSON output artifact is `/tmp/hero-hf-ra11-offline-replay.json`, SHA-256 `16c267869038d8aaa90febb474d34ab5a78d0eca94fe7514103e523dfa8f39ed`, 958 bytes. The committed comparison artifact is [autoresearch/baseline.json](../autoresearch/baseline.json), with `case_count` 28 and `overall_score` 0.95546.

The extraction score is weighted field-level accuracy over committed prediction fixtures. Legacy output field names contain `f1`, but this result is not F1. It is also not a live model result.

## Three separate denominators

These populations have different roles and must not be summed or substituted for one another.

| Population | Count | Role |
|---|---:|---|
| Committed prediction fixtures | 28 | Predictions scored by the offline extraction replay, matching `baseline.json` case count 28 |
| Lookup cases in [autoresearch/eval_dataset_72.json](../autoresearch/eval_dataset_72.json) | 72 | Expected outputs and lookup records, split into 51 golden and 21 adversarial cases; 44 currently have no committed prediction fixture |
| Authoring lines in the JSONL corpus | 202 | 151 lines in [evals/golden_set.jsonl](../evals/golden_set.jsonl) and 51 lines in [evals/adversarial_set.jsonl](../evals/adversarial_set.jsonl) |

Each JSONL authoring file opens with one `_meta` row at version `2.0.0`. Removing those two metadata rows leaves 150 golden cases and 50 adversarial cases, or 200 non-metadata authoring cases. The 202 authoring lines are not the extraction replay denominator.

## Retrieval measures are separate

Retrieval recall is the fraction of required ground-truth information present in the retrieved contexts for a retrieval query. Its population must be a specified set of queries with ground truth and captured retrieved contexts. Retrieval recall is unmeasured in the committed tree because there is no committed enabled judge run containing query-level ground truth, retrieved contexts, scores, and an aggregate over a declared population.

Support, called faithfulness in the evaluator, is the fraction of answer claims supported by retrieved contexts. Its population must be answers paired with the contexts used to produce them. Support is unmeasured in the committed tree because there is no committed enabled judge run containing claim decisions, source contexts, scores, and an aggregate over a declared answer population.

Abstention is whether the system declines to answer when the available evidence is insufficient. Its population must include labeled answerable and unanswerable queries, recorded system decisions, and an explicit abstention metric such as recall on unanswerable queries plus false-abstention rate on answerable queries. Abstention is unmeasured in the committed tree because no such labeled retrieval population and result artifact are committed.

The 0.9555 extraction replay score establishes none of retrieval recall, support, or abstention. It compares committed parsed extraction fields with expected document fields. It does not execute retrieval, inspect retrieved contexts, score answer claims, or test abstention decisions.

## Optional LLM judge implementation

[app/services/ragas_evaluator.py](../app/services/ragas_evaluator.py) defines `context_recall`, `faithfulness`, and `answer_relevancy` as Claude LLM-as-judge measures. Their configured weights are 0.35, 0.40, and 0.25. Evaluation is gated by `RAGAS_ENABLED`, which defaults off. When the flag is off, the evaluator returns `None` for all three measures and for the overall score. Therefore, the implementation does not provide a measured retrieval score in the committed tree.

## Demo fixture provenance trap

[frontend/demo_data/eval_sample.json](../frontend/demo_data/eval_sample.json) contains `context_recall` 0.91, `faithfulness` 0.93, `answer_relevancy` 0.88, `overall` 0.91, and `fixtures_evaluated` 16. Its `run_id` is `demo-eval-run-001` and its timestamp is `2024-11-20T09:00:00Z`.

Those values are demo fixture data, not a measurement. They do not establish retrieval recall, support, abstention, or a production evaluation result.

## CI and merge enforcement

[The Eval Gate workflow](../.github/workflows/eval-gate.yml) can execute the offline replay and report a passing or failing job. CI execution is distinct from enforced merge protection. The repository branch-protection query returned `Branch not protected`, and the branch-rules query returned an empty list. A passing job must not be described as an enforced merge gate under that repository state.

This note does not claim that README wording is correct. Correcting README gate and corpus wording is the later mandatory RA13 task and is outside this change.
