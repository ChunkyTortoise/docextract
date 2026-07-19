"""Architecture diagram page (Mermaid via st.markdown)."""
import streamlit as st


def show() -> None:
    st.title("Architecture Overview")
    st.caption("DocExtract AI — eval-gated document intelligence")

    st.markdown("""
```mermaid
graph TD
    A[PDF / Image Upload] --> B[FastAPI Ingestion]
    B --> C[ARQ Worker]
    C --> D[Classify + Two-pass Extract]
    D --> E[Pydantic Validator]
    E --> F[(pgvector HNSW)]
    E --> G[Streamlit / API Client]

    F --> H{Retrieval}
    H -->|vector / BM25 / hybrid| I[Ranked Chunks]
    I --> J[Agentic RAG - ReAct Loop]
    J --> G

    subgraph Offline CI — not on request path
        K[28-case offline replay]
        L[eval-gate.yml]
        M[(baseline.json)]
        K --> L
        L --> M
    end

    subgraph Observability
        N[Langfuse traces]
        O[Prometheus /metrics]
    end

    C --> N
    J --> N
    B --> O
```
""")

    st.subheader("Key Design Decisions")
    cols = st.columns(3)
    with cols[0]:
        st.metric("Eval gate", "28 fixtures", "offline CI replay")
        st.caption("Merge-safe accuracy signal; not inline on upload requests")
    with cols[1]:
        st.metric("Agentic RAG", "ReAct loop", "Think → Act → Observe")
        st.caption("Primary search path; streams reasoning over SSE")
    with cols[2]:
        st.metric("Test suite", "1,354 collected", "80% coverage gate")
        st.caption("Langfuse primary for live trace debugging")

    st.caption(
        "GraphRAG (opt-in, regex entity graph, file-backed) and semantic cache "
        "(implemented, default-off, not on extraction hot path) are documented in the README footnotes."
    )
