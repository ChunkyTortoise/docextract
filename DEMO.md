# DocExtract Demo Walkthrough

Hiring-manager path: about **90 to 120 seconds**, no API keys required.

## Start here (no credentials)

1. Open the [live demo](https://docextract-demo.streamlit.app) (cold start may take ~30s), **or** run locally:

```bash
DEMO_MODE=true streamlit run frontend/app.py
```

Local `DEMO_MODE` uses cached data under `frontend/demo_data/` and does not call Anthropic, Gemini, PostgreSQL, or Redis.

## 90–120 second path

1. **Extract** — pick the invoice, contract, or receipt sample; note structured fields and confidence.
2. **SSE progress** — watch stage updates (live demo or `/jobs/{id}/events` when API is up).
3. **Retrieval** — open search / agent trace for retrieval and reasoning output.
4. **Human review** — open the review / quality view for low-confidence handoff.
5. **Eval proof** — open the evaluation view, then skim the README metrics table (95.5% = 28-case offline CI replay, not a paid live run).

## Recording (owner)

A public 90–120s screen recording is optional proof. Record only with `docs/media/VIDEO-HUMAN-CHECKLIST.md`, verify in a clean browser, then add the stable URL here and on the README first screen. Do not invent a URL.

## Proof points

| Signal | What to inspect | Source |
|---|---|---|
| Typed extraction | Schemas and confidence | `app/schemas/extraction_models.py` |
| Eval discipline | Golden / adversarial / Promptfoo | `evals/` |
| Offline CI signal | 28-case replay | `scripts/eval_offline_replay.py`, `autoresearch/baseline.json` |
| Demo mode | No-credential cached data | `frontend/demo_mode.py` |

## Verification

```bash
pytest tests/ --collect-only -q -o addopts=
python scripts/run_eval_ci.py --ci
python scripts/audit_portfolio_claims.py
```
