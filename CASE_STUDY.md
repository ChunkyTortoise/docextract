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
FastAPI (REST API)
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
  ├── 3. Document classification
  ├── 4. Two-pass Claude extraction
  │       Pass 1: JSON extraction (claude-sonnet-4-6)
  │       Pass 2: tool_use correction (if confidence < 0.80)
  ├── 5. Business rule validation
  ├── 6. pgvector HNSW embedding (gemini-embedding-2-preview, 768-dim)
  └── 7. HMAC-signed webhook delivery (4-attempt retry)

PostgreSQL + pgvector    Redis (rate limiting + pub/sub)
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
- **AI**: Anthropic Claude (claude-sonnet-4-6) for extraction and correction
- **Embeddings**: Google Gemini gemini-embedding-2-preview (768-dim, HNSW index)
- **Queue**: ARQ (async Redis queue) with ARQ worker as a separate Render service
- **Frontend**: Streamlit 6-page dashboard (Upload, Progress, Results, Review, Records, Dashboard)

## The Results

**446 tests passing** — unit tests for every service layer, integration tests for the full upload-to-extraction pipeline, load tests via Locust.

**12-step processing pipeline** with per-step progress tracking and real-time SSE streaming to connected clients.

**Two-pass extraction with automatic correction** eliminates silent failures for low-confidence documents — the most common failure mode in template-based OCR systems.

**Sub-second deduplication** — SHA-256 hash lookup prevents reprocessing identical files before any storage write or queue enqueue occurs.

**Zero-downtime deployment** on Render with three independent services (API, Worker, Frontend) each deployable independently.

**103 files** across API, worker, services, frontend, tests, migrations, and scripts — full production codebase, not a prototype.

### Performance Profile

| Metric | Value |
|--------|-------|
| Test suite runtime | 2 seconds (446 tests) |
| Embedding model | gemini-embedding-2-preview, 768-dim, HNSW index |
| Extraction confidence threshold | 0.80 (configurable) |
| Max file size | 50 MB |
| Max pages (PDF) | 100 |
| Worker concurrency | 10 parallel jobs |
| Job timeout | 300 seconds |
| Webhook retry schedule | 0s → 30s → 5min → 30min |
| Rate limiting | sliding 60-second window, per API key |

## Technical Deep Dive

### Two-Pass Extraction (the core innovation)

```python
def extract(text: str, doc_type: str) -> ExtractionResult:
    # Pass 1: structured JSON extraction
    response = client.messages.create(
        model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": EXTRACT_PROMPT.format(...)}],
    )
    extracted = _parse_json_response(response.content[0].text)
    confidence = float(extracted.pop("_confidence", 0.5))

    # Pass 2: tool_use correction for low-confidence results
    if confidence < settings.extraction_confidence_threshold:
        extracted, corrections_applied = _apply_corrections_pass(
            client, text, doc_type, extracted, confidence
        )

    return ExtractionResult(data=extracted, confidence=confidence,
                            corrections_applied=corrections_applied)
```

The correction pass uses Claude's native `tool_use` API to return structured corrections — not free-form text that needs re-parsing. This makes the correction merge deterministic and auditable.

### 12-Step Worker Pipeline

The ARQ worker runs the full pipeline in a single async function with granular status updates at each step. Redis pub/sub events fire after every stage transition, so a browser tab watching the SSE stream shows a live progress bar as the document moves through extraction.

### pgvector Semantic Search

Documents are embedded using gemini-embedding-2-preview (768 dimensions) at the end of every successful extraction. The embeddings are stored in PostgreSQL via pgvector with an HNSW index for approximate nearest-neighbor queries. This enables semantic search across extracted records — finding invoices similar to a reference document, or surfacing contracts that mention specific concepts without exact keyword matching.

## What I'd Do Differently

- **Streaming extraction**: For large PDFs, extract and stream partial results page-by-page rather than waiting for the full document. Reduces perceived latency significantly.
- **Confidence calibration**: The 0.80 threshold is a reasonable default but should be configurable per document type — a driver's license extraction should have a higher bar than a generic form.
- **Hybrid search**: Add BM25 keyword search alongside pgvector semantic search and combine scores via RRF (reciprocal rank fusion) for better recall on exact field values.

## Key Takeaways

- The two-pass correction architecture pattern is reusable for any domain where structured extraction quality matters — medical records, legal contracts, financial documents.
- Redis pub/sub + SSE is a clean, lightweight pattern for real-time job progress that avoids WebSocket complexity.
- SHA-256 deduplication at the upload boundary is cheap insurance that prevents significant wasted compute in any document processing pipeline.
- Separating the API, worker, and frontend into independent deployable services makes scaling and debugging dramatically simpler than a monolith.

---

## Short Format — LinkedIn Post

Just shipped DocExtract AI: a production document intelligence API that turns PDFs, scanned images, and emails into structured, searchable data.

Three things I'm proud of in this build:

- **Two-pass Claude extraction**: Pass 1 extracts structured JSON and returns a confidence score. If confidence < 80%, Pass 2 fires a tool_use correction call — Claude returns specific field fixes as structured data, not free text. Catches the silent failures that kill data quality in production.
- **Real-time SSE streaming**: Every pipeline stage (text extraction → classification → AI extraction → embedding) publishes to Redis pub/sub. The frontend gets live progress updates without polling.
- **446 tests in 2 seconds**: Full unit + integration coverage, async-native test suite, runs fast enough that it's never a reason to skip.

Stack: FastAPI + ARQ + pgvector HNSW + Claude Sonnet + Streamlit
Live: https://docextract-api.onrender.com | https://docextract-frontend.onrender.com
GitHub: ChunkyTortoise/docextract

The two-pass correction pattern is the piece I'd carry into any future document intelligence work — it's the difference between an MVP and a system you can trust in production.
