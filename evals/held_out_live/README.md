# Held-out live partition (stubs only)

```text
STATUS: BENCHMARK PLAN / HARNESS ONLY — PERFORMANCE UNMEASURED
```

This directory is the **locked held-out partition** for:

- [docs/held-out-live-eval-protocol.md](../../docs/held-out-live-eval-protocol.md) (RA7; two-pass live quality)
- [docs/held-out-baseline-benchmark.md](../../docs/held-out-baseline-benchmark.md) (CONT-RA10; two-pass vs Pass 1 only)

Committed files here are **stubs**. They are not a scored dataset and must not be cited as results.

| File | Role |
|---|---|
| `test.json` | Untouched test cases (JSON array). Currently `[]`. |
| `train_dev.json` | Train/dev only. Currently `[]`. Never report this as held-out. |
| `partition_manifest.json` | Predeclare paths and sha256 **before** scoring. Hashes are unset until a real partition is locked. |

## How to add synthetic cases

1. Author **new IDs** (do not reuse `invoice_01`, JSONL authoring IDs, or `autoresearch/eval_dataset*.json` IDs).
2. Use public or synthetic text only. Invented vendors and amounts. No client private docs, no real-person identity scans, no real SSNs / card numbers / medical identifiers.
3. Match the `autoresearch/eval_dataset.json` case shape: `id`, `doc_type`, `weight`, `critical_fields`, `input_text`, `expected`. Add `source` / `license` on each case.
4. Put tuning material in `train_dev.json`. Put the published denominator in `test.json` only.
5. Hash and write `train_dev_sha256` / `test_sha256` / `test_case_count` / `sources` into `partition_manifest.json`, then commit the lock **before** any live scoring.
6. Do **not** commit model outputs or scored run JSON here. Measured A/B artifacts belong under `docs/artifacts/held-out-baseline/` after a funded run (still UNMEASURED until Cayman typed yes).

Repeating `python scripts/eval_offline_replay.py --floor 0.85` does not fill this partition.
