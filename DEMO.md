# DocExtract fixture explorer walkthrough

The offline route inspects stored JSON. It does not upload documents, extract fields, query a database or call a model. The UI's confidence, latency, Eval and Cost values are illustrative fixtures. The separate 28-fixture evaluation is measured offline replay, not live provider performance.

## Start the standalone explorer

From the repository root, use Python 3.10+ and an environment with `requirements_demo.txt` already installed. A fresh setup requires installing these dependencies first:

```bash
python -m venv .venv-demo
.venv-demo/bin/python -m pip install -r requirements_demo.txt
.venv-demo/bin/python -m streamlit run streamlit_demo.py
```

Open the local URL printed by Streamlit. No credentials, `.env`, API, PostgreSQL, Redis or worker are required. On Windows use `.venv-demo\Scripts\python` for the interpreter. This is the same standalone entry point as the README.

## Offline walkthrough

1. **Fields:** select Invoice, Contract and Receipt. Compare stored fields and sample confidence. Expand **Compare a synthetic source sample** for a preview and **Download synthetic comparison HTML** for a standalone accessible copy. Expand the complete fixture JSON for line items and parties.
2. **Search:** read the fixed invoice question and click **Replay stored search**. Two stored results appear. Return to Fields, change sample and return to Search, the recorded invoice output stays visible. **Reset recorded search** clears it. Selecting Contract or Receipt does not change the fixed invoice question.
3. **Trace:** expand the stored reasoning steps and read the stored answer. This is an illustrative trace, not a trace from this session.
4. **Eval:** inspect seeded UI scores and their warning. Follow the separate measured offline replay evidence link for the evaluation population and limitations.
5. **Cost:** inspect the seeded display and warning. These amounts are not metered spend, savings or a completed A/B experiment.

There is no measured time-to-complete claim for this route. Optional [capture provenance](docs/screenshots/PROVENANCE.md) identifies the existing completed-fields screenshot and three-state walkthrough.

## Synthetic comparison provenance

The [invoice](frontend/demo_data/comparison/invoice.html), [contract](frontend/demo_data/comparison/contract.html) and [receipt](frontend/demo_data/comparison/receipt.html) are each a **synthetic comparison sample reconstructed from stored fixture data**. They reproduce all `extracted_data` values from the corresponding `*_sample.json`, including lists. `python scripts/render_comparison_samples.py` regenerates the HTML using the standard library and `frontend/comparison_samples.py`.

Generation date: October 1, 2026. Layout and wording are newly authored. These are not the original processed PDFs, actual transactions or a signed NDA, and are not proof of extraction correctness. Known merchant names are illustrative stored fixture values. No new provider call, confidence calibration or improvement to the separate 95.5% score follows from these documents.

## Configured backend walkthrough

Prerequisites before these actions: install the full Python 3.12+ service dependencies, configure the environment described in [README Install](README.md#install), start API, PostgreSQL, Redis and the ARQ worker, and supply any required model credentials. Provider calls may cost money. This path was not verified by the offline walkthrough.

Run the full frontend with `streamlit run frontend/app.py` with `DEMO_MODE` unset/false. Then upload a document on the upload page, inspect extraction-stage SSE at `/api/v1/jobs/{job_id}/events`, use Agent Trace for `/api/v1/agent-search/stream`, and use Review for low-confidence handoff. Backend failure is not successful fixture extraction. See the existing [product API reference](docs/productization_api.md) for review endpoints and roles. Swagger at `http://localhost:8000/docs` exists only after your API starts.

## Verification

```bash
python scripts/eval_offline_replay.py --floor 0.85
python scripts/audit_portfolio_claims.py
pytest tests/frontend/test_fixture_explorer.py tests/frontend/test_comparison_samples.py --no-cov -q
```

Full test prerequisites differ from the lightweight demo environment. See README Tests for the configured suite. An optional owner recording should follow [the human checklist](docs/media/VIDEO-HUMAN-CHECKLIST.md); no hosted recording or runnable public explorer is asserted here.
