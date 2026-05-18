# Spec: docextract Hero-Repo Deep Polish (2026-05-17)

Status: executed (with one scope adaptation — see "Constraint encountered").

## Context

`docextract` is a portfolio "hero repo" shown to senior/applied-AI-engineer +
LLMOps hiring managers. The operative failure mode is *first-click survival*: a
skeptical reviewer must be impressed in ~5 minutes and not lose confidence in
~30. A 3-agent audit found strong engineering undermined by three issues:

- **Disqualifying:** the `eval-gate` CI badge was red on `main` — its
  Ragas/LLM-judge steps require `ANTHROPIC_API_KEY`, absent on scheduled/push
  runs, so every run failed.
- **Credibility risk:** headline metrics were self-sourced (p95 → a design doc,
  cost → a model, straight-through → circular); README claimed "28 scored
  cases" next to a "72-case corpus" with no reconciliation; the 72-case work
  was untracked (not reproducible from a clean clone).
- **Depth gaps:** no dedicated prompt-injection defense; doc drift; LMS framing
  stale after the Blackboard loop closed.

## What shipped

**Wave 1 — credibility (commit `5c75ccd`)**
- Restructured `.github/workflows/eval-gate.yml` into `precheck → offline → live`:
  the **offline replay job** (`scripts/eval_offline_replay.py`) scores the 28
  committed `golden_responses` fixtures against `baseline.json` with the same
  weighted scorer — deterministic, zero network, **drives the badge**; the
  **live job** is gated on secret presence and *skips cleanly* without a key.
- Committed the 72-case corpus + reproducibility harness (`scripts/benchmark.py`
  — measured F1/latency/cost/straight-through; cwd-independent `.env` bootstrap)
  + `eval_run_72.py` + `build_eval_dataset_72.py` + offline scorer (+ tests).
- Honest metric reconciliation: 95.5% F1 is now CI-replayable at zero cost;
  cost/latency/straight-through explicitly labeled **modeled** with method;
  fixed the incorrect OTel cost-attribution claim; synced doc drift (AGENTS
  test count, DECISIONS ADRs 0013–0019, FastAPI badge, evergreen heading);
  gitignored backups/`uv.lock`.

**Wave 2 — depth (commit `78e8500`)**
- `app/services/injection_guard.py`: instruction-hierarchy system clause,
  untrusted-text fencing with break-out neutralization, high-precision scan,
  unconditional output exfil-key sanitization. Wired into the two-pass
  extractor (extract + correct/reflect call sites). ADR-0020 documents the
  threat model. 5 unit tests; full suite 1261 passed, no regression.
- Removed the EdTech/LMS hiring row (Blackboard loop closed → generic
  senior-AI-eng/LLMOps positioning; also dropped the FERPA over-claim).
- Surfaced the failure-mode taxonomy + named the offline-replay regression
  gate in the README hero (eval rigor visible, not buried).

## Constraint encountered (scope adaptation)

The Anthropic account had **no API credits**, so the live 72-case benchmark
(the measured-numbers pillar) could not run. Per user decision, took the
**28-case offline-replay** path: the badge goes green honestly on the real
28-case replay (F1 0.9555, matches `baseline.json`), the 72-case corpus +
harness ship committed and re-runnable in one command when credits are
attached, and the unmeasured numbers are transparently labeled "modeled"
rather than presented as measured SLAs. This is itself a senior signal:
reproducible zero-cost CI eval + explicit measured-vs-modeled honesty.

## Verification

- `pytest tests/ -m "not e2e"` → 1261 passed, 5 skipped; coverage ~81% (≥80 gate).
- `ruff check app/ worker/ scripts/ frontend/` → clean (CI lint scope).
- `scripts/eval_offline_replay.py` → PASS, F1 0.9555 vs baseline 0.95546, no API key.
- `scripts/audit_portfolio_claims.py` → passed (no metric drift).
- Eval-gate badge: turns green once these commits reach `main` (offline job
  passes with no secret; live job skips).

## Deferred (require API budget; harness committed and ready)

- Metered 72-case benchmark numbers (`scripts/benchmark.py`).
- LLM-judge calibration vs human labels; Pass-2 business-impact + single/
  two-pass/reflection tradeoff table; README demo GIF + OTel trace screenshot.
- GH Action major-version bumps (deferred deliberately: warnings-only until
  2026-06-02; blind version guesses would risk turning green CI red).
