# Metering Runbook — flip modeled → measured

`extraction_f1` (95.5%) is **measured** today: deterministically CI-replayed from
committed fixtures by `scripts/eval_offline_replay.py` at zero API cost.

`avg_cost_per_document`, `p95_latency`, and `straight_through_rate` are **modeled**
(`docs/cost-model.md`). They are modeled only because metering requires live
Anthropic calls and the account currently has no credit balance. The harness is
complete and verified — `scripts/benchmark.py --limit 1` runs end to end and fails
*solely* with HTTP 400 `credit balance is too low` (no code/config blocker).

## When ~$20 of Anthropic credit is available

1. Run the full 72-case live sweep (≈$15–20, one-shot, ~10 min):

   ```
   .venv/bin/python scripts/benchmark.py
   ```

   Writes `autoresearch/benchmark_<YYYYMMDD>.json` (measured F1/p50/p95/cost/
   straight-through) and records the remaining `autoresearch/golden_responses/`
   fixtures so CI replay covers all 72 cases.

2. Propagate the measured numbers to the **three** reviewer-facing surfaces:
   - `README.md` — the "30-second pitch" metric table (cost, p95, straight-through rows): change basis from *Modeled* to *Measured — <date>, N=72, <sha>*.
   - `docs/portfolio-metrics.yaml` — set `basis: measured` and update `source:` for `avg_cost_per_document_usd`, `p95_latency_seconds`, `straight_through_rate_percent`.
   - `~/Desktop/Resumes/cayman-roden-ai-engineer.md` — L17 / L57: drop the "modeled … (metering harness committed, run-once-ready)" qualifier, state the measured values.

3. Consistency check (must pass before sending applications):

   ```
   .venv/bin/python scripts/audit_portfolio_claims.py
   ```

   Every shared number must agree across README ↔ portfolio-metrics.yaml ↔ resume.

One pass, deterministic, ~30 min total. Until then the modeled labels are the
honest framing and must stay on every surface.
