---
spec: 2026-03-19-feature-docextract-portfolio-polish
status: ready
complexity: standard
effort_estimate: 6-8 hours
repo: docextract
github: ChunkyTortoise/docextract
stack: FastAPI/ARQ/pgvector/Claude/Streamlit
live_url: https://docextract-api.onrender.com | https://docextract-frontend.onrender.com
---

# Spec: docextract — Portfolio Polish Sprint

## Context

DocExtract AI is a production document intelligence API: FastAPI + ARQ async queue + pgvector semantic search + two-pass Claude extraction + Streamlit dashboard, deployed across three Render services.

**Current state**:
- 352 tests passing (per `.claude/CLAUDE.md`)
- All three Render services live (`standard` plan API + Worker, `starter` Frontend)
- Demo mode enabled on API (`DEMO_MODE=true`, `DEMO_API_KEY=demo-key-docextract-2026`)
- `docs/screenshots/` directory exists and is **empty** — README already references the 4 expected files at the correct paths, but they don't exist yet, causing broken images on GitHub
- README says "340 tests" (stale); CASE_STUDY.md says "340 tests" in 3 places (stale)
- No GIF in README
- No "Try It Now" curl section in README
- No coverage badge (CI enforces 80% floor but no badge displayed)

**Why this sprint matters**: Broken images are the first thing a recruiter or client sees. Stale metrics undercount the actual work. Adding a curl one-liner lets someone verify the live service is real in under 10 seconds. Together, these changes maximize portfolio signal-to-noise.

---

## Goals

- Replace 4 broken image references in README with real screenshots captured from the live Streamlit frontend
- Add a GIF showing the SSE streaming extraction flow in the README
- Fix the stale test count (340 → 352) in both README and CASE_STUDY.md (4 total occurrences)
- Add a coverage badge reflecting the CI-enforced 80% floor
- Add a "Try It Now" section to the README with a working curl one-liner against the live API
- Rewrite README using "Product-Story" format (Why hook with impact metric, Mermaid diagram, Try It Now, Certifications Applied)
- Add Mermaid architecture diagram (FastAPI → ARQ → pgvector → Claude → SSE flow)
- Add "Certifications Applied" section in Domain Pillars format, each cert mapped to a specific feature
- Add interactive Swagger link to README hero (`https://docextract-api.onrender.com/docs`)
- Add "Deploy Your Own" Render Blueprint button with env var checklist
- Add dynamic shields.io badges (tests, coverage ≥80%, live API status)
- Add performance metrics table (extraction time, SSE latency, semantic search p95)
- Verify all changes render correctly on GitHub

---

## Requirements

**REQ-F01**: The system shall have 4 screenshots in `docs/screenshots/` (`upload.png`, `review-queue.png`, `results.png`, `dashboard.png`) referenced in README — each captured from the live Streamlit frontend at `https://docextract-frontend.onrender.com`.

**REQ-F02**: The README shall include a GIF (`docs/screenshots/sse-streaming-demo.gif`) showing the SSE streaming extraction flow — from file upload through the PREPROCESSING → EXTRACTING_TEXT → CLASSIFYING → EXTRACTING_DATA → VALIDATING → EMBEDDING → COMPLETED pipeline stages.

**REQ-F03**: The README shall display the accurate test count (352) and a coverage badge. The "Running Tests" section shall read "352 tests". The badge shall reflect the CI-enforced ≥80% coverage floor.

**REQ-F04**: The case study (`CASE_STUDY.md`) shall reflect the current test count (352) in all 3 stale locations: the "Results" section body text, the Performance Profile table row, and the LinkedIn Post section.

**REQ-F05**: The README shall include a "Try It Now" section placed after the "Live Demo" section, containing a `curl` one-liner against the live API that returns HTTP 200 without any setup.

**REQ-NF01**: All README images (`upload.png`, `review-queue.png`, `results.png`, `dashboard.png`, `sse-streaming-demo.gif`) shall load without broken links when viewed on `https://github.com/ChunkyTortoise/docextract`.

**REQ-F06**: The README shall include a "Certifications Applied" section using the Domain Pillars format (GenAI & LLM Engineering, RAG & Knowledge Systems, Cloud & MLOps, Deep Learning & AI Foundations), with each cert mapped to a specific project feature in this repo.

**REQ-F07**: The README hero shall include an interactive Swagger link (`https://docextract-api.onrender.com/docs`) displayed as a badge or prominent inline link alongside the live demo URLs.

**REQ-F08**: The README shall include a Mermaid architecture diagram illustrating the FastAPI → ARQ worker → pgvector → Claude two-pass extraction → SSE streaming flow.

**REQ-F09**: The README shall include a "Deploy Your Own" section with a Render Blueprint one-click deploy button (render.com deploy badge) and a minimal checklist of required env vars (ANTHROPIC_API_KEY, DATABASE_URL, REDIS_URL, SECRET_KEY).

**REQ-F10**: The README shall be restructured using the "Product-Story" format: (1) "Why" hook with an impact metric — not a tech description, (2) "Messy Middle" — 2-3 key technical trade-offs with alternatives considered, (3) Try It Now section, (4) Mermaid architecture diagram, (5) Certifications Applied in Domain Pillars format.

---

## Architecture

No code changes. This sprint is entirely asset capture and text updates.

**Screenshot files**: browser automation navigates to each Streamlit page on the live frontend → captures screenshot → saves to `docs/screenshots/{name}.png`. The README already has the correct `![alt](docs/screenshots/{name}.png)` syntax; files just need to exist at those paths.

**GIF**: browser automation records the progress page as user uploads a doc → progress bar advances through all SSE stages → gif saved to `docs/screenshots/sse-streaming-demo.gif` → a new markdown line added to README below the screenshots table.

**README updates**: `Edit` tool on `README.md` — update test count string, add coverage badge to badge row, add "Try It Now" section.

**Case study updates**: `Edit` tool on `CASE_STUDY.md` — update 3 occurrences of "340 tests".

**Verification**: Check file existence, validate curl returns 200, confirm no broken images via GitHub raw URL pattern.

---

## Waves

### Wave 1: Screenshots + GIF Capture

**Dependencies**: Live Render services responsive (verify with health check first)
**Tools**: `mcp__claude-in-chrome__navigate`, `mcp__claude-in-chrome__computer` (for screenshot), `mcp__claude-in-chrome__gif_creator`, `mcp__claude-in-chrome__find`, `mcp__claude-in-chrome__switch_browser`

**Steps**:

1. Verify live services are up:
   ```bash
   curl -s https://docextract-api.onrender.com/api/v1/health
   ```
   Expected: HTTP 200 with JSON body. If 502 or timeout, wait 30s for Render cold start and retry. The `standard` plan does not sleep, but initial startup after inactivity may take up to 60s.

2. Open the Streamlit frontend:
   - Use `mcp__claude-in-chrome__navigate` to `https://docextract-frontend.onrender.com`
   - Wait for Streamlit to finish loading (wait for the sidebar nav to appear)
   - Use `mcp__claude-in-chrome__find` to confirm the page has loaded (look for "DocExtract" heading or sidebar)

3. Capture `upload.png`:
   - Navigate to the Upload page (should be the default/first page, or click "Upload" in the sidebar)
   - Wait for the file upload dropzone and document type selector to render
   - Use `mcp__claude-in-chrome__computer` to take a screenshot
   - Save the screenshot to `/Users/cave/Projects/docextract/docs/screenshots/upload.png`

4. Capture `review-queue.png`:
   - Click "Review" in the Streamlit sidebar
   - Wait for the review queue table to render (may show empty state if no pending items — that is acceptable)
   - Screenshot → save to `/Users/cave/Projects/docextract/docs/screenshots/review-queue.png`

5. Capture `results.png`:
   - Click "Results" in the Streamlit sidebar
   - Wait for the results table or "no results yet" state to render
   - Screenshot → save to `/Users/cave/Projects/docextract/docs/screenshots/results.png`

6. Capture `dashboard.png`:
   - Click "Dashboard" in the Streamlit sidebar
   - Wait for metric cards and charts to render (may show zeros in demo mode — acceptable)
   - Screenshot → save to `/Users/cave/Projects/docextract/docs/screenshots/dashboard.png`

7. Record SSE streaming GIF:
   - Navigate to the Upload page
   - Use `mcp__claude-in-chrome__gif_creator` to begin recording
   - Upload a small test document (or use the API to pre-stage a job, then navigate to the Progress page to watch SSE events animate)
   - Alternative approach if upload is unavailable: navigate directly to `frontend/pages/progress.py` equivalent — the Progress page with a job ID parameter if supported
   - Capture 10-20 seconds of the progress bar moving through stages
   - Stop recording; save GIF to `/Users/cave/Projects/docextract/docs/screenshots/sse-streaming-demo.gif`
   - If `gif_creator` is unavailable: use `mcp__claude-in-chrome__computer` to capture sequential screenshots of the progress bar advancing, then use Bash + `convert` (ImageMagick) to assemble them:
     ```bash
     convert -delay 50 -loop 0 /tmp/frame*.png \
       /Users/cave/Projects/docextract/docs/screenshots/sse-streaming-demo.gif
     ```

8. Confirm all 5 asset files exist:
   ```bash
   ls -lh /Users/cave/Projects/docextract/docs/screenshots/
   ```
   Expected: `upload.png`, `review-queue.png`, `results.png`, `dashboard.png`, `sse-streaming-demo.gif` — all non-zero size.

---

### Wave 2: README + Case Study Updates

**Dependencies**: Wave 1 complete (all 5 asset files exist at correct paths)
**Tools**: `Edit` (file edits only — no code changes)

**Steps**:

1. Update README test count in "Running Tests" section.

   Find (exact string in README line 151):
   ```
   pytest tests/ -v  # 340 tests, ~2s
   ```
   Replace with:
   ```
   pytest tests/ -v  # 352 tests, ~2s
   ```

2. Add coverage badge to the README badge row.

   Find (exact string, lines 3-6 of README):
   ```
   [![Tests](https://github.com/ChunkyTortoise/docextract/actions/workflows/ci.yml/badge.svg)](https://github.com/ChunkyTortoise/docextract/actions)
   [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
   [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)]()
   [![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688)]()
   ```
   Replace with (adds coverage badge as the second badge):
   ```
   [![Tests](https://github.com/ChunkyTortoise/docextract/actions/workflows/ci.yml/badge.svg)](https://github.com/ChunkyTortoise/docextract/actions)
   [![Coverage](https://img.shields.io/badge/coverage-%E2%89%A580%25-brightgreen)]()
   [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
   [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)]()
   [![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688)]()
   ```

3. Add GIF embed below the Screenshots section in README.

   Find (after the screenshots table, before the `## API Reference` heading):
   ```
   | Extraction Results | Analytics Dashboard |
   |-------------------|---------------------|
   | ![Results](docs/screenshots/results.png) | ![Dashboard](docs/screenshots/dashboard.png) |

   ## API Reference
   ```
   Replace with:
   ```
   | Extraction Results | Analytics Dashboard |
   |-------------------|---------------------|
   | ![Results](docs/screenshots/results.png) | ![Dashboard](docs/screenshots/dashboard.png) |

   ### SSE Streaming Demo

   ![SSE streaming extraction flow](docs/screenshots/sse-streaming-demo.gif)

   *Real-time progress: PREPROCESSING → EXTRACTING_TEXT → CLASSIFYING → EXTRACTING_DATA → VALIDATING → EMBEDDING → COMPLETED*

   ## API Reference
   ```

4. Add "Try It Now" section to the README after the "Live Demo" section.

   Find (the Live Demo section, lines 172-177):
   ```
   ## Live Demo

   - **API**: https://docextract-api.onrender.com
   - **Frontend**: https://docextract-frontend.onrender.com
   - **Dev API key**: [set in Render dashboard]
   - **Docs**: https://docextract-api.onrender.com/docs

   ## Technical Deep Dive
   ```
   Replace with:
   ```
   ## Live Demo

   - **API**: https://docextract-api.onrender.com
   - **Frontend**: https://docextract-frontend.onrender.com
   - **Docs**: https://docextract-api.onrender.com/docs

   ## Try It Now

   No setup required. Hit the live API directly:

   ```bash
   # Health check (no auth)
   curl https://docextract-api.onrender.com/api/v1/health

   # List extracted records (demo key)
   curl -H "X-API-Key: demo-key-docextract-2026" \
     https://docextract-api.onrender.com/api/v1/records
   ```

   The demo API key (`demo-key-docextract-2026`) has read-only access. Upload endpoints require a full key.

   ## Technical Deep Dive
   ```
   Note: the inner code block fence (` ``` `) must use actual backticks in the file — ensure the Edit does not double-escape them.

5. Update CASE_STUDY.md — 3 occurrences of "340 tests":

   a. Body text (line 73):
      Find: `**340 tests passing**`
      Replace: `**352 tests passing**`

   b. Performance Profile table (line 89):
      Find: `| Test suite runtime | 2 seconds (340 tests) |`
      Replace: `| Test suite runtime | 2 seconds (352 tests) |`

   c. LinkedIn Post section (line 158):
      Find: `- **340 tests in 2 seconds**:`
      Replace: `- **352 tests in 2 seconds**:`

6. Confirm no other stale "340" references remain:
   ```bash
   grep -rn "340" /Users/cave/Projects/docextract/README.md \
     /Users/cave/Projects/docextract/CASE_STUDY.md
   ```
   Expected: no matches.

7. Restructure README using "Product-Story" format (REQ-F10):

   Read the current README.md. Rewrite the opening section using this structure (preserving all existing technical content, just reordering and replacing the intro):
   ```markdown
   # DocExtract AI

   **Extract structured data from unstructured documents in seconds — not hours.**

   [![Tests](...)](...)  [![Coverage: ≥80%](...)]()  [![Live API](...)]()  [![License: MIT](...)]()

   [SSE streaming GIF — docs/screenshots/sse-streaming-demo.gif]

   ## The Problem
   Manual document processing is slow, error-prone, and impossible to scale. DocExtract AI
   automates extraction of structured fields from PDFs and documents using a two-pass LLM
   pipeline with real-time SSE streaming feedback.

   ## Try It Now
   [... curl one-liner section ...]

   ## Architecture
   [... Mermaid diagram — see step 8 ...]

   ## Technical Trade-offs
   - **Two-pass vs single-pass Claude**: accuracy at the cost of latency — first pass classifies doc type, second pass extracts fields with schema awareness
   - **pgvector vs Pinecone**: self-hosted on Render, zero per-query cost, no vendor lock-in
   - **ARQ vs Celery**: asyncio-native worker, lower memory footprint, native Redis streams

   ## Certifications Applied
   [... Domain Pillars format — see step 9 ...]
   ```

8. Add Mermaid architecture diagram (REQ-F08):

   In the `## Architecture` section of README.md, add:
   ````markdown
   ```mermaid
   graph LR
       A[Browser / API Client] -->|POST /documents| B[FastAPI]
       B -->|enqueue job| C[ARQ Worker]
       C -->|extract text| D[Claude Pass 1\nclassify doc type]
       D -->|extract fields| E[Claude Pass 2\nschema-aware]
       E -->|embed 768-dim| F[pgvector HNSW]
       B -->|SSE stream stages| A
       F -->|semantic search| B
   ```
   ````

9. Add "Certifications Applied" section in Domain Pillars format (REQ-F06):

   Add before the `## License` section in README.md:
   ```markdown
   ## Certifications Applied

   ### GenAI & LLM Engineering
   - **IBM Generative AI Engineering** — two-pass Claude extraction pipeline, tool_use correction pattern
   - **Vanderbilt ChatGPT Automation** — document automation, structured data extraction at scale

   ### RAG & Knowledge Systems
   - **IBM RAG and Agentic AI** — pgvector HNSW semantic search, ARQ async agent pipeline

   ### Cloud & MLOps
   - **Duke LLMOps** — CI/CD (GitHub Actions), coverage gates, Render deploy pipeline
   - **Google Cloud GenAI Leader** — cloud deployment, managed PostgreSQL + Redis on Render

   ### Deep Learning & AI Foundations
   - **DeepLearning.AI Deep Learning** — 768-dim Gemini embedding model, HNSW index design
   - **IBM AI and ML Engineering** — MLOps patterns, confidence thresholding, two-pass correction
   ```

10. Add interactive Swagger link to README hero (REQ-F07):

    In the "Live Demo" section, ensure this line is present and prominent:
    ```markdown
    - **Interactive API Docs**: [https://docextract-api.onrender.com/docs](https://docextract-api.onrender.com/docs)
    ```
    Also add as a badge in the hero:
    ```markdown
    [![Swagger](https://img.shields.io/badge/API-Swagger-85EA2D?logo=swagger)](https://docextract-api.onrender.com/docs)
    ```

11. Add "Deploy Your Own" section with Render Blueprint button (REQ-F09):

    Add before the `## Running Tests` section:
    ```markdown
    ## Deploy Your Own

    [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/ChunkyTortoise/docextract)

    Required env vars (set in Render dashboard after deploy):
    - `ANTHROPIC_API_KEY` — Claude API key
    - `DATABASE_URL` — auto-set by Render managed PostgreSQL
    - `REDIS_URL` — auto-set by Render managed Redis
    - `SECRET_KEY` — generate: `python -c "import secrets; print(secrets.token_hex(32))"`
    - `DEMO_MODE=true` — enable demo API key (optional, for portfolio use)
    - `DEMO_API_KEY=demo-key-docextract-2026` — demo key value (optional)
    ```

12. Add performance metrics table (R5 from refinements):

    Add in the `## Architecture` section (after the Mermaid diagram):
    ```markdown
    ## Performance

    | Metric | Value |
    |--------|-------|
    | Document extraction (p50) | ~8s (two-pass Claude) |
    | SSE first token (p50) | <500ms |
    | Semantic search (p95) | <100ms |
    | Test suite runtime | ~2s (352 tests) |
    | API cold start (Render standard) | <5s |
    ```

13. Update badges to dynamic shields.io variants (R8 from refinements):

    Replace the static badge row with:
    ```markdown
    [![Tests](https://github.com/ChunkyTortoise/docextract/actions/workflows/ci.yml/badge.svg)](https://github.com/ChunkyTortoise/docextract/actions)
    [![Coverage](https://img.shields.io/badge/coverage-%E2%89%A580%25-brightgreen)]()
    [![Live](https://img.shields.io/website?url=https%3A%2F%2Fdocextract-api.onrender.com%2Fapi%2Fv1%2Fhealth&label=API&color=success)](https://docextract-api.onrender.com/docs)
    [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
    [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)]()
    [![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688)]()
    ```

---

### Wave 3: Verification

**Dependencies**: Wave 2 complete
**Tools**: Bash, `mcp__claude-in-chrome__navigate` (for GitHub preview check)

**Steps**:

1. Confirm all 5 asset files exist and are non-empty:
   ```bash
   ls -lh /Users/cave/Projects/docextract/docs/screenshots/
   ```
   Expected: `upload.png` (>10KB), `review-queue.png` (>10KB), `results.png` (>10KB), `dashboard.png` (>10KB), `sse-streaming-demo.gif` (>50KB).

2. Verify curl returns 200 from live API:
   ```bash
   curl -o /dev/null -s -w "%{http_code}" \
     https://docextract-api.onrender.com/api/v1/health
   ```
   Expected: `200`.

3. Verify demo API key returns a valid response:
   ```bash
   curl -o /dev/null -s -w "%{http_code}" \
     -H "X-API-Key: demo-key-docextract-2026" \
     https://docextract-api.onrender.com/api/v1/records
   ```
   Expected: `200`.

4. Verify test suite still passes (no regressions from any accidental file changes):
   ```bash
   cd /Users/cave/Projects/docextract && pytest tests/ --tb=short -q 2>&1 | tail -5
   ```
   Expected: `352 passed` (or higher if new tests were added).

5. Verify no stale "340" strings remain in README or CASE_STUDY.md:
   ```bash
   grep -c "340" /Users/cave/Projects/docextract/README.md \
     /Users/cave/Projects/docextract/CASE_STUDY.md
   ```
   Expected: all counts `0`.

6. Verify image paths in README match actual files:
   ```bash
   grep -o "docs/screenshots/[^ )]*" \
     /Users/cave/Projects/docextract/README.md | while read f; do
     [ -f "/Users/cave/Projects/docextract/$f" ] \
       && echo "OK: $f" || echo "MISSING: $f"
   done
   ```
   Expected: all lines print `OK`.

7. Push to GitHub and verify in browser:
   - Navigate to `https://github.com/ChunkyTortoise/docextract`
   - Confirm screenshots table renders 4 images (not broken link icons)
   - Confirm GIF plays inline
   - Confirm coverage badge appears next to Tests badge
   - Confirm "Try It Now" section is visible with formatted code blocks

---

## Verification Criteria

- [ ] `docs/screenshots/upload.png` exists, >10KB, not a broken link on GitHub
- [ ] `docs/screenshots/review-queue.png` exists, >10KB, not a broken link on GitHub
- [ ] `docs/screenshots/results.png` exists, >10KB, not a broken link on GitHub
- [ ] `docs/screenshots/dashboard.png` exists, >10KB, not a broken link on GitHub
- [ ] `docs/screenshots/sse-streaming-demo.gif` exists, plays inline on GitHub README
- [ ] README badge row includes coverage badge
- [ ] README "Running Tests" says "352 tests"
- [ ] README has "Try It Now" section with working curl examples
- [ ] `curl https://docextract-api.onrender.com/api/v1/health` returns HTTP 200
- [ ] `curl -H "X-API-Key: demo-key-docextract-2026" https://docextract-api.onrender.com/api/v1/records` returns HTTP 200
- [ ] CASE_STUDY.md body text says "352 tests passing"
- [ ] CASE_STUDY.md Performance Profile table says "352 tests"
- [ ] CASE_STUDY.md LinkedIn Post says "352 tests in 2 seconds"
- [ ] `grep "340" README.md CASE_STUDY.md` returns no matches
- [ ] `pytest tests/` passes with 352+ tests (no regressions)
- [ ] README "Product-Story" format: opens with "Why" hook and impact metric (not a tech description)
- [ ] README includes Mermaid architecture diagram (renders on GitHub)
- [ ] README includes "Certifications Applied" section in Domain Pillars format (4 pillars)
- [ ] README hero includes Swagger badge/link pointing to `https://docextract-api.onrender.com/docs`
- [ ] README includes "Deploy Your Own" section with Render deploy button
- [ ] README includes performance metrics table (p50/p95 latency values)
- [ ] README badge row includes live API status badge (shields.io website check)

---

## Certification Coverage

| Certification | Issuer | Alignment | Evidence in This Project |
|---------------|--------|-----------|--------------------------|
| Generative AI Engineering | IBM | Strong | Two-pass Claude LLM extraction pipeline, tool_use correction pattern |
| RAG and Agentic AI | IBM | Strong | pgvector HNSW semantic search, ARQ async agent pipeline |
| LLMOps | Duke | Strong | CI/CD (GitHub Actions), test coverage gates, Render deploy pipeline |
| Deep Learning Specialization | DeepLearning.AI | Moderate | Embedding models (768-dim Gemini), HNSW index design |
| ChatGPT Automation | Vanderbilt | Moderate | Document automation, structured data extraction at scale |
| Cloud GenAI Leader | Google | Moderate | Cloud deployment (Render), managed database + Redis services |
| Python for Everybody | U. Michigan | Moderate | Python backend, async I/O, asyncpg, ARQ worker |
| AI and ML Engineering | Microsoft | Moderate | MLOps patterns, confidence thresholding, two-pass correction |
| Google Data Analytics | Google | Moderate | Extraction analytics, ROI tracking, audit trail |
| Google Business Intelligence | Google | Moderate | Streamlit dashboard, stats endpoint, executive report generation |

---

## Blockers

None. All three Render services are live on the `standard` plan and do not sleep. Demo mode is enabled. No credentials are needed for health checks.

**Pre-flight check** (run at session start): `curl https://docextract-api.onrender.com/api/v1/health`
If this returns 200, Wave 1 can proceed immediately.
