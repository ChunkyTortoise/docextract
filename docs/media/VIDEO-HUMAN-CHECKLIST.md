# Demo recording — human checklist

Owner-only steps before publishing a public 90–120 second screen recording. Do not invent or pre-publish a URL.

Referenced from [DEMO.md](../../DEMO.md) and the README reviewer path.

## Before you record

- [ ] Confirm `DEMO_MODE=true streamlit run frontend/app.py` works locally with no API keys.
- [ ] Confirm the [live Streamlit demo](https://docextract-demo.streamlit.app) loads (allow ~30–60s cold start).
- [ ] Skim [DEMO.md](../../DEMO.md) and follow the 90–120s path: Extract → SSE progress → Retrieval / agent trace → Human review → Eval proof.
- [ ] Verify README metrics table still matches `docs/portfolio-metrics.yaml` (especially 95.5% = 28 CI fixtures, corpus 120).
- [ ] If Langfuse traces are part of the narrative, confirm demo deployment has owner-supplied keys — do not show secrets on screen.

## Recording setup

- [ ] Clean browser profile or incognito; no personal bookmarks or unrelated tabs.
- [ ] 1920×1080 or 1280×720; system notifications off.
- [ ] Mic optional; if used, check levels and room noise.
- [ ] Capture only product UI — no `.env`, terminal secrets, or API keys.

## Script beats (≈90–120s)

1. **Hook (10s)** — Ship-gate first: versioned corpus + offline CI replay, then extraction.
2. **Extract (25s)** — Sample invoice or receipt; structured fields and confidence.
3. **Progress (15s)** — SSE stages or demo-mode equivalent.
4. **Agentic RAG (25s)** — Search / agent trace: ReAct reasoning visible.
5. **Eval proof (20s)** — Evaluation view or README metrics; state 95.5% is 28-case offline replay.
6. **Close (10s)** — Link to repo, methodology doc, live demo.

## After recording

- [ ] Watch full take in a clean browser; audio and cursor legible.
- [ ] Upload to a stable public URL (YouTube unlisted, Loom, etc.) — **owner chooses host**.
- [ ] Add the URL to DEMO.md § Recording and README first screen (replace “recording added only after owner records”).
- [ ] Do not claim “live eval grade” for the 95.5% figure; it remains offline CI replay unless a new measured row is added to the ledger.

## Do not

- Invent view counts, hireability outcomes, or cost savings.
- Commit API keys, Langfuse secrets, or `.env` contents.
- Publish a URL before completing this checklist.
