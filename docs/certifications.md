# Certifications Applied

Each feature maps directly to a professional certification -- this is applied knowledge, not just coursework.

| Certification | Hours | Feature Demonstrated | Code Location |
|---|---|---|---|
| IBM Generative AI Engineering (PyTorch, LangChain, HuggingFace) | 144h | Two-pass Claude extraction with `tool_use` correction; structured output Pydantic schemas | [`app/services/claude_extractor.py`](../app/services/claude_extractor.py) |
| IBM RAG and Agentic AI | 24h | ReAct agentic RAG with 5 retrieval tools; pgvector HNSW; hybrid BM25+vector RRF | [`app/services/agentic_rag.py`](../app/services/agentic_rag.py), [`app/services/rag_tools.py`](../app/services/rag_tools.py) |
| Duke LLMOps Specialization | 48h | Prompt versioning (semver-tagged); golden eval CI gate (2% regression tolerance); model A/B testing with z-test | [`app/services/prompt_registry.py`](../app/services/prompt_registry.py), [`app/services/model_ab_test.py`](../app/services/model_ab_test.py) |
| DeepLearning.AI Deep Learning Specialization | 120h | 768-dim Gemini embedding model; HNSW index design; semantic cache with cosine similarity lookup | [`app/services/embedder.py`](../app/services/embedder.py), [`app/services/semantic_cache.py`](../app/services/semantic_cache.py) |
| Microsoft AI & ML Engineering | 75h | Per-model circuit breakers (CLOSED/OPEN/HALF_OPEN); confidence thresholding; MLOps deployment patterns | [`app/services/circuit_breaker.py`](../app/services/circuit_breaker.py), [`app/services/model_router.py`](../app/services/model_router.py) |
| Vanderbilt Agentic AI | 40h | ReAct think-act-observe loop; autonomous tool selection per query; confidence-gated iteration | [`app/services/agentic_rag.py`](../app/services/agentic_rag.py) |
| Vanderbilt Prompt Engineering | 18h | A/B tested extraction prompts; system instruction tuning; hallucination reduction via grounding | [`app/services/prompt_registry.py`](../app/services/prompt_registry.py) |
| Google Cloud GenAI Leader | 25h | Kubernetes/Kustomize + HPA; AWS Terraform IaC (RDS + ElastiCache + ECR); multi-stage Docker builds | [`deploy/k8s/`](../deploy/k8s/), [`deploy/aws/main.tf`](../deploy/aws/main.tf) |
| IBM BI Analyst | 141h | 14-page Streamlit dashboard; ROI tracking; executive report generation | [`frontend/pages/`](../frontend/pages/) |
| Google Data Analytics | 181h | Cost dashboard; extraction analytics; per-model latency and token tracking | [`frontend/pages/cost_dashboard.py`](../frontend/pages/cost_dashboard.py) |
| Google Advanced Data Analytics | 200h | RAGAS metrics (context recall, faithfulness, answer relevancy); Brier score calibration; statistical eval | [`app/services/ragas_evaluator.py`](../app/services/ragas_evaluator.py), [`tests/evaluation/`](../tests/evaluation/) |
| Microsoft Data Visualization | 87h | Plotly charts; confidence distribution histograms; cost breakdowns by model and document type | [`frontend/pages/cost_dashboard.py`](../frontend/pages/cost_dashboard.py), [`frontend/pages/evaluation.py`](../frontend/pages/evaluation.py) |

**Total verified training hours applied:** 1,003h across 12 certifications from IBM, DeepLearning.AI, Duke, Vanderbilt, Google, and Microsoft.
