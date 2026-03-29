"""Shared theme and CSS injection for DocExtract AI frontend."""

import streamlit as st

_FONTS_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=Space+Mono:ital,wght@0,400;0,700;1,400&"
    "family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600&"
    "family=JetBrains+Mono:wght@400;500&display=swap"
)

_CSS = f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{_FONTS_URL}" rel="stylesheet">
<style>
    /* Fonts */
    html, body, [class*="css"] {{
        font-family: 'DM Sans', sans-serif;
    }}
    h1, h2, h3, h4, h5, h6 {{
        font-family: 'Space Mono', monospace !important;
    }}
    code, pre, .stCode, [data-testid="stCode"] {{
        font-family: 'JetBrains Mono', monospace !important;
    }}

    /* Hide Streamlit chrome */
    #MainMenu, footer, header {{ visibility: hidden; }}
    [data-testid="stToolbar"] {{ display: none; }}

    /* Blueprint cards */
    .glass-card {{
        background: rgba(6, 182, 212, 0.04);
        border: 1px solid rgba(6, 182, 212, 0.12);
        border-left: 2px solid #06B6D4;
        border-radius: 8px;
        padding: 1rem;
    }}

    /* Skeleton shimmer for loading states */
    @keyframes shimmer {{
        0% {{ background-position: -468px 0; }}
        100% {{ background-position: 468px 0; }}
    }}
    .skeleton {{
        background: linear-gradient(
            to right,
            rgba(6, 182, 212, 0.04) 8%,
            rgba(6, 182, 212, 0.10) 18%,
            rgba(6, 182, 212, 0.04) 33%
        );
        background-size: 800px 104px;
        animation: shimmer 1.4s ease-in-out infinite;
        border-radius: 6px;
        height: 1rem;
        margin: 0.4rem 0;
    }}

    /* Metric card accent */
    [data-testid="metric-container"] {{
        background: rgba(6, 182, 212, 0.08);
        border: 1px solid rgba(6, 182, 212, 0.2);
        border-radius: 10px;
        padding: 0.75rem 1rem;
    }}

    /* Sidebar refinement */
    [data-testid="stSidebar"] {{
        background-color: #0D1A1F;
    }}

    /* Blueprint dot-grid background */
    .stApp {{
        background-image: radial-gradient(rgba(6, 182, 212, 0.08) 1px, transparent 1px);
        background-size: 24px 24px;
        background-attachment: fixed;
    }}
</style>
"""


PLOTLY_DARK: dict = {
    "template": "plotly_dark",
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
    "font": {"family": "DM Sans, sans-serif", "color": "#E2E8F0"},
}


def apply_theme() -> None:
    """Inject fonts, hide chrome, and apply Blueprint Cyan CSS."""
    st.markdown(_CSS, unsafe_allow_html=True)
