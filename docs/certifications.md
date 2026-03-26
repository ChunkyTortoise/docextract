# Certifications Applied

Each feature maps directly to a professional certification -- this is applied knowledge, not just coursework.

| Certification | Hours | Feature Demonstrated | Code Location |
|---|---|---|---|
| IBM Generative AI Engineering (PyTorch, LangChain, HuggingFace) | 144h | Two-pass Claude extraction with `tool_use` correction; structured output Pydantic schemas | [`app/services/claude_extractor.py`](../app/services/claude_extractor.py) |
| IBM RAG and Agentic AI | 24h | ReAct agentic RAG with 5 retrieval tools; pgvector HNSW; hybrid BM25+vector RRF | [`app/services/agentic_rag.py`](../app/services/agentic_rag.py), [`app/services/rag_tools.py`](../app/services/rag_tools.py) |
| Duke LLMOps Specialization | 48h | Prompt versioning (semver-tagged); golden eval CI gate (2% regression tolerance); model A/B testing with z-test | [`app/services/prompt_registry.py`](../app/services/prompt_registry.py), [`app/services/model_ab_test.py`](../app/services/model_ab_test.py) |
| DeepLearning.AI Deep Learning Specialization | 120h | 768-dim Gemini embedding model; HNSW index design; semantic cache with cosine similarity lookup | [`app/services/embedder.py`](../app/services/embedder.py), [`app/services/semantic_cache.py`](../app/services/semantic_cache.py) |
| Microsoft AI & ML Engineering | 75h | Per-model circuit breakers (CLOSED/OPEN/HALF_OPEN); confidence thresholding; MLOps deployment patterns | [`app/services/circuit_breaker.py`](../app/services/circuit_breaker.py), [`app/services/model_router.py`](../app/services/model_router.py) |
| Vanderbilt Generative AI Strategic Leader | 40h | ReAct think-act-observe loop; autonomous tool selection; confidence-gated iteration; A/B tested extraction prompts; hallucination reduction via grounding | [`app/services/agentic_rag.py`](../app/services/agentic_rag.py), [`app/services/prompt_registry.py`](../app/services/prompt_registry.py) |
| Google Cloud GenAI Leader | 25h | Multi-provider GenAI orchestration (Claude + Gemini); model selection strategy; GenAI-powered document classification and extraction | [`app/services/model_router.py`](../app/services/model_router.py), [`app/services/classifier.py`](../app/services/classifier.py) |
| IBM BI Analyst | 141h | 14-page Streamlit dashboard; ROI tracking; executive report generation | [`frontend/pages/`](../frontend/pages/) |
| Google Data Analytics | 181h | Cost dashboard; extraction analytics; per-model latency and token tracking | [`frontend/pages/cost_dashboard.py`](../frontend/pages/cost_dashboard.py) |
| Google Advanced Data Analytics | 200h | RAGAS metrics (context recall, faithfulness, answer relevancy); Brier score calibration; statistical eval | [`app/services/ragas_evaluator.py`](../app/services/ragas_evaluator.py), [`tests/evaluation/`](../tests/evaluation/) |
| Microsoft Data Visualization | 87h | Plotly charts; confidence distribution histograms; cost breakdowns by model and document type | [`frontend/pages/cost_dashboard.py`](../frontend/pages/cost_dashboard.py), [`frontend/pages/evaluation.py`](../frontend/pages/evaluation.py) |
| Python for Everybody (U. Michigan) | 60h | Python foundations applied across entire codebase: FastAPI API, SQLAlchemy async models, ARQ worker, dataclasses, type hints, httpx async HTTP client | [`app/`](../app/), [`worker/`](../worker/), [`mcp_server.py`](../mcp_server.py) |
| Linux Foundation OSS Development | 60h | GitHub Actions CI (bandit, ruff, mypy, eval gates, Docker builds, GHCR publishing); PR templates, CODEOWNERS, dependabot; Makefile automation; multi-stage Dockerfiles; K8s/Kustomize manifests; AWS Terraform IaC; bash scripts | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml), [`Makefile`](../Makefile), [`deploy/k8s/`](../deploy/k8s/), [`deploy/aws/main.tf`](../deploy/aws/main.tf) |
| Anthropic Claude Code in Action | 3h | MCP tool server exposing extract_document and search_records tools; Claude `tool_use` for two-pass extraction with correction tools and document classification; `.claude/CLAUDE.md` project config | [`mcp_server.py`](../mcp_server.py), [`app/services/claude_extractor.py`](../app/services/claude_extractor.py), [`app/services/classifier.py`](../app/services/classifier.py) |

**Total verified training hours applied:** 1,208h across 14 certifications from IBM, DeepLearning.AI, Duke, Vanderbilt, Google, Microsoft, U. Michigan, Linux Foundation, and Anthropic.

---

**Unmapped certifications (not applied in this repo):** 7 certifications are shown on the portfolio but have no direct code mapping here -- Meta Social Media Marketing, Google Digital Marketing, Google BI, Vanderbilt ChatGPT Personal Automation, DeepLearning.AI AI For Everyone, Microsoft GenAI for Data Analysis, and Microsoft AI-Enhanced Data Analysis. These are either platform-specific, executive/strategic, or domain-specific credentials that don't correspond to implemented features in this repository.
