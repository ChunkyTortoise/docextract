"""DocExtract AI -- Streamlit frontend entry point."""
import os

import streamlit as st

from frontend.theme import apply_theme

# Page config must be first
st.set_page_config(
    page_title="DocExtract AI",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_theme()

DEMO_MODE = os.getenv("DEMO_MODE", "").lower() in ("true", "1", "yes")


def authenticate() -> bool:
    """Simple password gate. Bypassed in demo mode."""
    if st.session_state.get("authenticated"):
        return True

    # Demo mode: skip login, auto-populate demo API key
    if DEMO_MODE:
        st.session_state["authenticated"] = True
        st.session_state["api_key"] = os.getenv(
            "DEMO_API_KEY", "demo-key-docextract-2026"
        )
        return True

    st.title("DocExtract AI")
    st.subheader("Login")

    password = st.text_input("Password", type="password")
    if st.button("Login"):
        expected = st.secrets.get("password", "")
        if password == expected:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Invalid password")
    return False


def init_session_state() -> None:
    """Initialize session state defaults."""
    defaults = {
        "authenticated": False,
        "current_job_id": None,
        "current_doc_id": None,
        "current_record_id": None,
        "filters": {},
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def main() -> None:
    init_session_state()

    if not authenticate():
        return

    if DEMO_MODE:
        st.info("Demo mode — read-only access")

    # Sidebar navigation
    with st.sidebar:
        st.title("DocExtract AI")
        st.caption("AI Document Processing")
        st.divider()

        pages = ["Upload", "Batch Upload", "Progress", "Results", "Records", "Review", "ROI", "Dashboard", "Cost Dashboard", "Demo", "Architecture", "Evaluation", "Prompt Lab", "Agent Trace"]
        default_idx = 0
        if "nav_target" in st.session_state:
            target = st.session_state.pop("nav_target")
            if target in pages:
                default_idx = pages.index(target)

        page = st.radio("Navigate", pages, index=default_idx)

    # Route to page
    if page == "Upload":
        from frontend.pages.upload import render
        render()
    elif page == "Batch Upload":
        from frontend.pages.batch_upload import render
        render()
    elif page == "Progress":
        from frontend.pages.progress import render
        render()
    elif page == "Results":
        from frontend.pages.results import render
        render()
    elif page == "Records":
        from frontend.pages.records import render
        render()
    elif page == "Review":
        from frontend.pages.review import render
        render()
    elif page == "ROI":
        from frontend.pages.roi import render
        render()
    elif page == "Dashboard":
        from frontend.pages.dashboard import render
        render()
    elif page == "Cost Dashboard":
        from frontend.pages.cost_dashboard import render
        render()
    elif page == "Demo":
        from frontend.pages.demo_sandbox import show
        show()
    elif page == "Architecture":
        from frontend.pages.architecture import show
        show()
    elif page == "Evaluation":
        from frontend.pages.evaluation import render
        render()
    elif page == "Prompt Lab":
        from frontend.pages.prompt_lab import render
        render()
    elif page == "Agent Trace":
        from frontend.pages.agent_trace import render
        render()


if __name__ == "__main__":
    main()
