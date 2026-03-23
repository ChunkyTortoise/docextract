"""Architecture diagram page (Mermaid via st.markdown)."""
import streamlit as st


def show() -> None:
    st.title("Architecture Overview")
    st.caption("DocExtract AI — production document intelligence pipeline")

    st.markdown("""
```mermaid
graph TD
    A[PDF / Image Upload] --> B[FastAPI Ingestion Layer]
    B --> C{OCR Engine}
    C -->|Default| D[Claude Vision API]
    C -->|Fallback| E[Tesseract OCR]
    D --> F[Chunker & Preprocessor]
    E --> F
    F --> G[Gemini Embeddings]
    G --> H[(pgvector DB)]
    F --> I[BM25 Index]

    H --> J{Retrieval}
    I --> J
    J -->|Hybrid RRF| K[Ranked Chunks]
    K --> L[Agentic RAG - ReAct Loop]
    L --> M[Claude Extraction]
    M --> N[Pydantic Validator]

    N --> O[RAGAS Eval Pipeline]
    O --> P[LLM-as-Judge]
    P --> Q[(Eval History DB)]

    M --> R[Streamlit Dashboard]
    O --> R
    Q --> R

    subgraph Observability
        S[OpenTelemetry / OTLP]
        T[Prometheus /metrics]
        U[Grafana Dashboard]
        S --> U
        T --> U
    end

    M --> S
    L --> T

    subgraph Deployment
        V[Docker Compose]
        W[K8s - Kustomize + HPA]
        X[AWS RDS + ElastiCache]
    end
```
""")

    st.subheader("Key Design Decisions")
    cols = st.columns(3)
    with cols[0]:
        st.metric("Test Coverage", "850+ tests", "pytest + CI gate")
        st.caption("RAGAS CI blocks merges on quality regression")
    with cols[1]:
        st.metric("Retrieval Modes", "3 strategies", "vector / BM25 / hybrid RRF")
        st.caption("Agentic layer auto-selects based on confidence")
    with cols[2]:
        st.metric("Models Supported", "4", "Sonnet / Haiku / Opus / Gemini")
        st.caption("Circuit breaker with auto-fallback chains")
