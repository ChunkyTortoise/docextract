# Held-out vs simpler-baseline artifacts

```text
STATUS: BENCHMARK PLAN / HARNESS ONLY — PERFORMANCE UNMEASURED
```

No measured A/B run has been logged.

When a funded live comparison is executed (`python scripts/held_out_baseline_benchmark.py --live --confirm-credit-spend` on a locked `evals/held_out_live/test.json`), write:

```text
docs/artifacts/held-out-baseline/<YYYYMMDD>/run.json
```

Do not commit fake scores. Do not copy `autoresearch/baseline.json` (28-fixture replay, Measured 95.5%) into this directory and call it the held-out A/B result.

See [docs/held-out-baseline-benchmark.md](../../held-out-baseline-benchmark.md). Publish numbers only after Cayman types yes.
