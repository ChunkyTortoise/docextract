"""Agent Trace Viewer — visualize the agentic RAG ReAct reasoning loop."""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st
from frontend.theme import PLOTLY_DARK


def render() -> None:
    st.title("Agent Trace Viewer")
    st.caption("Visualize Think \u2192 Act \u2192 Observe reasoning for each agentic RAG query")

    # Query input
    with st.form("agent_trace_form"):
        question = st.text_input(
            "Question",
            value="What is the total amount due on the invoice?",
            help="Ask a question about your documents",
        )
        max_iter = st.slider("Max iterations", min_value=1, max_value=5, value=3)
        submitted = st.form_submit_button("Run Agent", type="primary")

    result: dict | None = None
    if submitted:
        result = _load_trace(question, max_iter)
    else:
        result = _load_trace(None, max_iter)

    if result is None:
        st.info("Enter a question above and click 'Run Agent' to see the reasoning trace.")
        return

    _render_trace(result)


def _load_trace(question: str | None, max_iter: int) -> dict | None:
    """Try live API; fall back to demo data."""
    if question:
        try:
            import frontend.api_client as api
            return api.agent_search(question, max_iterations=max_iter)
        except Exception:
            pass  # fall through to demo data

    # Demo data fallback
    demo_file = Path(__file__).parent.parent / "demo_data" / "agent_trace_demo.json"
    if demo_file.exists():
        return json.loads(demo_file.read_text())
    return None


def _render_trace(result: dict) -> None:
    """Render a full AgenticRAGResult as a visual trace."""
    trace = result.get("reasoning_trace", [])
    tools_used = result.get("tools_used", [])
    confidence = result.get("confidence", 0.0)
    iterations = result.get("iterations", len(trace))
    sources = result.get("sources", [])

    # KPI row
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Iterations", iterations, help="ReAct steps taken")
    col2.metric("Final Confidence", f"{confidence:.0%}", help="Agent's self-assessed confidence")
    col3.metric("Tools Used", len(set(tools_used)), help="Distinct retrieval tools invoked")
    col4.metric("Sources Found", len(sources), help="Context passages returned")

    st.divider()

    # Reasoning trace
    if trace:
        st.subheader("Reasoning Trace")
        st.caption(
            "Each step: what the agent thought, which tool it used, "
            "what it observed, and its confidence"
        )

        confidences: list[float] = []
        steps: list[int] = []

        for step_data in trace:
            step_num = step_data.get("step", 0)
            thought = step_data.get("thought", "")
            action = step_data.get("action", "")
            action_input = step_data.get("action_input") or {}
            observation = step_data.get("observation", "")
            step_confidence = step_data.get("confidence") or 0.0

            confidences.append(float(step_confidence))
            steps.append(step_num)

            with st.expander(
                f"Step {step_num} \u2014 {action or 'reason'} (confidence {step_confidence:.0%})",
                expanded=(step_num == 1),
            ):
                t_col, a_col = st.columns(2)
                with t_col:
                    st.markdown("**Think**")
                    st.info(thought or "\u2014")
                with a_col:
                    st.markdown("**Act**")
                    if action:
                        query_str = action_input.get("query", "") if isinstance(action_input, dict) else str(action_input)
                        if query_str:
                            st.code(f"{action}(query={query_str!r})")
                        else:
                            st.code(action)
                    else:
                        st.caption("No action")
                st.markdown("**Observe**")
                st.success(observation or "\u2014")
                st.progress(float(step_confidence), text=f"Confidence: {step_confidence:.0%}")

        # Confidence trajectory (only when >1 step)
        if len(confidences) > 1:
            st.subheader("Confidence Trajectory")
            try:
                import plotly.graph_objects as go  # type: ignore[import]

                fig = go.Figure()
                fig.add_trace(
                    go.Scatter(
                        x=steps,
                        y=confidences,
                        mode="lines+markers",
                        name="Confidence",
                        line=dict(color="#22c55e", width=2),
                        marker=dict(size=8),
                    )
                )
                fig.add_hline(
                    y=0.8,
                    line_dash="dash",
                    line_color="orange",
                    annotation_text="Threshold (0.8)",
                )
                fig.update_layout(
                    xaxis_title="Step",
                    yaxis_title="Confidence",
                    yaxis=dict(range=[0, 1.05]),
                    height=300,
                    margin=dict(l=0, r=0, t=20, b=0),
                    **PLOTLY_DARK,
                )
                st.plotly_chart(fig, use_container_width=True)
            except ImportError:
                st.line_chart({s: c for s, c in zip(steps, confidences)})

    # Final answer
    st.divider()
    st.subheader("Answer")
    answer = result.get("answer", "")
    if answer:
        st.success(answer)
    else:
        st.warning("No answer generated")

    # Sources
    if sources:
        st.subheader("Sources")
        for i, src in enumerate(sources, 1):
            with st.expander(f"Source {i} \u2014 score {src.get('score', 0):.2f}"):
                st.write(src.get("content", ""))
                st.caption(
                    f"Document: {src.get('doc_id', '')} | "
                    f"Chunk: {src.get('chunk_id', '')}"
                )
