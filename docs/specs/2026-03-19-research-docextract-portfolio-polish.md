---
research_for: 2026-03-19-feature-docextract-portfolio-polish-spec
date: 2026-03-19
---

# Research: docextract Portfolio Polish

## Current State Audit

### Repository
- Repo: `ChunkyTortoise/docextract`
- Local: `/Users/cave/Projects/docextract/`
- Stack: FastAPI / ARQ / pgvector / Claude (claude-sonnet-4-6) / Gemini Embeddings / Streamlit / PostgreSQL / Redis
- Three independent Render services (API, Worker, Frontend)

### Test Count
- CLAUDE.md (ground truth): **352 tests**
- README.md "Running Tests" section: **340 tests** (stale)
- CASE_STUDY.md body text and Performance Profile table: **340 tests** (stale)
- CASE_STUDY.md LinkedIn Post section: **340 tests** (stale)
- pyproject.toml `addopts`: `--cov=app --cov-report=term-missing --cov-fail-under=80`

### Discrepancy: 340 vs 352
The actual passing count per `.claude/CLAUDE.md` is **352**. README and CASE_STUDY both say 340 and must be updated.

---

## README Analysis

### Current sections
1. Badges (Tests CI, License, Python, FastAPI) — no coverage badge
2. Architecture diagram (ASCII)
3. Features list
4. Screenshots section — **4 image references exist in markdown**; files are **missing** (screenshots dir is empty)
5. API Reference table
6. Quickstart
7. Environment Variables table
8. Running Tests — says "340 tests, ~2s" (stale)
9. Project Structure
10. Live Demo — URLs present, but dev API key field says "[set in Render dashboard]" (no curl one-liner)
11. Technical Deep Dive (links to CASE_STUDY.md)
12. License

### Image references in README (all broken — files don't exist)
```
docs/screenshots/upload.png
docs/screenshots/review-queue.png
docs/screenshots/results.png
docs/screenshots/dashboard.png
```
The `docs/screenshots/` directory exists but is **empty**.

### Missing elements
- No coverage badge (CI runs `--cov-fail-under=80` but no Codecov/coveralls badge)
- No "Try It Now" curl one-liner section
- No GIF showing SSE streaming flow
- Test count stale (340 → should be 352)

---

## CI/CD Analysis

### File: `.github/workflows/ci.yml`
- Three jobs: `lint`, `test`, `docker-build`
- Lint: ruff + mypy on `app/`, `worker/`, `scripts/`, `frontend/`
- Test: runs `pytest tests/ --cov=. --cov-report=term-missing --cov-fail-under=80 -v --tb=short`
  - Services: postgres (ankane/pgvector:latest) + redis:7-alpine
- Docker-build: builds all 3 Dockerfiles
- Branch triggers: push to `main`/`develop`, PR to `main`

### Coverage badge
- CI does **not** upload to Codecov or Coveralls — no external coverage service configured
- The `Tests` badge already points to `ci.yml` workflow status
- Coverage badge option: add `pytest-cov` + Codecov action to CI, or use a static badge showing ≥80%
- Simplest path: add a static Shields.io coverage badge (`≥80%`) rather than wiring a new service

### Existing badge in README
```
[![Tests](https://github.com/ChunkyTortoise/docextract/actions/workflows/ci.yml/badge.svg)](https://github.com/ChunkyTortoise/docextract/actions)
```
This badge is live and accurate.

---

## Case Study Analysis

### File: `CASE_STUDY.md`
- Exists and is thorough (163 lines)
- Stale metrics:
  - Line 73: "**340 tests passing**"
  - Line 89 (Performance Profile table): `Test suite runtime | 2 seconds (340 tests)`
  - Line 158 (LinkedIn Post): "**340 tests in 2 seconds**"
- All three instances must be updated to **352**
- No other factual inaccuracies found; architecture description and code snippets are accurate

---

## Screenshot Capture Plan

### Target: 4 screenshots

| File | Page | URL | What to show |
|------|------|-----|--------------|
| `upload.png` | Upload page | https://docextract-frontend.onrender.com (page 1) | File upload dropzone, document type selector, submit button |
| `review-queue.png` | Review page | https://docextract-frontend.onrender.com (Review nav item) | Review queue table with claim/approve/correct buttons |
| `results.png` | Results page | https://docextract-frontend.onrender.com (Results nav item) | Extracted fields table from a completed job |
| `dashboard.png` | Dashboard page | https://docextract-frontend.onrender.com (Dashboard nav item) | Metrics cards + charts (jobs processed, accuracy, throughput) |

### Notes on demo mode
- Render API has `DEMO_MODE=true` and `DEMO_API_KEY=demo-key-docextract-2026` set via render.yaml
- Frontend uses `API_URL` env var pointing to the Render API service
- No login required for demo mode; screenshots should be capturable without auth
- Services are on the `standard` plan (API, Worker) and `starter` (Frontend) — may have cold-start delay; wait for 200 before capturing

### Streamlit frontend page files
```
frontend/pages/upload.py      → Upload page
frontend/pages/review.py      → Review queue
frontend/pages/results.py     → Results
frontend/pages/dashboard.py   → Dashboard
frontend/pages/progress.py    → SSE progress (good for GIF)
frontend/pages/records.py     → Records list
```

---

## GIF Recording Plan

### Target: SSE streaming extraction flow

**Flow to record**:
1. Navigate to Upload page on frontend
2. Upload a small PDF (or use a pre-existing demo doc)
3. Click submit — transition to Progress page
4. Watch the SSE progress bar animate through stages: PREPROCESSING → EXTRACTING_TEXT → CLASSIFYING → EXTRACTING_DATA → VALIDATING → EMBEDDING → COMPLETED
5. End on the completed state or auto-redirect to Results

**Duration target**: 10-20 seconds, looping
**Tool**: `mcp__claude-in-chrome__gif_creator`
**Output path**: `docs/screenshots/sse-streaming-demo.gif`

### Fallback if live service is slow/unresponsive
Use `mcp__claude-in-chrome__javascript_tool` to inject mock SSE events into the progress page and record the animation.

---

## Live Service URLs

From `render.yaml` and `.claude/CLAUDE.md`:

| Service | URL | Render Service ID |
|---------|-----|-------------------|
| API | https://docextract-api.onrender.com | srv-d6ijm7buibrs73ad84rg |
| Worker | (internal) | srv-d6ijm7buibrs73ad84s0 |
| Frontend | https://docextract-frontend.onrender.com | srv-d6ivqtq4d50c73aq6cu0 |
| API Docs | https://docextract-api.onrender.com/docs | — |
| Health | https://docextract-api.onrender.com/api/v1/health | — |

### Demo API key
- Default: `demo-key-docextract-2026` (from README env vars table: `DEMO_API_KEY`)
- Must be confirmed against the live service before using in curl one-liner

### Curl one-liner target (for README "Try It Now" section)
```bash
curl https://docextract-api.onrender.com/api/v1/health
```
No auth required for health. A more illustrative one-liner using the demo key:
```bash
curl -H "X-API-Key: demo-key-docextract-2026" \
  https://docextract-api.onrender.com/api/v1/records
```

---

## Notes

- `docs/screenshots/` directory exists but is completely empty — the README already has the correct relative image paths (`docs/screenshots/upload.png` etc.), so files just need to be created at those paths
- The README screenshot table already has the exact filenames needed; no path changes required after files are created
- Coverage badge: CI already enforces 80% floor via `--cov-fail-under=80`; adding a static Shields.io badge is the lowest-friction option without adding Codecov
- Static coverage badge URL: `https://img.shields.io/badge/coverage-%E2%89%A580%25-brightgreen`
- Test count needs updating in 4 places total: README (1 place) + CASE_STUDY.md (3 places)
- No architecture or code changes required for this sprint — purely assets and text updates
