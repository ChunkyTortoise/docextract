"""Streamlit Cloud entry point: demo mode (no API keys required).

Deploy to Streamlit Cloud:
  1. Fork or connect ChunkyTortoise/docextract
  2. Set Main file path: streamlit_demo.py
  3. No secrets needed: demo data is pre-cached in frontend/demo_data/
"""

from __future__ import annotations

import logging
import os
import sys

# Ensure project root is on the path so `frontend.*` imports resolve
sys.path.insert(0, os.path.dirname(__file__))

# Force demo mode before any frontend imports
os.environ["DEMO_MODE"] = "true"

import streamlit as st

from frontend.pages.demo_sandbox import show

st.set_page_config(
    page_title="DocExtract AI | Fixture explorer",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Apply the project theme if available
try:
    from frontend.theme import apply_theme

    apply_theme()
except ImportError:
    logging.getLogger(__name__).warning("Optional demo theme could not be imported", exc_info=True)

st.markdown(
    """<style>
    .block-container { padding-top: 1rem; }
    @media (max-width: 600px) {
        h1 { font-size: 1.8rem !important; }
        h3 { font-size: 1.25rem !important; }
    }
    </style>""",
    unsafe_allow_html=True,
)

# Run the demo sandbox
show()

col_links = st.columns(3)
with col_links[0]:
    st.link_button("GitHub", "https://github.com/ChunkyTortoise/docextract")
with col_links[1]:
    st.link_button(
        "Case Study", "https://github.com/ChunkyTortoise/docextract/blob/main/CASE_STUDY.md"
    )
with col_links[2]:
    st.link_button("Product API reference",
        "https://github.com/ChunkyTortoise/docextract/blob/main/docs/productization_api.md")


st.divider()
st.caption(
    "This demo uses pre-cached extraction results. "
    "Run the offline explorer with `python -m streamlit run streamlit_demo.py` "
    "or deploy the full stack via `docker compose up`. "
    "Source: [github.com/ChunkyTortoise/docextract](https://github.com/ChunkyTortoise/docextract)"
)
