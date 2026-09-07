# Eval Methodology

DocExtract separates a deterministic, merge-safe offline replay from optional paid live evaluation.

## Evidence map

| Asset | Current size | Purpose |
|---|---:|---|
| Golden authoring corpus | 151 cases | Hand-authored extraction inputs and expected outputs |
| Adversarial authoring corpus | 51 cases | Failure-mode and prompt-injection coverage |
| Offline replay fixtures | 28 cases | Deterministic zero-cost CI signal |
| Accepted replay baseline | 95.5% | Weighted field-level accuracy over the 28 replay fixtures |

The 202-case authoring corpus is separate from the 28-fixture replay. The published 95.5% result uses only the replay fixtures as its denominator and must not be described as F1 or as a 202-case live-model result.

Scoring formulas, missing-field rules, fixture provenance, and the 28-vs-202 denominator boundary: [eval-boundary.md](eval-boundary.md).

## Always-on gate

The `offline` job in `.github/workflows/eval-gate.yml` runs:

```bash
python scripts/eval_offline_replay.py --floor 0.85
```

It loads recorded responses from `autoresearch/golden_responses/`, scores them against expected outputs, and compares the result with `autoresearch/baseline.json`. It requires no model API key and is the merge-safe signal behind the Eval Gate badge.

```text
eval-gated change -> 28 committed fixtures -> offline replay -> baseline comparison -> pass or block
```

The committed baseline records weighted field-level accuracy. Critical fields receive twice the weight of noncritical fields. A replay below the configured floor or outside the accepted regression tolerance fails the job.

## Optional live evaluation

Promptfoo, Ragas, and LLM-as-judge paths provide deeper model-dependent checks when credentials and budget are available. They are conditional jobs, not unconditional required checks. When `ANTHROPIC_API_KEY` is absent, the workflow skips them.

- Promptfoo checks structured output and prompt-injection assertions.
- Ragas measures retrieval-oriented qualities such as faithfulness and answer relevancy.
- LLM-as-judge applies a structured rubric across repeated samples.
- Gemini can act as an independent judge to reduce same-provider self-grading.

Live results should be published only with a dated artifact, provider and model identifiers, case count, run count, cost, and latency. Modeled cost or latency belongs in `docs/cost-model.md`, not in the README as measured performance.

## Observability boundary

Langfuse, LangSmith, and OpenTelemetry integrations exist in the codebase but require explicit configuration. They are useful for trace inspection and prompt-version workflows when enabled. An unverified hosted dashboard or live trace is not public evidence.

## Updating the baseline

Baseline changes are reviewed code changes. Use the repository commands to generate a candidate artifact, inspect case-level differences, and commit the updated artifact only when the change is intentional. Do not use `--update-baseline` merely to silence a regression.

Before publishing a new metric:

1. Record the exact command and immutable artifact.
2. State whether the run is deterministic replay or a paid live run.
3. State the denominator and weighting method.
4. Repeat stochastic runs when variance matters.
5. Update `docs/portfolio-metrics.yaml` with a measured status and date.

## Reproduce the public result

```bash
python scripts/eval_offline_replay.py --floor 0.85
```

Expected public interpretation: 95.5% weighted field-level accuracy on 28 committed deterministic replay fixtures, at zero API cost. The 202-case corpus describes authored evaluation coverage, not the measured denominator.
