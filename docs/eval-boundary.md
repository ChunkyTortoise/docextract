# Eval Boundary: 28-Fixture Replay vs 202-Case Authoring Corpus

This note states what the published **Measured 95.5%** result is, how it is scored, and what it does not prove. It does not introduce a new accuracy number.

Related: [eval-methodology.md](eval-methodology.md) (always-on vs paid live paths), [eval-guide.md](eval-guide.md) (harness runbook).

## The two denominators

| Asset | Size | Role | Scored by the CI badge? |
|---|---:|---|---|
| Authoring corpus | 202 lines | Hand-authored inputs and expected outputs | No |
| Offline replay fixtures | 28 JSON files | Committed predictions scored in CI | Yes |
| Accepted baseline | 95.5% | Weighted field-level accuracy on those 28 | Yes (compared, not recomputed as a live grade) |

Public README and `docs/portfolio-metrics.yaml` count **202** as the line counts of:

- `evals/golden_set.jsonl` (151 lines)
- `evals/adversarial_set.jsonl` (51 lines)

Each JSONL file starts with a `_meta` object (`version: 2.0.0`). The 202 figure is authoring coverage, not the measured denominator.

The 28-fixture score lives in `autoresearch/baseline.json`:

```json
"overall_score": 0.95546,
"case_count": 28
```

Public docs round that to **95.5%**. Call it **weighted field-level accuracy**. Do not call it F1. Script variable names still say `extraction_f1_*` for legacy reasons.

Reproduce:

```bash
python scripts/eval_offline_replay.py --floor 0.85
```

## How the three eval files relate

```text
evals/golden_set.jsonl          151 lines  (authoring; golden)
evals/adversarial_set.jsonl      51 lines  (authoring; adversarial)
        \______________________________/
                      |
              202-line authoring corpus
              (labels, Promptfoo/Ragas inputs)
                      |
                      |  IDs overlap, separate files
                      v
autoresearch/eval_dataset_72.json   72 cases (51 golden + 21 adversarial)
        expected fields + case weights + critical_fields
                      |
                      |  script iterates this file
                      v
autoresearch/golden_responses/<id>.json   28 committed fixtures
        parsed_extraction used as the prediction
                      |
                      v
score_extraction(parsed, expected, critical_fields)
                      |
                      v
autoresearch/baseline.json   overall_score 0.95546, case_count 28
```

`scripts/eval_offline_replay.py` does **not** read the JSONL authoring files. It loads `autoresearch/eval_dataset_72.json`, looks up `autoresearch/golden_responses/<id>.json`, and scores `parsed_extraction` against `case["expected"]`.

Cases in the 72-file with no fixture are listed as **pending** and skipped. They are not scored as failures. `--min-cases` defaults to 28 so the committed fixture set cannot shrink silently.

`autoresearch/eval_dataset.json` is the original 28-case dataset. Its case IDs match the 28 fixture filenames exactly. `scripts/run_eval_ci.py` still loads that 28-case file. All 28 fixture IDs also appear in the JSONL authoring corpus (16 golden, 12 adversarial).

## Pipeline relation

Production extraction is a two-pass Claude pipeline (ADR-0003): Pass 1 extracts; Pass 2 runs only when confidence is below a per-type threshold.

CI offline replay does **not** run that pipeline. It does **not** call a live model. It scores committed fixture JSON against expected fields.

Optional paid paths (Promptfoo, Ragas, LLM-as-judge) run only when `ANTHROPIC_API_KEY` is present. They are skipped otherwise and are not the Eval Gate badge driver. See `.github/workflows/eval-gate.yml` (`offline` vs `live` jobs).

Intentional red demo of the gate: [PR #32](https://github.com/ChunkyTortoise/docextract/pull/32) (keep open; Offline replay fails on purpose).

## Scoring: `score_extraction`

Implementation: `autoresearch/eval.py`. The docstring there already names the metric **weighted field-level accuracy**.

The function iterates **expected keys only**. Extra keys in the extracted dict are ignored.

### Field weights

- Critical field (`key in critical_fields`): weight `2.0`
- Any other expected field: weight `1.0`

`critical_fields` come from the case record in `eval_dataset_72.json` (and the matching 28-case file).

### Scalars

`_score_scalar(extracted, expected)`:

| Expected | Extracted | Score |
|---|---|---|
| `None` | `None` | `1.0` |
| `None` | non-null | `0.5` (partial credit) |
| non-null | `None` | `0.0` |
| number | number within 1% relative | `1.0` else `0.0` |
| number `0` | `0` | `1.0`; any other value `0.0` |
| string | string | normalized Levenshtein after `.strip()` |

Numeric rule (expected != 0): `abs(extracted - expected) / abs(expected) <= 0.01`. String values that parse as float are accepted for numeric expected fields.

String similarity:

```text
sim = 1 - levenshtein(a, b) / max(len(a), len(b))
```

Empty vs empty is `1.0`.

### Lists

`_score_list` uses best-pair alignment: each expected item is scored against the extracted item with the highest `_score_list_item` score. The list score is the mean of those best-pair scores.

- Empty expected list: `1.0`
- Missing or non-list extracted when expected is non-empty: `0.0`
- Extra extracted items are not penalized (only expected items are iterated)
- The same extracted item can be the best match for more than one expected item (no exclusive 1-1 assignment)

Inside a list item, expected fields whose value is `None` are skipped, not given the top-level 0.5/1.0 null rule.

### Per-case formula

```text
case_score = sum(w_k * s_k) / sum(w_k)

where for each key k in expected:
  w_k = 2.0 if k is critical else 1.0
  s_k = list or scalar field score in [0.0, 1.0]
```

If `sum(w_k) == 0`, the function returns `0.0`.

### Overall formula (replay)

After each replayed case is scored, `eval_offline_replay.py` applies **case weights** from the dataset (`case["weight"]`):

```text
overall = sum(case.weight * case.score) / sum(case.weight)
```

The 28 fixture cases currently use weights `1.0` (15 cases), `0.8` (6), and `0.5` (7). The 72-case file also contains `2.0` weights on some pending (unfixtured) cases; those do not enter the published 28-case score.

The script rounds the combined overall to 4 decimal places, then:

1. Fails if replayed count `< --min-cases` (default 28)
2. Fails if overall `< --floor` (CI uses `0.85`)
3. Fails if overall `< baseline.overall_score - --tolerance` (default tolerance `0.03`)

`scripts/run_eval_ci.py` uses a separate regression tolerance of `0.02` against the same `baseline.json`.

### Worked example (illustration only)

Not a measured result. One case, expected:

```text
invoice_number = "INV-001"   (critical, weight 2.0)
vendor_name    = "Acme"      (critical, weight 2.0)
notes          = "Net 30"    (not critical, weight 1.0)
```

Extracted: `invoice_number` matches, `vendor_name` is missing (`None`), `notes` matches.

```text
s_invoice = 1.0
s_vendor  = 0.0    # expected non-null, extracted None
s_notes   = 1.0

case_score = (2.0*1.0 + 2.0*0.0 + 1.0*1.0) / (2.0 + 2.0 + 1.0)
           = 3.0 / 5.0
           = 0.60
```

Null illustration on a single non-critical field: expected `None` and extracted `None` scores `1.0`; expected `None` and extracted `"Acme"` scores `0.5`.

## Prediction provenance

**Known (CI behavior):** the offline job does not call a model. It reads committed JSON.

**Known (file shape):** every file in `autoresearch/golden_responses/` currently has:

- `case_id`
- `model` (all 28 files store `claude-sonnet-4-6`)
- `recorded_at`
- `raw_response`
- `parsed_extraction` (this is what the scorer reads)

The replay script docstring calls these **recorded extractor outputs**. `scripts/benchmark.py` writes this same JSON shape from a live `extract()` call (side effect: `autoresearch/golden_responses/<id>.json`).

**Open / unknown:** whether each of the 28 files was originally produced by a live extractor run, then committed, versus written or edited by hand. Evidence that keeps this open:

- `docs/eval-guide.md` documents creating a fixture file by hand with this same shape, including a sample `recorded_at` of `2026-03-24T00:00:00Z`.
- Twelve adversarial fixtures store midnight UTC timestamps (`2026-03-24T00:00:00Z` or `2026-03-25T00:00:00Z`). Sixteen others store 1-minute increments on `2026-01-15`. Those stamps are consistent with recording, hand authoring, or later edits. They do not prove a live two-pass run on the current prompts.

How to verify a given fixture:

1. Open `autoresearch/golden_responses/<id>.json` and inspect `model`, `recorded_at`, `raw_response`, `parsed_extraction`.
2. `git log -- autoresearch/golden_responses/<id>.json`
3. Compare the writer in `scripts/benchmark.py` (live `extract()`, `datetime.now(UTC).isoformat()`) with the committed stamp format.

Do not describe CI replay as a live two-pass Claude grade.

## What this does NOT prove

- **A 202-case score.** The authoring corpus is not the replay denominator. There is no published 202-case accuracy figure here.
- **Live model grade.** CI replay does not call Anthropic (or any other provider). A change to prompts or the extractor can still pass offline replay until fixtures are re-recorded.
- **Held-out freshness.** The 28 predictions are committed files. They are not a fresh sample drawn at eval time.
- **The 44 pending cases in `eval_dataset_72.json`.** No fixture means not scored, not failed.
- **Generalization** to new vendors, layouts, languages, or document types outside these 28.
- **Cost or latency.** Those remain modeled until a metered `scripts/benchmark.py` artifact is committed (`docs/cost-model.md`).
- **F1 / precision / recall.** The scorer is weighted field-level accuracy, even when code says `extraction_f1_*`.

## Claim checklist

When citing eval results:

1. Name the command: `python scripts/eval_offline_replay.py --floor 0.85`
2. Name the artifact: `autoresearch/baseline.json` (`overall_score` 0.95546, `case_count` 28)
3. Name the metric: weighted field-level accuracy (critical fields 2x)
4. Name the denominator: 28 committed fixtures
5. Keep the 202-line corpus labeled as authoring coverage, not the measured population
