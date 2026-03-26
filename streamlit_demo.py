"""Streamlit Cloud entry point — demo mode (no API keys required).

Deploy to Streamlit Cloud:
  1. Fork or connect ChunkyTortoise/docextract
  2. Set Main file path: streamlit_demo.py
  3. No secrets needed — demo data is pre-cached in frontend/demo_data/
"""
from __future__ import annotations

import os
import sys

# Ensure project root is on the path so `frontend.*` imports resolve
sys.path.insert(0, os.path.dirname(__file__))

# Force demo mode before any frontend imports
os.environ["DEMO_MODE"] = "true"

import streamlit as st

st.set_page_config(
    page_title="DocExtract AI — Live Demo",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Apply the project theme if available
try:
    from frontend.theme import apply_theme
    apply_theme()
except Exception:
    pass

st.markdown(
    """
    <style>
    .demo-banner {
        background: linear-gradient(135deg, #6366F1 0%, #8B5CF6 100%);
        padding: 1rem 1.5rem;
        border-radius: 0.5rem;
        margin-bottom: 1.5rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="demo-banner">'
    '<strong>DocExtract AI</strong> — Document intelligence with production-grade RAG, '
    'agentic retrieval, and LLMOps. No sign-up required.'
    '</div>',
    unsafe_allow_html=True,
)

col_links = st.columns([1, 1, 1, 1, 4])
with col_links[0]:
    st.link_button("GitHub", "https://github.com/ChunkyTortoise/docextract")
with col_links[1]:
    st.link_button("Case Study", "https://github.com/ChunkyTortoise/docextract/blob/main/CASE_STUDY.md")
with col_links[2]:
    st.link_button("API Docs", "https://github.com/ChunkyTortoise/docextract#api-reference")

st.divider()

# Run the demo sandbox
from frontend.pages.demo_sandbox import show
show()

st.divider()
st.caption(
    "This demo uses pre-cached extraction results. "
    "Self-host with `DEMO_MODE=true streamlit run frontend/app.py` "
    "or deploy the full stack via `docker compose up`. "
    "Source: [github.com/ChunkyTortoise/docextract](https://github.com/ChunkyTortoise/docextract)"
)
