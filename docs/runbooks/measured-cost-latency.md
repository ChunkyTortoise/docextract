# Measured cost / latency (Phase B)

Ledger rows `avg_cost_per_document_usd` and `p95_latency_seconds` stay **modeled** until a funded benchmark completes.

## Run (requires Anthropic credits)

```bash
set -a && source .env && set +a
python scripts/benchmark.py   # or make target if present
# Then flip status to measured in docs/portfolio-metrics.yaml per docs/metering-runbook.md
```

## Current blocker (2026-07-18)

Live Anthropic calls return credit-balance errors. Do not invent measured numbers. Keep README pointing at [docs/cost-model.md](../cost-model.md).
