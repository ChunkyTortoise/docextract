"""Interactive demo sandbox — works without API keys using cached results."""
from __future__ import annotations

import os
import streamlit as st
from frontend.demo_mode import (
    load_demo_extraction,
    load_demo_search,
    load_demo_eval,
    load_demo_agent_trace,
    load_demo_cost,
    list_demo_doc_types,
)


def show() -> None:
    st.title("Try DocExtract — Live Demo")
    st.info(
        "This sandbox uses pre-cached results so you can explore the full pipeline "
        "without uploading real documents or API credentials.",
        icon="ℹ️",
    )

    tab_extract, tab_search, tab_eval, tab_agent, tab_cost = st.tabs(
        ["Document Extraction", "Semantic Search", "Evaluation Scores", "Agent Trace", "Cost Analysis"]
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
            delta = "Pass" if summary["passed"] else "Fail"
            col.metric(label, f"{score:.0%}", delta if key == "overall" else None)
        if not result.get("regression_detected", False):
            st.success("No regression detected — all golden fixtures within threshold.")
        else:
            st.error("Regression detected — CI gate would block this merge.")

    # --- Agent Trace tab ---
    with tab_agent:
        st.subheader("Agentic RAG — ReAct Trace")
        trace = load_demo_agent_trace()

        st.caption(
            f"Question: *{trace['question']}* — "
            f"{trace['iterations']} iterations, "
            f"tools: {', '.join(trace['tools_used'])}, "
            f"confidence: {trace['confidence']:.0%}"
        )

        # KPI row
        kpi_cols = st.columns(4)
        kpi_cols[0].metric("Iterations", trace["iterations"])
        kpi_cols[1].metric("Final Confidence", f"{trace['confidence']:.0%}")
        kpi_cols[2].metric("Tools Used", len(trace["tools_used"]))
        kpi_cols[3].metric("Sources", len(trace["sources"]))

        # Reasoning steps
        for step in trace["reasoning_trace"]:
            with st.expander(
                f"Step {step['step']}: {step['action']} — confidence {step['confidence']:.0%}",
                expanded=(step["step"] == 1),
            ):
                st.markdown(f"**Think:** {step['thought']}")
                st.code(f"Action: {step['action']}({step['action_input']})", language="python")
                st.markdown(f"**Observe:** {step['observation']}")

                # Confidence bar
                st.progress(step["confidence"], text=f"Confidence: {step['confidence']:.0%}")

        # Final answer
        st.divider()
        st.markdown("**Final Answer**")
        st.write(trace["answer"])
        if trace["sources"]:
            st.markdown("**Sources**")
            for src in trace["sources"]:
                st.caption(f"[{src['doc_id']}] score={src['score']:.2f}: {src['content'][:200]}...")

    # --- Cost Analysis tab ---
    with tab_cost:
        st.subheader("Cost & Model Routing")
        cost = load_demo_cost()
        summary = cost["summary"]

        # KPI row
        kpi_cols = st.columns(4)
        kpi_cols[0].metric("Total Requests", f"{summary['total_requests']:,}")
        kpi_cols[1].metric("Total Cost", f"${summary['total_cost_usd']:.2f}")
        kpi_cols[2].metric("Cache Hit Rate", f"{summary['cache_hit_rate']:.0%}")
        kpi_cols[3].metric(
            "Cache Savings",
            f"${summary['cache_savings_usd']:.2f}",
            delta=f"-{summary['cache_savings_usd'] / (summary['total_cost_usd'] + summary['cache_savings_usd']) * 100:.0f}% cost avoided",
        )

        st.caption(f"Period: last {summary['period_hours']} hours")

        # Cost by model table
        st.markdown("**Cost by Model & Operation**")
        model_data = cost["by_model"]
        col_model, col_op, col_req, col_cost, col_lat, col_conf = st.columns(6)
        col_model.markdown("**Model**")
        col_op.markdown("**Operation**")
        col_req.markdown("**Requests**")
        col_cost.markdown("**Total Cost**")
        col_lat.markdown("**Avg Latency**")
        col_conf.markdown("**Avg Confidence**")

        for m in model_data:
            col_model, col_op, col_req, col_cost, col_lat, col_conf = st.columns(6)
            col_model.text(m["model"].split("-")[1].title())
            col_op.text(m["operation"])
            col_req.text(f"{m['requests']:,}")
            col_cost.text(f"${m['total_cost']:.2f}")
            col_lat.text(f"{m['avg_latency_ms']}ms")
            col_conf.text(f"{m['avg_confidence']:.1%}")

        # A/B test result
        st.divider()
        ab = cost["ab_test"]
        st.markdown("**Model A/B Test Result**")
        st.caption(f"Test: {ab['name']} — Status: **{ab['status']}** (p={ab['p_value']:.3f})")

        ab_cols = st.columns(2)
        with ab_cols[0]:
            st.markdown(f"**Variant A: {ab['variant_a']['model']}**")
            st.text(f"Accuracy: {ab['variant_a']['accuracy']:.1%}")
            st.text(f"Avg cost: ${ab['variant_a']['avg_cost']:.4f}")
            st.text(f"n = {ab['variant_a']['n']}")
        with ab_cols[1]:
            st.markdown(f"**Variant B: {ab['variant_b']['model']}**")
            st.text(f"Accuracy: {ab['variant_b']['accuracy']:.1%}")
            st.text(f"Avg cost: ${ab['variant_b']['avg_cost']:.4f}")
            st.text(f"n = {ab['variant_b']['n']}")

        st.info(ab["conclusion"], icon="ℹ️")
