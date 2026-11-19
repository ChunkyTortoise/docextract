"""Streamlit Cloud entry point: demo mode (no API keys required).

Deploy to Streamlit Cloud:
  1. Fork or connect ChunkyTortoise/docextract
  2. Set Main file path: streamlit_demo.py
  3. No secrets needed: demo data is pre-cached in frontend/demo_data/
"""

from __future__ import annotations

import os
import sys

# Ensure project root is on the path so `frontend.*` imports resolve
sys.path.insert(0, os.path.dirname(__file__))

# Force demo mode before any frontend imports
os.environ["DEMO_MODE"] = "true"

import streamlit as st

from frontend.demo_result import apply_demo_styles
from frontend.pages.demo_sandbox import show

st.set_page_config(
    page_title="DocExtract AI | Fixture explorer",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Scope the standalone fixture shell without changing other product pages.
with st.container(key="fixture-explorer"):
    apply_demo_styles()
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
        st.link_button(
            "Product API reference",
            "https://github.com/ChunkyTortoise/docextract/blob/main/docs/productization_api.md",
        )

    st.divider()
    st.caption(
        "This demo uses pre-cached extraction results. "
        "Run the offline explorer with `python -m streamlit run streamlit_demo.py` "
        "or deploy the full stack via `docker compose up`. "
        "Source: [github.com/ChunkyTortoise/docextract](https://github.com/ChunkyTortoise/docextract)"
    )
