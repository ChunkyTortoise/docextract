# Fixture explorer captures

Captured 2026-09-26 from the working patch on base commit `c4562bb10980b7c9abf289c9020de6633ece079c`, branch `visual/verified-showcase-20260926`.

- `demo-hero.png`: actual Chrome screenshot, 900 x 1000 viewport.
- `demo-mobile.png`: actual Chrome screenshot, 375 x 900 viewport.
- Entrypoint: `python -m streamlit run streamlit_demo.py`.
- Environment: isolated Python 3.12 environment installed from `requirements_demo.txt`; Streamlit 1.64.0.
- Selected fixture: `frontend/demo_data/invoice_sample.json`.
- Mode: stored JSON explorer. No upload, live extraction, search database, billing request or provider call.
- No compositing, cropping, generated pixels or editorial overlays. The browser viewport ends before some lower content.
- Sample confidence values are stored metadata, not calibrated accuracy or the separate 28-fixture evaluation result. Fields without confidence show `Not supplied`.

Reproduce the UI using README reviewer path 2. Run the separate offline evaluation with `python scripts/eval_offline_replay.py --floor 0.85`.

The previous image showed controls before results. These replacements show actual stored output and matching alt text. The source PDF is not displayed; do not describe this as a side-by-side source-document verification or a fresh extraction.

## Optional walkthrough

`fixture-walkthrough.gif` is a 9-second loop of three actual browser captures at 900 x 1000: Invoice fields, Contract fields, and Search replay after clicking its button. Each state lasts 3 seconds. It is a step-by-step screenshot sequence, not continuous video. The system ffmpeg converted these captures using a shared GIF palette. No generated UI or altered results. Final Search capture preserves literal currency values after fixing Markdown math interpretation. The README links to motion rather than autoplaying it.
