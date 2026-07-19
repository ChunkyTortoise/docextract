# DocExtract Demo Walkthrough

Hiring-manager path: about **90 to 120 seconds**, no API keys required.

## Start here (no credentials)

1. Open the [live demo](https://docextract-demo.streamlit.app) (cold start may take ~30s), **or** run locally:

```bash
DEMO_MODE=true streamlit run frontend/app.py
```

Local `DEMO_MODE` uses cached data under `frontend/demo_data/` and does not call Anthropic, Gemini, PostgreSQL, or Redis.

## 90–120 second path

In `DEMO_MODE`, Evaluation / Cost Dashboard / Quality Monitor are **hidden** (they fall back to synthetic seed without a live API). Stay on the pages below.

1. **Demo sandbox** — start on **Demo**; pick the invoice, contract, or receipt sample; note structured fields and confidence.
2. **SSE progress** — watch stage updates (live demo or `/jobs/{id}/events` when API is up).
3. **Retrieval** — open **Agent Trace** for retrieval and reasoning output.
4. **Human review** — open **Review** for low-confidence handoff.
5. **Eval proof** — skim the README metrics table and [docs/eval-methodology.md](docs/eval-methodology.md) (95.5% = 28-case offline CI replay, not a paid live run). Optional: public red blocked eval-gate PR linked from the README.

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
python scripts/eval_offline_replay.py --floor 0.85
python scripts/audit_portfolio_claims.py
```
