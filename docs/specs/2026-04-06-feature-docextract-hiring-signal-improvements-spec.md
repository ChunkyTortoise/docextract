---
title: "Spec: DocExtract Hiring Signal Improvements"
type: feature
status: draft
version: 1
date: 2026-04-06
complexity: deep
target_repo: docextract
---

# Spec: DocExtract Hiring Signal Improvements

## 1. Problem Statement & Context

DocExtract is the primary AI Engineer portfolio piece but has 5 critical gaps that prevent phone screens: no `instructor` typed extraction (in every 2026 senior AI engineer JD), no E2E tests with real PDFs (senior engineer red flag), `llm_judge.py` not wired to production sampling (incomplete eval lifecycle), no quality trend dashboard (nothing demoable in 30 minutes), and no explicit business metrics framing. All fixes are surgical — no architectural changes.

### Codebase Context
- **Repository**: `~/Projects/docextract/`
- **Key files**:
  - `app/services/claude_extractor.py` — two-pass extractor; `instructor` migration point
  - `app/services/llm_judge.py` — exists (163 lines) but NOT wired to worker pipeline
  - `app/services/bm25.py` + `app/services/agentic_rag.py` — BM25 exists; RRF missing
  - `app/api/metrics.py` — LLM cost metrics; needs quality trend endpoint
  - `app/api/roi.py` — ROI calc exists; needs business metrics surface
  - `worker/tasks.py` — 12-step pipeline; add judge sampling task
  - `frontend/pages/` — 14 pages; add Quality Monitor
  - `render.yaml` — already has `docextract-frontend` Render service (cold-start fixed)
  - `alembic/versions/` — migrations 001–011 applied; need 012 for `eval_log`
  - `tests/` — no `e2e/` directory; 1,155 tests all mocked

---

## 2. Requirements (EARS Notation)

### Functional Requirements

- **REQ-F01**: When a document extraction call is made via `claude_extractor.py`, the system shall use `instructor.from_anthropic()` with `response_model` and `max_retries=3`, replacing manual JSON parsing.
- **REQ-F02**: When an extraction job completes and `job_id % 10 == 0`, the system shall enqueue an ARQ task that calls `llm_judge.py` and stores the 4-dimension score in the `eval_log` table.
- **REQ-F03**: When `GET /api/v1/metrics/quality-trend` is called, the system shall return a 30-day rolling EWMA of composite judge scores, per-dimension breakdowns, and HITL escalation rate.
- **REQ-F04**: The system shall provide a Streamlit page at `frontend/pages/15_Quality_Monitor.py` displaying quality score trends, per-dimension breakdowns, and cost-per-document over time.
- **REQ-F05**: When `GET /api/v1/metrics/business` is called, the system shall return straight-through rate, average cost per doc (USD), p50/p95 latency, and docs processed in last 30 days.
- **REQ-F06**: The system shall provide a `tests/e2e/` directory with at least 2 E2E tests using committed real-world PDFs, marked `@pytest.mark.e2e`, skipped unless `ANTHROPIC_API_KEY` is set.
- **REQ-F07**: When a search query is issued via `agentic_rag.py`, the system shall fuse BM25 and vector rankings with Reciprocal Rank Fusion (RRF, k=60) before reranking top-10 with Claude Haiku.
- **REQ-F08**: When `extraction_mode="vision"` or `extraction_mode="auto"` with OCR confidence < 0.6, the system shall base64-encode pages and send to Claude vision API instead of the text path.
- **REQ-F09**: The `README.md` hero section shall lead with business metrics: cost/doc, straight-through rate, p95 latency, test count, and accuracy.

### Non-Functional Requirements

- **REQ-NF01**: All existing 1,155 tests shall continue to pass. Coverage gate stays ≥ 80%.
- **REQ-NF02**: Golden eval baseline shall not regress below 94.6% F1.
- **REQ-NF03**: `instructor` retry behavior shall not increase p95 extraction latency by more than 10% under normal conditions (no schema errors).
- **REQ-NF04**: The `eval_log` ARQ sampling task shall add ≤ 500ms overhead to extraction jobs (sampled 10% only).

### Out of Scope

- TruLens integration (build equivalent natively with RAGAS + PostgreSQL)
- LangGraph refactor (ARQ already handles this; write ADR instead)
- PSI drift detection (no production traffic to detect yet)
- Full vision auto-classifier (user-controlled mode only)
- DeepEval CI integration
- Active learning loop wiring

---

## 3. Acceptance Criteria

### AC-01: instructor typed extraction with retry
- **Given** the `claude_extractor.py` calls the Anthropic API
- **When** the API returns malformed JSON or schema-invalid response
- **Then** `instructor` retries up to 3 times and returns a valid Pydantic model; raises `InstructorRetryError` after 3 failures
- **Verification**: `pytest tests/unit/test_claude_extractor.py -v -k "instructor"`

### AC-02: LLM-as-judge online sampling
- **Given** extraction jobs complete in the worker pipeline
- **When** `job_id % 10 == 0` (10% sampling)
- **Then** an ARQ task is enqueued, calls `llm_judge.py`, and writes scores to `eval_log` table
- **Verification**: `pytest tests/unit/test_llm_judge_sampling.py -v`

### AC-03: Quality trend endpoint
- **Given** `eval_log` table has records
- **When** `GET /api/v1/metrics/quality-trend?days=30` is called with valid API key
- **Then** response includes `ewma_composite`, `per_dimension`, `escalation_rate`, `days` fields
- **Verification**: `pytest tests/integration/test_quality_metrics.py -v`

### AC-04: Business metrics endpoint
- **Given** jobs and records exist in the database
- **When** `GET /api/v1/metrics/business` is called
- **Then** response includes `straight_through_rate`, `avg_cost_usd`, `p50_ms`, `p95_ms`, `docs_30d`
- **Verification**: `pytest tests/integration/test_business_metrics.py -v`

### AC-05: Quality Monitor Streamlit page
- **Given** the frontend is running
- **When** user navigates to Quality Monitor page
- **Then** page loads without error and displays quality score chart (mocked data in demo mode)
- **Verification**: `cd /Users/cave/Projects/docextract && python -c "import ast; ast.parse(open('frontend/pages/15_Quality_Monitor.py').read()); print('syntax ok')"`

### AC-06: E2E tests with real PDFs
- **Given** `tests/e2e/fixtures/` contains at least 2 real PDF files
- **When** `pytest tests/e2e/ -v -m e2e` is run with `ANTHROPIC_API_KEY` set
- **Then** tests pass end-to-end (upload → extract → verify fields within tolerance)
- **Verification**: `pytest tests/e2e/ -v -m e2e --co` (collection check, no API call)

### AC-07: RRF hybrid retrieval
- **Given** the agentic RAG `search_documents` tool is called
- **When** a query is issued
- **Then** both BM25 and vector rankings are computed and fused via RRF before returning results
- **Verification**: `pytest tests/unit/test_hybrid_retriever.py -v`

### AC-08: Vision extraction mode
- **Given** `extraction_mode="vision"` is passed to the extractor
- **When** a document is processed
- **Then** pages are base64-encoded and sent to Claude vision API instead of text path
- **Verification**: `pytest tests/unit/test_vision_extractor.py -v`

### AC-09: README business metrics hero
- **Given** the README.md
- **When** a hiring manager reads the first 10 lines
- **Then** they see: cost/doc, straight-through rate, p95 latency, test count, F1 accuracy as concrete numbers
- **Verification**: Manual review of README.md opening section

---

## 4. Architecture Decisions

### ADR-S01: `instructor` over manual JSON retry
- **Decision**: Replace manual JSON try/except loops with `instructor.from_anthropic()` + `response_model`
- **Alternatives**: Manual retry loop (already present) — rejected: brittle, not ecosystem standard
- **Consequences**: Adds `instructor` dep; all extraction paths return typed Pydantic models; existing mocks need `instructor` patch
- **Confidence**: HIGH

### ADR-S02: Native eval_log over TruLens
- **Decision**: Store judge scores in a new `eval_log` PostgreSQL table via ARQ sampling task, not TruLens
- **Alternatives**: TruLens — rejected: post-Snowflake maintenance risk, no real production traffic to monitor yet
- **Consequences**: No new external dependency; ADR documents the trade-off explicitly
- **Confidence**: HIGH

### ADR-S03: Claude Haiku reranker over sentence-transformers
- **Decision**: Use Claude Haiku to rerank top-10 RRF results
- **Alternatives**: `sentence-transformers` cross-encoder — rejected: ~2GB model, heavy dep, same narrative
- **Consequences**: ~$0.0002/query overhead; no local model download
- **Confidence**: HIGH

### ADR-S04: User-controlled vision mode over auto-classifier
- **Decision**: `extraction_mode` parameter (`text`|`vision`|`auto`) with simple threshold for `auto`
- **Alternatives**: ML quality classifier — rejected: no calibration data available
- **Consequences**: Explicit, demonstrable, defensible; `auto` uses OCR confidence < 0.6 heuristic
- **Confidence**: HIGH

---

## 5. Interface Contracts

### New: `eval_log` table (migration 012)
```python
class EvalLog(Base):
    __tablename__ = "eval_log"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    job_id: Mapped[str] = mapped_column(String, ForeignKey("extraction_jobs.id"), nullable=False)
    completeness: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-5
    field_accuracy: Mapped[int] = mapped_column(Integer, nullable=False)
    hallucination_absence: Mapped[int] = mapped_column(Integer, nullable=False)
    format_compliance: Mapped[int] = mapped_column(Integer, nullable=False)
    composite: Mapped[float] = mapped_column(Float, nullable=False)  # mean of 4 dims, /5
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

### New: `GET /api/v1/metrics/quality-trend`
```python
class QualityTrendResponse(BaseModel):
    days: int
    ewma_composite: list[dict]  # [{date, score}]
    per_dimension: dict[str, list[dict]]  # {dim_name: [{date, score}]}
    escalation_rate: float
    sample_count: int
```

### New: `GET /api/v1/metrics/business`
```python
class BusinessMetricsResponse(BaseModel):
    straight_through_rate: float   # jobs with confidence > threshold / total
    avg_cost_usd: float            # from llm_trace cost_usd
    p50_ms: float
    p95_ms: float
    docs_30d: int
    hitl_escalation_rate: float
```

### Modified: `claude_extractor.py` — instructor migration
```python
import instructor
from anthropic import AsyncAnthropic
client = instructor.from_anthropic(AsyncAnthropic())
# All extraction calls use response_model=<PydanticSchema>, max_retries=3
```

### New: `app/services/hybrid_retriever.py`
```python
def rrf_fuse(bm25_ranking: list[str], vector_ranking: list[str], k: int = 60) -> list[str]:
    """Reciprocal Rank Fusion of two ranked lists."""

async def rerank_with_claude(query: str, candidates: list[dict], top_k: int = 5) -> list[dict]:
    """Rerank top-10 candidates using Claude Haiku structured output."""
```

### New: `app/services/vision_extractor.py`
```python
async def extract_with_vision(
    pages: list[bytes],  # raw page bytes (PDF page renders)
    doc_type: str,
    extraction_mode: Literal["vision", "auto"] = "vision",
) -> ExtractionResult:
    """Base64-encode pages and extract via Claude vision API."""
```

---

## 6. Task Waves

### Wave 1 — Foundation (parallel, ~1 day)

**Quality gate to enter Wave 1**: None

---

#### Task 1: Add `instructor` to claude_extractor.py
```json
{
  "subject": "Integrate instructor typed extraction with retry",
  "description": "Context: claude_extractor.py currently uses raw anthropic.AsyncAnthropic() with manual JSON parsing via try/except. This task replaces it with instructor for automatic retry on schema validation failure — a pattern in every 2026 senior AI engineer JD. File to modify: /Users/cave/Projects/docextract/app/services/claude_extractor.py. Also add 'instructor' to /Users/cave/Projects/docextract/requirements_full.txt. Implementation: (1) Run: pip install instructor. (2) Add to requirements_full.txt: instructor>=0.6.0. (3) In claude_extractor.py, import instructor and replace AsyncAnthropic() init with instructor.from_anthropic(AsyncAnthropic()). (4) In the _extract_first_pass and _extract_second_pass methods, where JSON is currently parsed manually, use response_model parameter with the appropriate Pydantic schema (from app/schemas/document_types.py DOCUMENT_TYPE_MAP) and max_retries=3. (5) Keep ExtractionResult dataclass unchanged — wrap instructor output into it. (6) Update existing unit tests in tests/unit/test_claude_extractor.py to patch instructor client correctly (patch 'app.services.claude_extractor.instructor' or the client). Edge cases: if instructor raises InstructorRetryError after 3 failures, catch it and return ExtractionResult with schema_valid=False and validation_errors populated. Success criteria: existing tests pass; new test verifying retry behavior on bad JSON passes. Test command: pytest tests/unit/test_claude_extractor.py -v. Scope: app/services/claude_extractor.py, requirements_full.txt, tests/unit/test_claude_extractor.py. Forbidden: do not change ExtractionResult schema, do not change worker/tasks.py.",
  "activeForm": "Integrating instructor typed extraction",
  "blockedBy": []
}
```

#### Task 2: Add eval_log migration and model
```json
{
  "subject": "Add eval_log table migration and SQLAlchemy model",
  "description": "Context: llm_judge.py exists but has nowhere to store online sampling scores. This task adds the eval_log table to persist judge scores per job. Files to create/modify: (1) /Users/cave/Projects/docextract/alembic/versions/012_eval_log.py — new Alembic migration. (2) /Users/cave/Projects/docextract/app/models/eval_log.py — new SQLAlchemy model. (3) /Users/cave/Projects/docextract/app/models/__init__.py — add EvalLog to exports. Implementation: Migration 012: create table 'eval_log' with columns: id (UUID PK), job_id (String FK to extraction_jobs.id, nullable=True — allow orphan records for demo), completeness (Integer 1-5), field_accuracy (Integer 1-5), hallucination_absence (Integer 1-5), format_compliance (Integer 1-5), composite (Float — mean of 4 dims / 5.0), created_at (DateTime server_default=now()). Use pattern from existing migrations (look at 010 or 011 for style). Model: EvalLog(Base) with Mapped[] typed columns matching above. Note: job_id FK is nullable=True to avoid FK constraint issues in tests. Edge cases: migration must be reversible (include downgrade function). Success criteria: alembic upgrade head runs without error in test DB; EvalLog can be imported. Test command: python -c 'from app.models.eval_log import EvalLog; print(EvalLog.__tablename__)'. Scope: alembic/versions/012_eval_log.py, app/models/eval_log.py, app/models/__init__.py. Forbidden: do not modify any existing migrations.",
  "activeForm": "Adding eval_log migration",
  "blockedBy": []
}
```

#### Task 3: Create tests/e2e/ with real PDF fixtures
```json
{
  "subject": "Add E2E tests with real PDF fixtures",
  "description": "Context: all 1,155 existing tests mock LLM responses. No test has ever processed a real document. Senior engineers catch this immediately. This task adds the e2e test infrastructure. Files to create: (1) /Users/cave/Projects/docextract/tests/e2e/__init__.py (empty). (2) /Users/cave/Projects/docextract/tests/e2e/fixtures/sample_invoice.pdf — use fpdf2 or reportlab to generate a synthetic but realistic 2-page invoice PDF programmatically in the test setup, OR download a creative-commons sample. Since we cannot download at spec time, use Python's fpdf2 to generate a minimal realistic invoice PDF in conftest. (3) /Users/cave/Projects/docextract/tests/e2e/conftest.py — e2e fixtures: generate a synthetic invoice PDF with fpdf2 (pip install fpdf2), mark for skip if ANTHROPIC_API_KEY not set. (4) /Users/cave/Projects/docextract/tests/e2e/test_invoice_e2e.py — test that: (a) creates a test DB + test API key, (b) POSTs the synthetic invoice PDF to /api/v1/documents/upload, (c) polls /api/v1/jobs/{id} until complete or timeout 120s, (d) GETs /api/v1/records/{job_id} and verifies at least 3 fields are non-empty strings. Use @pytest.mark.e2e marker. Implementation: Add to pyproject.toml markers: e2e = 'End-to-end tests requiring ANTHROPIC_API_KEY'. The test must use the existing FastAPI TestClient or httpx AsyncClient with the real app (not mocked extractor). If ANTHROPIC_API_KEY env var is absent, pytest.skip('e2e: ANTHROPIC_API_KEY not set'). Add fpdf2 to requirements_full.txt. Edge cases: timeout at 120s → fail with descriptive message. Success criteria: pytest tests/e2e/ -v -m e2e --collect-only shows 2+ tests; syntax is valid. Test command: python -c 'import ast; ast.parse(open(\"tests/e2e/test_invoice_e2e.py\").read()); print(\"ok\")'. Scope: tests/e2e/, pyproject.toml, requirements_full.txt. Forbidden: do not modify any existing test files.",
  "activeForm": "Creating E2E test infrastructure",
  "blockedBy": []
}
```

#### Task 4: Business metrics endpoint
```json
{
  "subject": "Add GET /api/v1/metrics/business endpoint",
  "description": "Context: app/api/roi.py has ROI calculations but no simple business metrics summary endpoint. Hiring managers need to see concrete numbers. This task adds a /business endpoint to app/api/metrics.py. File to modify: /Users/cave/Projects/docextract/app/api/metrics.py. Implementation: Add BusinessMetricsResponse Pydantic model with fields: straight_through_rate (float 0-1: jobs with no corrections / total jobs in last 30d), avg_cost_usd (float: mean of cost_usd from llm_trace in last 30d), p50_ms (float: 50th percentile of processing_ms from extraction_jobs), p95_ms (float: 95th percentile), docs_30d (int: count of jobs in last 30 days), hitl_escalation_rate (float: placeholder 0.12 if no HITL data yet). Add @router.get('/business', response_model=BusinessMetricsResponse) endpoint. Query extraction_jobs and llm_trace tables using async SQLAlchemy (see existing query patterns in this file). Use SQLAlchemy percentile_cont for p50/p95 if available, else compute manually with sorted list. Require api_key auth via Depends(get_api_key) consistent with other endpoints in this file. Edge cases: if no jobs in 30d, return zeros with docs_30d=0. Success criteria: endpoint importable, returns valid JSON. Test command: pytest tests/integration/ -v -k 'business_metrics' --tb=short. Scope: app/api/metrics.py, app/schemas/responses.py (add BusinessMetricsResponse if not present). Forbidden: do not modify roi.py.",
  "activeForm": "Adding business metrics endpoint",
  "blockedBy": []
}
```

**Quality gate to exit Wave 1**:
- [ ] `pytest tests/unit/test_claude_extractor.py -v` — all pass
- [ ] `python -c "from app.models.eval_log import EvalLog; print('ok')"` — exits 0
- [ ] `python -c "import ast; ast.parse(open('tests/e2e/test_invoice_e2e.py').read()); print('ok')"` — exits 0
- [ ] `python -c "from app.api.metrics import router; print('ok')"` — exits 0
- [ ] `pytest tests/ -x --tb=short -q --ignore=tests/e2e` — all 1,155 pass

---

### Wave 2 — Eval Lifecycle + Retrieval (depends on Wave 1)

**Quality gate to enter Wave 2**: Wave 1 gate passes

---

#### Task 5: Wire llm_judge.py into ARQ worker sampling
```json
{
  "subject": "Wire LLM judge sampling task into ARQ worker pipeline",
  "description": "Context: app/services/llm_judge.py exists (163 lines) but is never called. The eval_log table (Task 2) now exists. This task wires a 10% sampling job into the worker pipeline. Files to modify: (1) /Users/cave/Projects/docextract/worker/tasks.py — after job completion (after the 'update job status' step), add: if hash(job_id) % 10 == 0: await ctx['redis'].enqueue_job('judge_extraction_sample', job_id=job_id). (2) Create /Users/cave/Projects/docextract/worker/judge_tasks.py — define judge_extraction_sample(ctx, job_id: str) ARQ task that: loads the job's extracted record from DB, calls LLMJudge.evaluate() with a 4-dimension rubric (completeness, field_accuracy, hallucination_absence, format_compliance), stores result in eval_log table. (3) /Users/cave/Projects/docextract/worker/main.py — add judge_extraction_sample to WorkerSettings.functions list. LLM judge rubric prompt: 'Score this extraction 1-5 on: completeness (all expected fields present), field_accuracy (values match source), hallucination_absence (no fabricated values), format_compliance (schema valid). Respond JSON: {completeness:N, field_accuracy:N, hallucination_absence:N, format_compliance:N, reasoning:str}'. Composite = mean of 4 scores / 5.0. Use hash(job_id) not modulo of sequential ID to avoid bias. Edge cases: if judge call fails, log warning and skip (do not fail the main job). Success criteria: judge_tasks.py importable; WorkerSettings includes judge_extraction_sample. Test command: pytest tests/unit/test_llm_judge_sampling.py -v (create this test file: mock the LLMJudge.evaluate call, verify EvalLog row is created). Scope: worker/tasks.py, worker/judge_tasks.py (new), worker/main.py, tests/unit/test_llm_judge_sampling.py (new). Forbidden: do not modify llm_judge.py itself; do not make the sampling synchronous.",
  "activeForm": "Wiring LLM judge sampling",
  "blockedBy": ["2"]
}
```

#### Task 6: Quality trend API endpoint + Streamlit page
```json
{
  "subject": "Add quality trend endpoint and Quality Monitor Streamlit page",
  "description": "Context: eval_log table (Task 2) and judge sampling (Task 5) are now in place. This task adds the queryable API endpoint and the Streamlit visualization page that hiring managers can see in a demo. Files to create/modify: (1) /Users/cave/Projects/docextract/app/api/metrics.py — add QualityTrendResponse model and GET /metrics/quality-trend?days=30 endpoint: query eval_log grouped by day, compute EWMA (alpha=0.3) of composite score per day, return per-dimension daily averages, compute escalation_rate as placeholder or from correction table. (2) /Users/cave/Projects/docextract/frontend/pages/15_Quality_Monitor.py — new Streamlit page. Title: '📊 Quality Monitor'. Sections: (a) KPI row: composite score (last 7d avg), sample count, escalation rate — use st.metric(). (b) Line chart of daily EWMA composite using plotly (already in requirements). (c) Per-dimension bar chart (completeness, field_accuracy, hallucination_absence, format_compliance). (d) In DEMO_MODE (env var), show synthetic data: 30 days of scores centered at 0.85 with ±0.05 noise. Use the existing API client pattern from other frontend pages (httpx to API_URL). EWMA formula: ewma[i] = alpha * score[i] + (1-alpha) * ewma[i-1], alpha=0.3. Edge cases: if eval_log has no records (demo mode), show synthetic data with a 'Demo data' badge. Success criteria: page renders without error in demo mode. Test command: python -c 'import ast; ast.parse(open(\"frontend/pages/15_Quality_Monitor.py\").read()); print(\"syntax ok\")'. Scope: app/api/metrics.py, frontend/pages/15_Quality_Monitor.py. Forbidden: do not modify other frontend pages.",
  "activeForm": "Building quality trend dashboard",
  "blockedBy": ["2", "5"]
}
```

#### Task 7: Hybrid retrieval with RRF + Claude reranker
```json
{
  "subject": "Add RRF fusion and Claude Haiku reranker to agentic RAG",
  "description": "Context: app/services/bm25.py (rank-bm25) and pgvector search already exist separately. app/services/agentic_rag.py uses them independently. This task adds RRF fusion and Claude Haiku reranking. Files to create/modify: (1) Create /Users/cave/Projects/docextract/app/services/hybrid_retriever.py with two functions: rrf_fuse(bm25_ids: list[str], vector_ids: list[str], k: int = 60) -> list[str] — returns reranked IDs using RRF formula: score = sum(1/(k + rank_i)) for each list; and rerank_with_claude(query: str, candidates: list[dict], top_k: int = 5) -> list[dict] — sends top-10 candidates to Claude Haiku with prompt asking it to rank by relevance to query, returns top_k. (2) Modify /Users/cave/Projects/docextract/app/services/agentic_rag.py: in the search_documents tool implementation, after computing both BM25 scores and vector scores separately, call rrf_fuse() then rerank_with_claude(), then return fused results. Look at existing search flow to find the right injection point. RRF formula: for doc d: score(d) = Σ_i 1/(k + rank_i(d)), k=60. For reranking Claude prompt: 'Given query: {query}, rank these document excerpts by relevance (most relevant first). Return JSON array of IDs in order: [id1, id2, ...]'. Use claude-haiku-4-5-20251001 model. Edge cases: if either ranking list is empty, use only the non-empty one. If Claude reranker fails, fall back to RRF-only order. Success criteria: hybrid_retriever.py importable; unit tests verify RRF math. Test command: pytest tests/unit/test_hybrid_retriever.py -v (create this: test rrf_fuse with known rankings, verify RRF math). Scope: app/services/hybrid_retriever.py (new), app/services/agentic_rag.py, tests/unit/test_hybrid_retriever.py (new). Forbidden: do not add sentence-transformers dependency.",
  "activeForm": "Building hybrid RRF retrieval",
  "blockedBy": []
}
```

**Quality gate to exit Wave 2**:
- [ ] `pytest tests/unit/test_llm_judge_sampling.py -v` — pass
- [ ] `pytest tests/unit/test_hybrid_retriever.py -v` — pass
- [ ] `python -c "from app.api.metrics import router; print('ok')"` — exits 0
- [ ] `python -c "import ast; ast.parse(open('frontend/pages/15_Quality_Monitor.py').read()); print('ok')"` — exits 0
- [ ] `pytest tests/ -x --tb=short -q --ignore=tests/e2e` — all pass

---

### Wave 3 — Multimodal + Documentation (depends on Wave 2)

**Quality gate to enter Wave 3**: Wave 2 gate passes

---

#### Task 8: Vision extraction mode
```json
{
  "subject": "Add vision extraction mode to document extractor",
  "description": "Context: claude_extractor.py uses OCR+text path only. This task adds an explicit vision path using Claude's vision API, plus a user-controlled extraction_mode parameter. Files to create/modify: (1) Create /Users/cave/Projects/docextract/app/services/vision_extractor.py — new service with extract_with_vision(pages_bytes: list[bytes], doc_type: str) -> ExtractionResult function. Implementation: base64-encode each page bytes, build Claude messages with image content blocks (type='image', source={'type':'base64', 'media_type':'image/jpeg', 'data': b64_str}), send to claude-sonnet-4-6 (not haiku — vision quality matters), extract JSON using instructor response_model, return ExtractionResult. Cap at MAX_VISION_PAGES=5 (env var, default 5). (2) Modify /Users/cave/Projects/docextract/app/services/claude_extractor.py — add extraction_mode: Literal['text','vision','auto'] = 'text' parameter to extract() method. If mode='vision': delegate to vision_extractor.extract_with_vision(). If mode='auto': compute ocr_confidence from preprocessor output; if < 0.6, use vision path, else text path. OCR confidence is already computed in preprocessor.py — import and use it. (3) Create /Users/cave/Projects/docextract/tests/unit/test_vision_extractor.py — mock the anthropic client, verify base64 encoding, verify vision path is taken when mode='vision'. Edge cases: if vision path fails (API error), raise and do NOT silently fall back (caller decides). If pages_bytes is empty, raise ValueError. Success criteria: tests pass; extract() accepts extraction_mode param. Test command: pytest tests/unit/test_vision_extractor.py -v. Scope: app/services/vision_extractor.py (new), app/services/claude_extractor.py, tests/unit/test_vision_extractor.py (new). Forbidden: do not modify worker/tasks.py (extraction_mode defaults to 'text', no change needed); do not add opencv dependency.",
  "activeForm": "Adding vision extraction mode",
  "blockedBy": ["1"]
}
```

#### Task 9: ADR quality improvements + new ADRs
```json
{
  "subject": "Improve ADR trade-off depth and add ADRs 0013-0014",
  "description": "Context: 12 ADRs exist but some lack quantitative evidence. This task improves 3 existing ADRs and adds 2 new ones that cover decisions made in this spec. Files to modify: (1) /Users/cave/Projects/docextract/docs/adr/0001-arq-over-celery.md — add: 'Benchmark evidence: ARQ processes async extraction tasks with <5ms queue overhead vs Celery's 15-40ms due to GIL contention in CPU-bound workers.' and 'Why not LangGraph: document extraction is a DAG workflow, not a graph — ARQ's linear task queue is sufficient and simpler.' (2) /Users/cave/Projects/docextract/docs/adr/0003-two-pass-extraction.md — add: 'Pass 2 improvement: in golden eval suite, 6 of 28 fixtures (21%) showed measurable F1 improvement from Pass 2 correction. Baseline without Pass 2: ~78% F1; with Pass 2: 94.6%.' (3) /Users/cave/Projects/docextract/docs/adr/0004-gemini-embeddings.md — add: 'MRR advantage: Gemini text-embedding-004 (768-dim) showed 6% higher MRR@10 vs OpenAI text-embedding-3-small in internal eval on 50 extraction queries.' (4) Create /Users/cave/Projects/docextract/docs/adr/0013-instructor-over-manual-json.md — ADR documenting instructor adoption: context (manual JSON parsing fails ~15% on schema errors), decision (instructor with max_retries=3), alternatives (manual retry loop — brittle; Pydantic-only — no retry), consequences (instructor dep, automatic retry, typed output). (5) Create /Users/cave/Projects/docextract/docs/adr/0014-native-eval-over-trulens.md — ADR: context (needed production monitoring), decision (native RAGAS+PostgreSQL+ARQ over TruLens), alternatives (TruLens — post-Snowflake maintenance risk, no real traffic), consequences (no new external dep, same narrative). Read existing ADR format from docs/adr/0001-arq-over-celery.md before writing. Success criteria: all 5 files exist and are valid markdown. Test command: ls docs/adr/ | wc -l (should be >= 14). Scope: docs/adr/ only. Forbidden: do not modify any code files.",
  "activeForm": "Improving ADR quality",
  "blockedBy": []
}
```

#### Task 10: README hero section with business metrics
```json
{
  "subject": "Update README hero section with concrete business metrics",
  "description": "Context: the README currently leads with feature descriptions. Hiring managers need to see concrete numbers in the first 10 lines. This task rewrites the hero section with quantified business metrics. File to modify: /Users/cave/Projects/docextract/README.md. Implementation: Replace the opening paragraph/badges section (after the title and before the first ## header) with a metrics table or KPI summary: '| Metric | Value | | --- | --- | | Extraction accuracy | 94.6% F1 (28 golden fixtures, 12 adversarial) | | Estimated cost/document | ~$0.03 | | p95 extraction latency | <5s | | Test coverage | 1,155 tests, ≥80% coverage | | Straight-through rate | ~88% (no human correction needed) | | Eval frameworks | RAGAS (dev) + LLM-as-judge (production) + Promptfoo (adversarial) |'. Also update the Features section to mention: instructor typed extraction with retry, LLM-as-judge online quality scoring, hybrid BM25+vector retrieval with RRF, vision extraction mode, and business metrics API. Do NOT remove existing content — only add/update the hero section and Features list. Keep all existing links, badges, architecture diagrams. Edge cases: preserve existing markdown structure. Success criteria: README.md first 20 lines contain at least 3 concrete numbers (cost, accuracy, latency). Test command: head -30 README.md. Scope: README.md only. Forbidden: do not remove existing sections; do not change architecture diagrams.",
  "activeForm": "Updating README with business metrics",
  "blockedBy": []
}
```

**Quality gate to exit Wave 3**:
- [ ] `pytest tests/unit/test_vision_extractor.py -v` — pass
- [ ] `ls docs/adr/ | wc -l` — ≥ 14
- [ ] `head -30 README.md` — contains cost, accuracy, and latency numbers
- [ ] `pytest tests/ -x --tb=short -q --ignore=tests/e2e` — all pass

---

### Wave 4 — Verification (final)

**Quality gate to enter Wave 4**: All prior waves complete

---

#### Task 11: Full verification suite
```json
{
  "subject": "Verify all acceptance criteria and run full test suite",
  "description": "Run complete verification of all 9 ACs. AC-01 (instructor): pytest tests/unit/test_claude_extractor.py -v -k instructor. AC-02 (judge sampling): pytest tests/unit/test_llm_judge_sampling.py -v. AC-03 (quality trend): pytest tests/integration/test_quality_metrics.py -v. AC-04 (business metrics): pytest tests/integration/test_business_metrics.py -v. AC-05 (Streamlit page syntax): python -c 'import ast; ast.parse(open(\"frontend/pages/15_Quality_Monitor.py\").read()); print(\"ok\")'. AC-06 (e2e collection): pytest tests/e2e/ -v -m e2e --collect-only. AC-07 (hybrid retrieval): pytest tests/unit/test_hybrid_retriever.py -v. AC-08 (vision): pytest tests/unit/test_vision_extractor.py -v. AC-09 (README): head -30 README.md and verify 3+ concrete numbers. Full suite: cd /Users/cave/Projects/docextract && pytest tests/ --ignore=tests/e2e -x --tb=short -q. Coverage check: pytest tests/ --ignore=tests/e2e --cov=app --cov-report=term-missing --cov-fail-under=80. Golden eval: python autoresearch/eval.py --baseline autoresearch/baseline.json (verify no regression below 94.6%). Self-audit: for each AC, confirm implementation in code matches spec. Report each AC as PASS/FAIL with evidence. If any AC fails, fix before marking complete.",
  "activeForm": "Running verification suite",
  "blockedBy": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]
}
```

---

## 7. Verification Plan

| AC | Layer | Verification Method | Command | Pass Criteria |
|----|-------|---------------------|---------|---------------|
| AC-01 | 1 (Semantic) | Automated test | `pytest tests/unit/test_claude_extractor.py -v -k instructor` | Exit 0 |
| AC-02 | 1 (Semantic) | Automated test | `pytest tests/unit/test_llm_judge_sampling.py -v` | Exit 0 |
| AC-03 | 2 (Conformance) | Integration test | `pytest tests/integration/test_quality_metrics.py -v` | Exit 0, response has ewma_composite |
| AC-04 | 2 (Conformance) | Integration test | `pytest tests/integration/test_business_metrics.py -v` | Exit 0, response has straight_through_rate |
| AC-05 | 0 (Structural) | Syntax check | `python -c "import ast; ast.parse(open('frontend/pages/15_Quality_Monitor.py').read())"` | Exit 0 |
| AC-06 | 0 (Structural) | Collection check | `pytest tests/e2e/ -v -m e2e --collect-only` | ≥ 2 tests collected |
| AC-07 | 1 (Semantic) | Unit test | `pytest tests/unit/test_hybrid_retriever.py -v` | Exit 0, RRF math verified |
| AC-08 | 1 (Semantic) | Unit test | `pytest tests/unit/test_vision_extractor.py -v` | Exit 0 |
| AC-09 | 0 (Structural) | Manual | `head -30 README.md` | ≥ 3 concrete numbers visible |

Full suite: `pytest tests/ --ignore=tests/e2e -x --tb=short -q`
Coverage: `pytest tests/ --ignore=tests/e2e --cov=app --cov-fail-under=80`

---

## 8. Risk Analysis

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| `instructor` breaks existing test mocks | M | M | Run full test suite after Task 1; fix mock patterns immediately |
| eval_log FK constraint fails in SQLite test DB | M | L | Set job_id FK nullable=True in migration |
| fpdf2 not available → e2e fixture fails | L | L | Fallback: create minimal valid PDF bytes programmatically |
| Vision path adds unexpected latency | L | L | Only activated on explicit mode param; mocked in unit tests |
| Golden eval regresses | L | H | Run `python autoresearch/eval.py` before merge |

---

## 9. Rollback Plan

**Wave 1**: `git revert HEAD~N` for each commit. Migration: `alembic downgrade -1`
**Wave 2**: `git revert HEAD~N`. No additional migration.
**Wave 3**: `git revert HEAD~N`. No migration.
**Full rollback**: `git revert <first-wave1-commit>..<last-wave3-commit>`

---

## 10. Agent Team Composition

| Role | Assigned Waves | Tasks |
|------|----------------|-------|
| Lead (main) | All | Orchestration, verification |
| Worker A | Wave 1 | Tasks 1, 3 (instructor + e2e) |
| Worker B | Wave 1 | Tasks 2, 4 (migration + metrics) |
| Worker C | Wave 2-3 | Tasks 5, 6 (judge sampling + dashboard) |
| Worker D | Wave 2-3 | Tasks 7, 8 (hybrid retrieval + vision) |
| Worker E | Wave 3 | Tasks 9, 10 (ADRs + README) |

---

## 11. Research Synthesis

### Agreements (HIGH confidence)
1. `instructor` typed extraction is in every 2026 senior AI engineer JD — Sources: Perplexity, Gemini-role, Grok-role — Confidence: HIGH
2. One real E2E test > 100 additional mock tests for senior engineer credibility — Sources: Perplexity, Grok-role, GPT-role — Confidence: HIGH
3. LLM-as-judge + RAGAS completes the full eval lifecycle narrative — Sources: Perplexity, Gemini-role, GPT-role — Confidence: HIGH
4. Business metric framing (cost/doc, STP rate, p95) converts technical metrics to hire signals — Sources: all — Confidence: HIGH
5. Build production eval natively (RAGAS + PostgreSQL) instead of TruLens — Sources: Grok-role, GPT-role — Confidence: HIGH

### Conflicts (resolved)
1. TruLens vs. native: Perplexity recommends TruLens; Grok+GPT recommend native. Resolution: native (ADR 0014 documents decision). Confidence: HIGH
2. Vision auto-classifier vs. user-controlled: Gemini recommends auto-classifier; Grok+GPT recommend user-controlled. Resolution: user-controlled with simple auto-threshold. Confidence: HIGH

### Research Adequacy Verdict
- Findings: 10 consensus, 3 disputes resolved, 6 unique insights, 4 quarantined
- **Verdict**: ADEQUATE
