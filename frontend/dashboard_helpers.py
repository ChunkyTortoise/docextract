"""Shared helpers for Evaluation / Cost / Quality Streamlit dashboards."""
from __future__ import annotations

import os

import streamlit as st

_DEMO_TRUTHY = frozenset({"1", "true", "yes"})

SYNTHETIC_SEED_LABEL = (
    "Synthetic seed — not measured production telemetry. "
    "Connect the API and run extraction jobs to populate live metrics."
)


def is_demo_mode() -> bool:
    return os.environ.get("DEMO_MODE", "").lower() in _DEMO_TRUTHY


def render_demo_mode_eval_proof_panel(page_name: str) -> None:
    """Point reviewers at README eval proof instead of synthetic charts."""
    st.info(
        f"**{page_name}** is hidden in demo mode because it would show synthetic seed "
        "data, not measured telemetry.\n\n"
        "For hireability proof without API keys, see the **Eval gate** section in the "
        "[README](https://github.com/ChunkyTortoise/docextract#eval-gate): "
        "28-case offline CI replay (95.5% weighted field accuracy), "
        "200-case versioned corpus, and [eval-methodology.md]"
        "(https://github.com/ChunkyTortoise/docextract/blob/main/docs/eval-methodology.md).\n\n"
        "To populate live charts, deploy with `DEMO_MODE` unset, API keys configured, "
        "and Langfuse enabled per [langfuse-demo-trace.md]"
        "(https://github.com/ChunkyTortoise/docextract/blob/main/docs/runbooks/langfuse-demo-trace.md).",
        icon="📊",
    )


def guard_demo_mode_dashboard(page_name: str) -> bool:
    """Return True when render should stop (demo mode — no synthetic charts)."""
    if is_demo_mode():
        render_demo_mode_eval_proof_panel(page_name)
        return True
    return False


def show_synthetic_seed_banner(extra: str = "") -> None:
    """Label mock/seed data clearly when the API returned empty."""
    message = SYNTHETIC_SEED_LABEL
    if extra:
        message = f"{message} {extra}"
    st.info(message, icon="🔬")
