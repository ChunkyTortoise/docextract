# autoresearch/: legacy runner, active replay data

The command-line runner is legacy. Several data files and scoring functions remain dependencies of the current offline replay and regression gate; keep them with the repository.

| Path | Current use |
|---|---|
| `baseline.json` | Historical weighted field-accuracy baseline used by the replay and `scripts/eval_gate.py` |
| `golden_responses/` | 28 frozen prediction fixtures replayed by `scripts/eval_offline_replay.py` |
| `eval_dataset_72.json` | 72 lookup cases used by the replay, including cases without prediction fixtures |
| `eval.py` | Scoring helpers imported by the replay; its standalone runner is legacy |
| `fixtures.py`, `reporter.py` | Support code for the legacy runner |
| `eval_dataset.json` | Historical source for the initial authoring-corpus migration |

Author new cases in `evals/golden_set.jsonl` and `evals/adversarial_set.jsonl`: 150 golden and 50 adversarial cases, plus two metadata rows. This authoring inventory is separate from the frozen replay population. Changes to replay fixtures or the baseline require their own reviewed evidence update.

Use `python scripts/eval_offline_replay.py` for the zero-API-cost check. `make eval` invokes optional live evaluation and requires funded credentials. See [evaluation methodology](../docs/eval-methodology.md).
