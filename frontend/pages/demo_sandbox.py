"""Interactive demo sandbox — works without API keys using cached results."""
from __future__ import annotations

import os
import streamlit as st
from frontend.demo_mode import (
    load_demo_extraction,
    load_demo_search,
    load_demo_eval,
    list_demo_doc_types,
)


def show() -> None:
    st.title("Try DocExtract — Live Demo")
    st.info(
        "This sandbox uses pre-cached results so you can explore the full pipeline "
        "without uploading real documents or API credentials.",
        icon="ℹ️",
    )

    tab_extract, tab_search, tab_eval = st.tabs(
        ["Document Extraction", "Semantic Search", "Evaluation Scores"]
    )

    # --- Extraction tab ---
    with tab_extract:
        st.subheader("Document Extraction")
        doc_type = st.selectbox(
            "Select document type",
            list_demo_doc_types(),
            format_func=str.title,
        )
        if st.button("Extract Document", type="primary"):
            with st.spinner("Extracting…"):
                result = load_demo_extraction(doc_type)
            confidence = result.get("confidence", 0)
            st.success(f"Extracted **{result['document_type'].title()}** — confidence {confidence:.0%}")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Extracted Fields**")
                for key, value in result["extracted_data"].items():
                    if not isinstance(value, list):
                        st.text(f"{key.replace('_', ' ').title()}: {value}")
                    else:
                        st.text(f"{key.replace('_', ' ').title()}: {len(value)} items")
            with col2:
                st.markdown("**Field Confidence**")
                for field, score in result["field_confidence"].items():
                    color = "🟢" if score >= 0.90 else "🟡" if score >= 0.75 else "🔴"
                    st.text(f"{color} {field.replace('_', ' ').title()}: {score:.0%}")
            st.caption(f"Processing time: {result['processing_time_ms']} ms")

    # --- Search tab ---
    with tab_search:
        st.subheader("Hybrid Semantic Search")
        query = st.text_input(
            "Search query",
            value="What is the total amount due on the invoice?",
        )
        if st.button("Search", type="primary"):
            with st.spinner("Searching…"):
                result = load_demo_search()
            st.caption(
                f"Retrieval mode: **{result['retrieval_mode']}** — "
                f"latency: {result['latency_ms']} ms"
            )
            for i, r in enumerate(result["results"], 1):
                with st.expander(f"Result {i} — score {r['score']:.2f} ({r['source']})"):
                    st.write(r["content"])
                    st.caption(f"Document: {r['doc_id']} | Chunk: {r['chunk_id']}")

    # --- Eval tab ---
    with tab_eval:
        st.subheader("RAGAS Evaluation Scores")
        result = load_demo_eval()
        summary = result["summary"]
        st.caption(f"Run: {result['run_id']} — {result['fixtures_evaluated']} fixtures evaluated")
        cols = st.columns(4)
        metrics = [
            ("Context Recall", "context_recall"),
            ("Faithfulness", "faithfulness"),
            ("Answer Relevancy", "answer_relevancy"),
            ("Overall", "overall"),
        ]
        for col, (label, key) in zip(cols, metrics):
            score = summary[key]
            delta = "✓ Pass" if summary["passed"] else "✗ Fail"
            col.metric(label, f"{score:.0%}", delta if key == "overall" else None)
        if not summary["regression_detected"]:
            st.success("No regression detected — all 16 golden fixtures within threshold.")
        else:
            st.error("Regression detected — CI gate would block this merge.")
