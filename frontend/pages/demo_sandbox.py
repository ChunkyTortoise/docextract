"""Interactive fixture explorer. No model, retrieval, or billing calls."""

from __future__ import annotations

import streamlit as st

from frontend.demo_mode import (
    list_demo_doc_types,
    load_demo_agent_trace,
    load_demo_cost,
    load_demo_eval,
    load_demo_extraction,
    load_demo_search,
)


def show() -> None:
    st.title("Document to data.")
    st.caption("DOCEXTRACT / FIXTURE EXPLORER")
    st.info("Fixture mode: inspect stored JSON outputs. No upload, model call, or database.")
    extract_tab, search_tab, trace_tab, eval_tab, cost_tab = st.tabs(
        ["Fields", "Search", "Trace", "Eval", "Cost"]
    )

    with extract_tab:
        doc_type = st.selectbox("Document sample", list_demo_doc_types(), format_func=str.title)
        result = load_demo_extraction(doc_type)
        st.subheader(f"{result['document_type'].title()} / structured result")
        st.caption(
            f"Source: frontend/demo_data/{doc_type}_sample.json | "
            f"Stored sample: {result['filename']}"
        )
        st.table(
            [
                {
                    "Field": key.replace("_", " ").title(),
                    "Stored value": str(value)
                    if not isinstance(value, list)
                    else f"{len(value)} entries (see JSON)",
                    "Sample confidence": (
                        f"{result['field_confidence'][key]:.0%}"
                        if key in result["field_confidence"]
                        else "Not supplied"
                    ),
                }
                for key in dict.fromkeys([*result["field_confidence"], *result["extracted_data"]])
                for value in [result["extracted_data"][key]]
            ],
        )
        st.caption(
            "These are stored outputs, not an extraction of a document in this session. "
            "Confidence values are not calibrated accuracy or the offline replay score."
        )
        with st.expander("Inspect the complete fixture JSON"):
            st.json(result)
        st.markdown(
            "**Reproduce the separate offline evaluation:** "
            "`python scripts/eval_offline_replay.py --floor 0.85`"
        )

    with search_tab:
        sample = load_demo_search()
        st.subheader("Replay a stored search result")
        st.caption(
            "This replays search_sample.json for its original question. "
            "It does not accept arbitrary queries or search a running database."
        )
        st.text_input("Recorded question", value=sample["query"], disabled=True)
        if st.button("Replay stored search", type="primary"):
            st.caption(
                f"Stored mode: {sample['retrieval_mode']} | "
                f"Illustrative latency: {sample['latency_ms']} ms"
            )
            for index, result in enumerate(sample["results"], 1):
                with st.expander(
                    f"Result {index}: {result['source']} / stored score {result['score']:.2f}",
                    expanded=True,
                ):
                    st.text(result["content"])
                    st.caption(f"Document: {result['doc_id']} | Chunk: {result['chunk_id']}")

    with trace_tab:
        trace = load_demo_agent_trace()
        st.subheader("Illustrative agent trace")
        st.caption(
            "Static agent_trace_demo.json. These steps and confidence values are fixture data, "
            "not a trace captured from this session."
        )
        st.write(trace["question"])
        for step in trace["reasoning_trace"]:
            with st.expander(f"Step {step['step']}: {step['action']}", expanded=step["step"] == 1):
                st.markdown("**Stored reasoning**")
                st.write(step["thought"])
                st.code(f"{step['action']}({step['action_input']})", language="python")
                st.text(step["observation"])
        st.markdown("**Stored answer**")
        st.text(trace["answer"])

    with eval_tab:
        result = load_demo_eval()
        st.subheader("Illustrative evaluation display")
        st.warning(
            "Seeded UI sample, not measured RAGAS performance or the 28-fixture offline replay. "
            "Do not use these sample scores as portfolio metrics."
        )
        st.json(result)
        st.markdown(
            "[Measured offline replay and limitations]"
            "(https://github.com/ChunkyTortoise/docextract/blob/main/docs/retrieval-extraction-evidence.md)"
        )

    with cost_tab:
        st.subheader("Illustrative cost display")
        st.warning(
            "Seeded UI sample, not metered spend, measured savings, or a completed A/B experiment. "
            "No provider is called by this page."
        )
        st.json(load_demo_cost())
