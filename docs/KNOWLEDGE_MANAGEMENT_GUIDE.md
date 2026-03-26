# Knowledge Management Guide

## What DocExtract Is

DocExtract is a document intelligence platform that converts unstructured documents into a searchable, queryable knowledge base. It handles the full pipeline: ingest documents in any format, extract structured data using AI, embed content into a vector database, and expose everything through a hybrid search and RAG Q&A interface.

The result is a knowledge base that answers questions like "What are the indemnification limits in our 2023 vendor contracts?" or "Which technical manuals reference component XR-40?" across thousands of documents — without manual tagging, indexing, or data entry.

---

## Architecture

### Pipeline Overview

```
Document Upload
    │
    ▼
MIME Detection (python-magic)
    │
    ▼
Text Extraction
  ├─ PDF (pdfplumber for text-layer, Tesseract for OCR)
  ├─ Image (Tesseract OCR / Claude Vision)
  └─ Email (headers + body + attachments)
    │
    ▼
Document Classification (Haiku primary / Sonnet fallback)
  └─ Returns: doc_type, confidence score
    │
    ▼
Two-Pass Structured Extraction (Sonnet primary / Haiku fallback)
  ├─ Pass 1: JSON extraction with per-field confidence scores
  └─ Pass 2 (if confidence < 0.80): tool_use correction call
    │
    ▼
Guardrails (when GUARDRAILS_ENABLED=true)
  ├─ PII detection: SSN, credit card, phone, email
  └─ Grounding check: extracted values validated against source text
    │
    ▼
Embedding (Gemini embedding, 768-dim)
  └─ Stored in pgvector HNSW index
    │
    ▼
Delivery
  ├─ Webhook POST (HMAC-signed, 4-attempt retry)
  └─ SSE event stream to listening clients
```

### Storage Layer

| Component | Purpose |
|-----------|---------|
| PostgreSQL + pgvector | Structured records, embeddings, audit logs |
| Redis | Job queue (ARQ), rate limiting, SSE pub/sub |
| File Storage | Raw documents (local filesystem or Cloudflare R2) |

### Search Architecture

Queries hit a hybrid search endpoint that fuses two signals:

- **Semantic search**: Query is embedded (768-dim Gemini), compared against all document embeddings via pgvector HNSW cosine similarity
- **BM25 keyword search**: Term-frequency matching via `app/services/bm25.py`
- **Fusion**: Reciprocal Rank Fusion (RRF) combines both result lists (`?mode=hybrid`)

This combination outperforms either approach alone: keyword search catches exact terminology (contract clause numbers, part codes), semantic search catches meaning without exact match.

---

## Use Cases

### Contract Management

Upload contracts in bulk. DocExtract classifies each document as a contract, extracts parties, effective dates, termination clauses, indemnification limits, and governing law. Ask questions across your entire contract library: "Which contracts expire in Q3?" or "Find contracts where liability is capped below $500,000."

**Fields extracted**: party names, effective date, expiration date, auto-renewal terms, liability cap, jurisdiction, signatory names

### Compliance Documentation

Maintain a live knowledge base of policies, procedures, and regulatory filings. When auditors ask for evidence of a specific control, the system returns the relevant paragraph with source document reference and extraction timestamp.

**Fields extracted**: policy name, effective date, version number, owner, applicable regulation, review cycle

### Technical Manuals and Documentation

Index product manuals, service bulletins, and engineering specifications. Technicians query in natural language: "What torque spec applies to the XR-40 fastener?" The RAG Q&A layer synthesizes an answer with citations.

**Scale**: The pgvector HNSW index handles 100M+ vectors with sub-100ms query latency.

### Research Libraries

Upload research papers, reports, and analyst notes. The platform extracts metadata (authors, publication date, methodology, key findings) and enables semantic search across the full corpus. Multi-document synthesis (via `agentic_rag.py`) can answer questions that require pulling information from multiple sources.

### Medical Records

Extract structured data from clinical notes, lab reports, and discharge summaries. The PII detection pipeline automatically flags records containing PHI and routes them to a human review queue. Guardrails verify extracted values appear in the source text before storage.

**Note**: PHI processing requires an Anthropic BAA. See `docs/COMPLIANCE.md`.

---

## Key Capabilities

### Hybrid Search: BM25 + pgvector

Default mode (`?mode=vector`) uses semantic search only. Hybrid mode (`?mode=hybrid`) fuses BM25 and vector results using RRF. Use hybrid mode when your documents contain precise identifiers (contract numbers, part codes, regulation citations) where exact-term matching matters.

```
GET /api/v1/search?q=indemnification+liability+cap&mode=hybrid&limit=10
```

### Claude-Powered Extraction: 94.6% Accuracy

The two-pass extraction pipeline runs on every document:

1. **Pass 1**: Claude Sonnet produces a structured JSON extraction with per-field confidence scores
2. **Pass 2**: If any field confidence falls below 0.80, a second `tool_use` call targets those specific fields for correction

Evaluated on a 28-fixture test suite including 12 adversarial cases (4 prompt injection attempts). Accuracy: 94.6% on the golden fixture set.

Model fallback chain: Sonnet primary → Haiku fallback (circuit breaker triggers after 5 failures, recovers after 60s).

### Document Classification

Before extraction, every document is classified by type using Claude Haiku:
- Supported types: contract, invoice, medical_record, email, research_paper, technical_manual, financial_statement
- Classification confidence is stored with the record
- The extraction schema adapts based on doc_type

Classification uses Haiku (lower cost) with Sonnet as fallback, since classification requires less reasoning than extraction.

### Chunking Pipeline for Large Documents

`app/services/chunker.py` splits large documents before embedding:
- Configurable chunk size (default: 512 tokens) with overlap
- Chunk boundaries respect paragraph and sentence structure
- Each chunk gets its own embedding; search results return the matching chunk plus parent document metadata
- Multi-document synthesis (`agentic_rag.py`) reassembles context across chunks

### Streaming Q&A via SSE

Question answering streams token-by-token over Server-Sent Events:

```
GET /jobs/{id}/events         → SSE stream for job progress
GET /api/v1/rag/stream?q=...  → Streaming RAG Q&A
```

The SSE approach works through standard HTTP proxies and load balancers without WebSocket upgrade requirements.

### Audit Trails

Every record action appends an entry to the `audit_logs` table. Entries are immutable (append-only, no UPDATE or DELETE):

| Field | Description |
|-------|-------------|
| entity_type | Document, Record, Job, etc. |
| entity_id | UUID of the affected entity |
| action | created, claimed, approved, corrected, deleted |
| actor | API key identifier or user ID |
| old_data | JSON snapshot before change |
| new_data | JSON snapshot after change |
| timestamp | UTC timestamp |

This produces a complete chain of custody for every document: upload → extraction → review → approval.

### Human-in-the-Loop Review Queue

Records are automatically routed to the review queue when:
- PII is detected in extracted output (requires human verification before downstream use)
- Extraction confidence falls below the configured threshold
- Grounding check finds ungrounded fields (extraction not supported by source text)

The review queue is accessible at `GET /api/v1/records?needs_review=true`. Reviewers claim records, make corrections, and approve them. All corrections feed back into the DPO training pipeline for future model improvement.

### Multi-Model Support

Supported models are controlled via environment variables:

```
EXTRACTION_MODELS=claude-sonnet-4-6,claude-haiku-4-5
CLASSIFICATION_MODELS=claude-haiku-4-5,claude-sonnet-4-6
EMBEDDING_MODEL=models/gemini-embedding-2-preview-0514
```

Model usage is tracked per record. The `model_ab_test.py` service supports controlled A/B experiments across models with accuracy and cost comparison.

---

## Enterprise Deployment

### Infrastructure Options

| Option | Setup Time | Monthly Cost | Best For |
|--------|-----------|-------------|---------|
| Docker Compose | 30 min | $24 (VPS) | Evaluation, small teams |
| Render Blueprint | 15 min | ~$35 | Early production |
| AWS Terraform | 2-4 hrs | ~$190 | Enterprise, high volume |
| K8s / GKE | 4-8 hrs | ~$140 | Existing K8s infrastructure |

See `deploy/COST_ANALYSIS.md` for a full breakdown.

### Kubernetes Architecture

Three Kubernetes services, each with independent HPA:

**API** (api-deployment.yaml)
- 2 replicas minimum, 8 maximum
- Autoscales on CPU (70% threshold) and memory (80% threshold)
- Rolling update with zero downtime (maxUnavailable: 0)
- Resource limits: 500m CPU, 512Mi memory

**Worker** (worker-deployment.yaml)
- 2 replicas minimum, 6 maximum
- CPU-bound autoscaling (OCR and embedding are the bottlenecks)
- Scales up immediately (stabilizationWindowSeconds: 0), scales down slowly (5 min window)

**Redis**
- Single instance for queue and SSE pub/sub
- Replace with ElastiCache for production HA

Kustomize overlays at `deploy/k8s/overlays/` for environment-specific configuration without duplicating base manifests.

### AWS Terraform

Managed services reduce operational overhead:
- **RDS PostgreSQL 16** (db.t3.micro): automated backups, point-in-time recovery
- **ElastiCache Redis 7** (cache.t3.micro): Redis AUTH, VPC isolation
- **S3 bucket**: document storage with AES-256 server-side encryption and versioning enabled
- **ECR**: container registry with automated vulnerability scanning on push

All provisioned from `deploy/aws/main.tf` with a single `terraform apply`.

### Observability

Grafana dashboard (`deploy/grafana/docextract-dashboard.json`) provides 9 monitoring panels:
- LLM call latency: p50/p95/p99 by model
- Queue depth: pending jobs
- Extraction accuracy: rolling accuracy vs. eval threshold
- Cache hit rate: semantic cache performance
- Token cost: per-model USD spend per hour
- Circuit breaker state: CLOSED/OPEN/HALF_OPEN per model
- Request throughput
- Error rate by endpoint
- Worker throughput

Prometheus scrapes the `/metrics` endpoint (requires `OTEL_ENABLED=true`).

---

## Implementation Timeline

### Phase 1 — Foundation (Week 1-2)
- Deploy Docker Compose stack locally or on Render
- Configure API keys (ANTHROPIC_API_KEY, GEMINI_API_KEY)
- Upload 50-100 representative documents
- Validate classification accuracy for your document types
- Tune extraction schemas for your specific fields

### Phase 2 — Integration (Week 2-3)
- Connect webhook endpoint to receive extracted records
- Integrate search API into existing tools
- Configure review queue workflow
- Enable guardrails (`GUARDRAILS_ENABLED=true`) if processing sensitive data

### Phase 3 — Production (Week 3-4)
- Migrate to AWS Terraform or K8s for production infrastructure
- Set up Grafana monitoring and alerts
- Configure `DATA_RETENTION_DAYS` per retention policy
- Establish review queue SLA (target: < 24hr review cycle)
- Run golden eval CI gate to confirm accuracy on your document types

### Phase 4 — Optimization (Ongoing)
- Review human corrections weekly, export DPO dataset monthly
- A/B test model updates using `model_ab_test.py`
- Monitor cache hit rate; warm cache with common queries
- Tune confidence thresholds per document type

---

## FAQ for IT Buyers

**What document formats are supported?**
PDF (text-layer and scanned/OCR), images (PNG, JPEG, TIFF), email (EML/MSG with attachments). DOCX support via conversion before upload.

**Where is data stored?**
All documents and extracted records stay in your infrastructure. The only external calls are to the Claude API (Anthropic) and Gemini embedding API (Google). No document content is stored by either provider beyond the API call window.

**Can it run air-gapped?**
The extraction pipeline requires Claude API access. For air-gapped requirements, self-hosted models can be substituted by swapping `EXTRACTION_MODELS` to point at a local Ollama or vLLM endpoint. The rest of the stack runs on-premises.

**How is access controlled?**
API key authentication on all endpoints. Admin keys can create and revoke other keys. Standard keys can read and write records but cannot manage keys. Per-key rate limiting is enforced via Redis sliding window.

**What happens when the AI makes a mistake?**
Low-confidence extractions are routed to the human review queue automatically. Reviewers correct and approve records. All corrections are logged to the audit trail. Correction data can be exported as a DPO training dataset (`finetune_exporter.py`) to improve future extractions.

**What is the extraction accuracy?**
94.6% on the 28-fixture golden eval suite, including 12 adversarial cases. Accuracy on your specific document types will vary. Phase 1 of the implementation includes tuning and validation against a sample of your own documents.

**How does it handle sensitive documents?**
The PII detection pipeline scans all extraction output for SSNs, credit cards, phone numbers, and email addresses. Records containing PII are auto-flagged for review. PII is redacted before sending data to external observability services (Langfuse, LangSmith). See `docs/COMPLIANCE.md` for HIPAA and GDPR details.

**Can it handle documents in languages other than English?**
Claude handles multilingual extraction well. The BM25 keyword search is language-agnostic. Semantic search quality depends on Gemini's multilingual embedding support (strong for major European languages, variable for others). The eval suite currently covers English-language documents only.

**What is the throughput capacity?**
On the AWS Terraform stack (db.t3.micro + cache.t3.micro + EC2 t3.small): ~1,000 documents/day. The worker autoscaler handles burst processing. For 10,000+ documents/day, scale the EC2 instance class and increase RDS allocated storage. The API and Worker components are stateless and scale horizontally.

**What does integration look like for our existing systems?**
The primary integration point is a webhook endpoint on your side. DocExtract POSTs extracted records as JSON to your configured URL with HMAC signature verification. Alternatively, poll the search and records API. The MCP server (`mcp_server.py`) enables direct integration with Claude Desktop and compatible AI tools.
