# DocExtract AI: From Unstructured Documents to Structured Data in Seconds

## The Challenge

Every organization that processes documents at scale runs into the same wall: PDFs, scanned images, emails, and attachments arrive in unpredictable formats, and someone has to pull the data out of them. Manual extraction is slow, inconsistent, and expensive. Template-based OCR tools break the moment a vendor changes their invoice layout.

The specific problem here was building a production-grade document intelligence API that could:

- Accept any document format (PDF, image, email) without pre-configuration
- Auto-classify the document type and extract the right fields
- Handle low-confidence extractions gracefully rather than silently producing bad data
- Process documents asynchronously with real-time status updates
- Deduplicate resubmissions automatically
- Notify downstream systems reliably when results are ready

Previous approaches using template-matching OCR required manual maintenance for every new document layout, produced silent errors with low-confidence reads, and offered no review workflow for ambiguous extractions.

## The Solution

DocExtract AI is a FastAPI-based document intelligence service built on three core decisions: async-first processing, two-pass AI extraction with automatic error correction, and a semantic search layer that makes extracted records findable by meaning, not just metadata.

### Architecture Overview

```
Client
  │
  ▼
FastAPI (REST API)              /metrics ──► Prometheus
  │  ├── POST /documents/upload  ──► SHA-256 dedup → ARQ queue
  │  ├── GET  /jobs/{id}/events  ──► SSE stream (Redis pub/sub)
  │  ├── GET  /records           ──► paginated extracted records
  │  └── GET  /search            ──► pgvector semantic search
  │
  ▼
ARQ Worker (async Python)
  │
  ├── 1. MIME detection + routing
  ├── 2. Text extraction (PDF/image/email)
  ├── 3. Document classification ──► Model Router ──► Haiku (primary)
  │                                                └── Sonnet (fallback)
  ├── 4. Two-pass Claude extraction
  │       Pass 1: JSON extraction ──► Model Router ──► Sonnet (primary)
  │                                                └── Haiku (fallback)
  │       Pass 2: tool_use correction (if confidence < threshold)
  │       [Circuit breaker per model: CLOSED/OPEN/HALF_OPEN]
  ├── 5. Business rule validation
  ├── 6. pgvector HNSW embedding (gemini-embedding-2-preview, 768-dim)
  └── 7. HMAC-signed webhook delivery (4-attempt retry)

PostgreSQL + pgvector    Redis (rate limiting + pub/sub + circuit state)
```

### Key Technical Decisions

**Two-pass extraction** is the architectural centerpiece. Pass 1 calls Claude with a structured JSON prompt and asks for a `_confidence` field. If confidence falls below 0.80, Pass 2 fires a second call using Claude's `tool_use` API — the model returns corrections as a structured `apply_corrections` tool call, which are merged into the original extraction. This catches ~15-20% of extractions that would otherwise silently produce incomplete or malformed records.

**SHA-256 deduplication** on upload. Before queuing a new job, the API hashes the raw file bytes and queries for an existing document with the same hash. Resubmitted files return the existing job ID immediately — no duplicate processing, no wasted API calls.

**Redis sliding-window rate limiting** is wired directly into the API key middleware. Each request adds a timestamped score to a sorted set, removes scores older than 60 seconds, and checks the remaining count against the key's per-minute limit — all in a single Redis pipeline. Rate limit headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `Retry-After`) are returned on 429 responses.

**SSE streaming** for real-time job progress. The ARQ worker publishes status events to Redis pub/sub channels (`job:{id}:events`) at each pipeline stage. The API exposes a `/jobs/{id}/events` endpoint that subscribes and streams these as Server-Sent Events. Clients get live progress updates (PREPROCESSING → EXTRACTING_TEXT → CLASSIFYING → EXTRACTING_DATA → VALIDATING → EMBEDDING → COMPLETED) without polling.

**AES-GCM encrypted webhook secrets** at rest. Webhook signing secrets are encrypted before storage using a server-side AES key and decrypted only at delivery time. Delivered payloads carry an `X-Signature-256` HMAC-SHA256 header for receiver-side verification.

### Integration Points

- **Storage**: pluggable backend (local filesystem or Cloudflare R2) behind a common interface
- **OCR**: Tesseract or PaddleOCR depending on document type
- **AI**: Anthropic Claude (Sonnet → Haiku fallback via circuit breaker model router) for extraction and correction
- **Embeddings**: Google Gemini gemini-embedding-2-preview (768-dim, HNSW index)
- **Queue**: ARQ (async Redis queue) with ARQ worker as a separate Render service
- **Frontend**: Streamlit 13-page dashboard (Upload, Progress, Results, Review, Records, Dashboard, Analytics, Settings, Cost Dashboard, Demo, Architecture, Evaluation, Prompt Lab)

## The Results

**925 tests passing** — unit tests for every service layer, integration tests for the full upload-to-extraction pipeline, load tests via Locust.

**92.6% extraction accuracy** measured against 16 golden eval fixtures across 6 document types (invoice, receipt, purchase order, bank statement, medical record, identity document). Enforced in CI with a 2% regression tolerance.

**12-step processing pipeline** with per-step progress tracking and real-time SSE streaming to connected clients.

**Two-pass extraction with automatic correction** eliminates silent failures for low-confidence documents — the most common failure mode in template-based OCR systems.

**Sub-second deduplication** — SHA-256 hash lookup prevents reprocessing identical files before any storage write or queue enqueue occurs.

**Zero-downtime deployment** on Render with three independent services (API, Worker, Frontend) each deployable independently.

**176 Python files** across API, worker, services, frontend, tests, migrations, and scripts — full production codebase, not a prototype.

### Performance Profile

| Metric | Value |
|--------|-------|
| Test suite runtime | 2 seconds (925 tests) |
| Extraction accuracy | 92.6% (golden eval, 16 fixtures, 6 doc types) |
| Embedding model | gemini-embedding-2-preview, 768-dim, HNSW index |
| Extraction confidence threshold | 0.80 global; per-type overrides (0.75–0.90) |
| Max file size | 50 MB |
| Max pages (PDF) | 100 |
| Worker concurrency | 10 parallel jobs |
| Job timeout | 300 seconds |
| Webhook retry schedule | 0s → 30s → 5min → 30min |
| Rate limiting | sliding 60-second window, per API key |
| Circuit breaker recovery | 60s window, 5-failure threshold |

## Technical Deep Dive

### Two-Pass Extraction with Circuit Breaker Fallback

```python
async def extract(text: str, doc_type: str) -> ExtractionResult:
    router = ModelRouter(
        failure_threshold=settings.circuit_breaker_failure_threshold,
        recovery_timeout=settings.circuit_breaker_recovery_seconds,
    )

    # Pass 1: structured JSON extraction via fallback chain
    async def _extract_call(model: str) -> Message:
        async with trace_llm_call(db, model, "extract") as ctx:
            response = await client.messages.create(
                model=model,  # Sonnet → Haiku on circuit-open
                messages=[{"role": "user", "content": EXTRACT_PROMPT.format(...)}],
            )
            ctx.record_response(response)
        return response

    response, model_used = await router.call_with_fallback(
        operation="extract",
        chain=settings.extraction_models,  # ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"]
        call_fn=_extract_call,
    )

    extracted = _parse_json_response(response.content[0].text)
    confidence = float(extracted.pop("_confidence", 0.5))

    # Pass 2: tool_use correction for low-confidence results
    threshold = settings.confidence_thresholds.get(doc_type, 0.80)
    if confidence < threshold:
        extracted, corrections_applied = await _apply_corrections_pass(
            client, text, doc_type, extracted, confidence, router=router
        )

    return ExtractionResult(data=extracted, confidence=confidence,
                            corrections_applied=corrections_applied,
                            model_used=model_used)
```

The circuit breaker tracks failures per model. When Claude Sonnet hits its failure threshold (rate limit spike, 5xx errors), it opens the circuit and the router automatically routes to Claude Haiku without any manual intervention. The HALF_OPEN state probes recovery before restoring full traffic. The correction pass uses Claude's native `tool_use` API for structured corrections — deterministic and auditable.

### 12-Step Worker Pipeline

The ARQ worker runs the full pipeline in a single async function with granular status updates at each step. Redis pub/sub events fire after every stage transition, so a browser tab watching the SSE stream shows a live progress bar as the document moves through extraction.

### pgvector Semantic Search

Documents are embedded using gemini-embedding-2-preview (768 dimensions) at the end of every successful extraction. The embeddings are stored in PostgreSQL via pgvector with an HNSW index for approximate nearest-neighbor queries. This enables semantic search across extracted records — finding invoices similar to a reference document, or surfacing contracts that mention specific concepts without exact keyword matching.

## Shipped Improvements (P1/P2 Roadmap)

The three items originally listed as "what I'd do differently" were subsequently implemented:

- **Page-by-page streaming**: Long PDFs now emit partial extraction results per page via SSE — no blocking until full-document completion.
- **Per-type confidence thresholds**: `CONFIDENCE_THRESHOLDS` accepts a JSON dict mapping document type to threshold. Identity documents default to 0.90; receipts to 0.75.
- **Hybrid search (BM25 + RRF)**: The `/records/search` endpoint accepts `?mode=hybrid` to combine pgvector cosine similarity and BM25 keyword scores via reciprocal rank fusion. Pure `bm25` mode is also available.

Additional features shipped in the same pass:

- **Structured table extraction**: Tables are extracted as JSON (headers + rows) rather than flattened to markdown text.
- **Vision-native extraction path**: `OCR_ENGINE=vision` routes image documents through Claude's vision API, bypassing Tesseract — handles handwriting significantly better.
- **Active learning from HITL corrections**: When `ACTIVE_LEARNING_ENABLED=true`, approved human corrections feed back into subsequent extraction prompts, improving accuracy over time.
- **MCP tool server**: `mcp_server.py` exposes `extract_document` and `search_records` as MCP tools for Claude Desktop or any agent host.

## Production Reliability Sprint

The three features that turned docextract from a demo into a system you'd trust in production:

**Circuit breaker model fallback** (`app/services/circuit_breaker.py`, `app/services/model_router.py`). Each model in the fallback chain has its own `AsyncCircuitBreaker` — a CLOSED/OPEN/HALF_OPEN state machine behind an `asyncio.Lock`. When a model trips (5 consecutive failures: rate limits, 5xx), its circuit opens and calls route to the next model in the chain. After a 60-second recovery window it enters HALF_OPEN and probes with a single call. Extraction chains Sonnet→Haiku; classification chains Haiku→Sonnet (inverted by intent: classification is simpler, so Haiku-first is the preferred path not the degraded one).

**Golden eval CI gate** (`scripts/run_eval_ci.py`, `autoresearch/baseline.json`). 16 golden fixtures covering all 6 document types run in CI after every push. The gate loads a committed baseline score (92.6%) and fails the build if the current run drops more than 2%. The `--update-baseline` flag accepts an intentional regression. This makes extraction quality a first-class CI signal — the same way coverage thresholds gate code quality.

**OpenTelemetry + Prometheus** (`app/observability.py`). Feature-flagged behind `OTEL_ENABLED=false` so existing CI is unaffected. When enabled, `setup_telemetry(app)` creates a `PrometheusMetricReader`, mounts `/metrics`, and wires up three instruments: `llm_call_duration_ms` (Histogram), `llm_calls_total` (Counter), and `llm_tokens_total` (Counter). The bridge pattern augments the existing `llm_tracer.py` DB tracing rather than replacing it — the DB traces power the `/stats` endpoint and ROI features; OTel powers ops dashboards.

## AI Engineering Sprint (March 2026)

Six additional capabilities shipped in a single parallel-agent sprint:

**Agentic RAG with ReAct Tool-Use Loop**
A ReAct (Reasoning + Acting) agent autonomously selects from 5 retrieval tools per query — vector similarity, BM25 keyword search, hybrid RRF, metadata lookup, and result reranking. The agent's reasoning trace (Think → Act → Observe → Confidence) is fully logged. Confidence-gated at 0.8 with max 3 iterations to bound cost.

**RAGAS Evaluation Pipeline**
Three production evaluation metrics: context recall (0.35), faithfulness (0.40), answer relevancy (0.25). Faithfulness carries the highest weight because hallucination is the worst failure mode. An LLM-as-judge evaluator scores outputs against structured rubrics with few-shot examples and evidence extraction. Feature-flagged to avoid CI cost.

**Structured Output Extraction**
Per-document-type Pydantic schemas (Invoice, Contract, Receipt, Medical Record) with field-level confidence scores. Batch processing uses `asyncio.gather` with `Semaphore(5)` for concurrency control. One retry on parse failure before raising.

**Cost Tracker and Model A/B Testing**
`CostTracker` computes USD cost per request using Decimal arithmetic against a model pricing table — avoiding float rounding errors. `ModelABTest` uses SHA-256 hashing for deterministic variant assignment and a two-sample z-test for statistical significance. Both integrate into the existing `llm_traces` table, requiring no new storage.

**Prompt Versioning and Regression Testing**
Prompts stored as versioned files (`prompts/{category}/vX.Y.Z.txt`) with env-configurable active version. `PromptRegressionTester` runs the golden eval suite against two prompt versions and flags regressions above 2%. Changes that improve accuracy but increase cost are surfaced as tradeoffs, not automatically accepted.

**Interactive Demo Sandbox**
`DEMO_MODE=true` enables a pre-cached demo with no API keys, no database, and no document uploads. Three tabs: structured extraction with field-level confidence visualization, hybrid semantic search, and RAGAS evaluation scores. Loads in under 3 seconds.

## What I'd Still Do Differently

- **Field-level confidence**: Current confidence scores are document-level. Field-level scores (e.g., `total: 0.97, address: 0.61`) would let reviewers focus attention on specific uncertain fields rather than re-reviewing the entire record.
- **Multilingual extraction prompts**: Non-English documents extract with degraded accuracy because prompts are English-only. A language-detect + prompt-translate layer would extend the system to European and LATAM markets without model changes.
- **Full SROIE F1 benchmark**: The benchmark script exists, dry-run scoring validation passes, but publishing real field-level F1 numbers against the full SROIE dataset requires API credits and dataset download. The golden eval accuracy (92.6%) covers all doc types but SROIE would add an externally auditable reference point.
- **Streaming agentic RAG**: the ReAct loop currently runs to completion before returning; SSE streaming of intermediate reasoning steps would improve perceived latency
- **Cross-document queries**: agentic retrieval is currently scoped to single documents; extending to multi-document queries with source attribution is a natural next step

## Key Takeaways

- The two-pass correction architecture pattern is reusable for any domain where structured extraction quality matters — medical records, legal contracts, financial documents.
- Redis pub/sub + SSE is a clean, lightweight pattern for real-time job progress that avoids WebSocket complexity.
- SHA-256 deduplication at the upload boundary is cheap insurance that prevents significant wasted compute in any document processing pipeline.
- Separating the API, worker, and frontend into independent deployable services makes scaling and debugging dramatically simpler than a monolith.

---

## Short Format — LinkedIn Post

Just shipped DocExtract AI: a production document intelligence API that turns PDFs, scanned images, and emails into structured, searchable data.

Four things I'm proud of in this build:

- **92.6% extraction accuracy** measured against 16 golden eval fixtures, gated in CI with a 2% regression tolerance. Extraction quality is a first-class CI signal.
- **Circuit breaker model fallback**: Per-model CLOSED/OPEN/HALF_OPEN state machines route around provider outages automatically. Sonnet → Haiku on extraction, Haiku → Sonnet on classification. No downtime during rate limit spikes.
- **Two-pass Claude extraction**: Pass 1 extracts structured JSON with a confidence score. If confidence < 80%, Pass 2 fires a tool_use correction call — Claude returns field-level fixes as structured data, not free text.
- **Agentic RAG (ReAct)**: autonomous retrieval agent selects from 5 tools per query — vector, BM25, hybrid, metadata, rerank. Confidence-gated at 0.8 with max 3 iterations.
- **RAGAS evaluation pipeline**: context recall, faithfulness, and answer relevancy scored by LLM-as-judge with structured rubric. CI gate blocks regressions.
- **925 tests in 2 seconds**: Full unit + integration coverage including eval regression gate, circuit breaker state machine tests, and OTel bridge tests.

Stack: FastAPI + ARQ + pgvector HNSW + Claude Sonnet/Haiku + OpenTelemetry + Prometheus + Streamlit
Live: https://docextract-api.onrender.com | https://docextract-frontend.onrender.com
GitHub: ChunkyTortoise/docextract

The circuit breaker + eval gate combination is the piece I'd carry into any future AI pipeline — reliability and measurable quality are what separate production systems from demos.
