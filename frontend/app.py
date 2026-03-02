"""DocExtract AI -- Streamlit frontend entry point."""
import streamlit as st

# Page config must be first
st.set_page_config(
    page_title="DocExtract AI",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)


def authenticate() -> bool:
    """Simple password gate."""
    if st.session_state.get("authenticated"):
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

    # Sidebar navigation
    with st.sidebar:
        st.title("DocExtract AI")
        st.caption("AI Document Processing")
        st.divider()

        page = st.radio(
            "Navigate",
            ["Upload", "Progress", "Results", "Records", "Review", "Dashboard"],
            index=0,
        )

    # Route to page
    if page == "Upload":
        from frontend.pages.upload import render
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
    elif page == "Dashboard":
        from frontend.pages.dashboard import render
        render()


if __name__ == "__main__":
    main()
