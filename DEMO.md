# DocExtract Demo Walkthrough

This walkthrough gives a hiring reviewer a five-minute path through the live or local demo without requiring API keys.

## Live Demo

[Open the Streamlit demo](https://docextract-demo.streamlit.app)

First visit may take about 30 seconds to wake the hosted app.

## Local Demo

```bash
DEMO_MODE=true streamlit run frontend/app.py
```

This mode uses cached demo data from `frontend/demo_data/` and does not call Anthropic, Gemini, PostgreSQL, or Redis.

## Five-Minute Path

1. Open the app and start on the upload or demo sandbox flow.
2. Choose the invoice, contract, or receipt sample.
3. Inspect the extracted fields and confidence values.
4. Open the search or agent trace view to see retrieval and reasoning output.
5. Open the review or quality view to see how low-confidence results become human-review work.
6. Open the evaluation view to connect the product behavior to the eval gate.

## Proof Points

| Signal | What to inspect | Source |
|---|---|---|
| Typed extraction | Structured document schemas and confidence values | `app/schemas/extraction_models.py` |
| Eval discipline | Golden, adversarial, and Promptfoo cases | `evals/` |
| Failure analysis | Known failure modes and next experiments | `docs/eval-failure-analysis.md` |
| Cost control | Per-model cost attribution | `app/services/cost_tracker.py` |
| Reliability | Circuit breaker model fallback | `app/services/circuit_breaker.py` |
| Demo mode | No-credential cached app data | `frontend/demo_mode.py` |

## Verification

```bash
pytest tests/unit/test_demo_mode.py -q
python scripts/audit_portfolio_claims.py
```
