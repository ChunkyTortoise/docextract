"""Shared theme and CSS injection for DocExtract AI frontend."""

import streamlit as st

_FONTS_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=Plus+Jakarta+Sans:wght@400;500;600;700&"
    "family=JetBrains+Mono:wght@400;500&display=swap"
)

_CSS = f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{_FONTS_URL}" rel="stylesheet">
<style>
    /* Fonts */
    html, body, [class*="css"] {{
        font-family: 'Plus Jakarta Sans', sans-serif;
    }}
    code, pre, .stCode, [data-testid="stCode"] {{
        font-family: 'JetBrains Mono', monospace !important;
    }}

    /* Hide Streamlit chrome */
    #MainMenu, footer, header {{ visibility: hidden; }}
    [data-testid="stToolbar"] {{ display: none; }}

    /* Glass cards */
    .glass-card {{
        background: rgba(255, 255, 255, 0.05);
        backdrop-filter: blur(12px) saturate(180%);
        -webkit-backdrop-filter: blur(12px) saturate(180%);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 1.25rem 1.5rem;
        margin-bottom: 1rem;
    }}

    /* Skeleton shimmer for loading states */
    @keyframes shimmer {{
        0% {{ background-position: -468px 0; }}
        100% {{ background-position: 468px 0; }}
    }}
    .skeleton {{
        background: linear-gradient(
            to right,
            rgba(255,255,255,0.04) 8%,
            rgba(255,255,255,0.10) 18%,
            rgba(255,255,255,0.04) 33%
        );
        background-size: 800px 104px;
        animation: shimmer 1.4s ease-in-out infinite;
        border-radius: 6px;
        height: 1rem;
        margin: 0.4rem 0;
    }}

    /* Metric card accent */
    [data-testid="metric-container"] {{
        background: rgba(99, 102, 241, 0.08);
        border: 1px solid rgba(99, 102, 241, 0.2);
        border-radius: 10px;
        padding: 0.75rem 1rem;
    }}

    /* Sidebar refinement */
    [data-testid="stSidebar"] {{
        background-color: #13132a;
    }}
</style>
"""


PLOTLY_DARK: dict = {
    "template": "plotly_dark",
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
    "font": {"family": "Plus Jakarta Sans, sans-serif", "color": "#E2E8F0"},
}


def apply_theme() -> None:
    """Inject fonts, hide chrome, and apply glassmorphism CSS."""
    st.markdown(_CSS, unsafe_allow_html=True)
