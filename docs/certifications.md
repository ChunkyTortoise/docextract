# Certifications Applied

Each entry maps methodology learned to production implementation. References are module-level to remain stable across refactors.

---

## IBM Generative AI Engineering — IBM (144h)
**Methodology learned**: PyTorch model lifecycle, LangChain orchestration, HuggingFace Trainer API, structured LLM output schemas
**Applied in**: `app/services/` — two-pass Claude extraction with `tool_use` correction, Pydantic structured output schemas, QLoRA fine-tuning pipeline
**Production metric**: 94.6% extraction accuracy across 28-fixture adversarial eval suite (including 4 prompt injection fixtures)
**Design decision informed**: Two-pass extraction pattern (classify then extract) reduces hallucination vs single-pass; correction pass uses tool_use to self-repair low-confidence fields

## IBM RAG and Agentic AI — IBM (24h)
**Methodology learned**: Retrieval-Augmented Generation pipeline design, ReAct agent loop, tool-augmented agentic patterns
**Applied in**: `app/services/` — ReAct loop with 5 retrieval tools, pgvector HNSW, hybrid BM25+vector RRF fusion, confidence-gated iteration
**Production metric**: Hybrid retrieval reduces missed citations vs single-vector search (validated across adversarial eval fixtures)
**Design decision informed**: Tool-per-retrieval-strategy pattern enables A/B testing search algorithms without changing the agent loop

## Duke LLMOps Specialization — Duke University (48h)
**Methodology learned**: Prompt lifecycle management, LLM regression testing, model selection criteria, CI/CD for LLM systems
**Applied in**: `app/services/` and `.github/workflows/` — prompt versioning (semver-tagged), golden eval CI gate (2% regression tolerance), model A/B testing with z-test significance
**Production metric**: CI gate blocks deploys when accuracy drops >2% from 94.6% baseline; prompt versions are immutable and auditable
**Design decision informed**: Semver prompt tagging enables reproducible experiment comparisons across training runs and model upgrades

## DeepLearning.AI Deep Learning Specialization — DeepLearning.AI (120h)
**Methodology learned**: Neural network architecture, embedding spaces, attention mechanisms, fine-tuning theory (QLoRA, LoRA, DPO)
**Applied in**: `app/services/` and `scripts/` — 768-dim Gemini embedding model, HNSW index design, semantic cache with cosine similarity, QLoRA Mistral-7B training scripts
**Production metric**: Semantic cache hit rate ~23% on repeated query patterns; adapter trained with r=16, lora_alpha=32 on Mistral-7B-Instruct-v0.2
**Design decision informed**: 768-dim embedding chosen over 384-dim for retrieval precision on technical documents; QLoRA 4-bit quantization fits T4 15GB VRAM

## Microsoft AI & ML Engineering — Microsoft (75h)
**Methodology learned**: Production ML system patterns, reliability engineering for AI systems, MLOps deployment
**Applied in**: `app/services/` — per-model circuit breakers (CLOSED/OPEN/HALF_OPEN), confidence thresholding, fallback routing, cost-per-request tracking
**Production metric**: Circuit breaker auto-falls back Sonnet→Haiku on error threshold; prevents cascading failures under load
**Design decision informed**: State-machine circuit breaker preferred over simple retry — faster recovery, observable state, per-model isolation

## Vanderbilt Generative AI Strategic Leader — Vanderbilt University (40h)
**Methodology learned**: ReAct (Reason+Act) loop design, autonomous agent evaluation, LLM product strategy
**Applied in**: `app/services/` — ReAct think-act-observe loop, autonomous tool selection, A/B tested extraction prompts, hallucination reduction via grounding
**Production metric**: Confidence gating (threshold: 0.85) prevents overconfident extractions from reaching storage
**Design decision informed**: Confidence gating preferred over always-returning results — downstream automation requires trustworthy confidence scores, not just high accuracy

## Google Cloud GenAI Leader — Google Cloud (25h)
**Methodology learned**: Multi-provider GenAI orchestration, model selection tradeoffs, GenAI architecture design
**Applied in**: `app/services/` — multi-provider routing (Claude + Gemini), model selection strategy by document complexity and cost
**Production metric**: Gemini embeddings chosen over OpenAI ada-002 (better cost/quality on document retrieval benchmarks)
**Design decision informed**: Provider-agnostic router interface enables model swaps without application code changes

## IBM BI Analyst — IBM (141h)
**Methodology learned**: Dashboard design, KPI definition, stakeholder reporting, executive data storytelling
**Applied in**: `frontend/pages/` — 14-page Streamlit dashboard with ROI tracking, extraction analytics, and executive report generation
**Production metric**: Dashboard renders in <2s with Streamlit caching; supports real-time cost monitoring per document type
**Design decision informed**: Page-per-analytics-domain structure mirrors BI tool conventions — familiar to non-engineer stakeholders

## Google Data Analytics — Google (181h)
**Methodology learned**: Data pipeline design, operational analytics, cost analysis methodology
**Applied in**: `frontend/pages/` — cost dashboard, extraction analytics, per-model latency and token tracking per request
**Production metric**: Cost tracking to 4 decimal places per API call; per-model breakdown enables cost attribution
**Design decision informed**: Per-request cost tracking baked into worker (not dashboard) — enables alerting without UI dependency

## Google Advanced Data Analytics — Google (200h)
**Methodology learned**: Statistical evaluation, A/B testing methodology, calibration metrics, regression analysis
**Applied in**: `tests/evaluation/` and `app/services/` — RAGAS metrics (context recall, faithfulness, answer relevancy), Brier score calibration curve, z-test for A/B significance
**Production metric**: Brier score 0.12 (well-calibrated confidence); 94.6% accuracy across 28 adversarial fixtures including prompt injection
**Design decision informed**: Brier score required alongside accuracy — confidence calibration matters for downstream automation decisions more than raw accuracy

## Microsoft Data Visualization — Microsoft (87h)
**Methodology learned**: Chart selection principles, interactive visualization design, data-ink ratio
**Applied in**: `frontend/pages/` — Plotly charts, confidence distribution histograms, cost breakdowns by model and document type
**Production metric**: Calibration curve + Brier score histogram renders in <1s on evaluation page
**Design decision informed**: Histogram over table for confidence distributions — visual pattern recognition is faster than tabular scanning for distribution shape

## Python for Everybody — University of Michigan (60h)
**Methodology learned**: Python fundamentals, async patterns, file I/O, HTTP, data structures, type annotations
**Applied in**: `app/`, `worker/`, `mcp_server.py` — FastAPI async routes, SQLAlchemy ORM, ARQ worker, httpx async HTTP client, full type annotation coverage
**Production metric**: 1,183 tests covering entire Python codebase; 87%+ test coverage enforced in CI
**Design decision informed**: Async-first design throughout (FastAPI + asyncpg + ARQ) — blocking I/O would bottleneck document processing under concurrent uploads

## Linux Foundation OSS Development — Linux Foundation (60h)
**Methodology learned**: Git workflows, CI/CD pipeline design, container orchestration, Infrastructure-as-Code
**Applied in**: `.github/workflows/`, `deploy/k8s/`, `deploy/aws/`, `Makefile` — GitHub Actions CI with bandit, ruff, mypy, eval gates, Docker builds; K8s/Kustomize; AWS Terraform (RDS + ElastiCache)
**Production metric**: CI pipeline enforces bandit security scan + mypy type check on every PR; eval gate blocks accuracy regressions
**Design decision informed**: Multi-stage Dockerfiles (build→test→runtime) reduce production image size; GitOps K8s manifests enable reproducible deploys

## Anthropic Claude Code in Action — Anthropic (3h)
**Methodology learned**: Model Context Protocol (MCP) server design, Claude tool_use API patterns, agentic coding workflows
**Applied in**: `mcp_server.py`, `app/services/` — MCP server exposing extract_document and search_records tools; Claude tool_use for two-pass extraction and document classification
**Production metric**: MCP server integrated with .claude/CLAUDE.md — Claude Code agents can query the extraction pipeline directly
**Design decision informed**: MCP interface preferred over custom API wrapper — standard protocol enables any MCP-compatible client to use the pipeline

---

**Applied training total:** 1,208h across 14 certifications from IBM, DeepLearning.AI, Duke, Vanderbilt, Google, Microsoft, U. Michigan, Linux Foundation, and Anthropic.

Additional certifications in data analytics, marketing, and business operations inform domain understanding but are not directly mapped to this codebase.
