"""Document viewer component with page navigation."""
import streamlit as st


def display_document(
    pages: list[bytes],
    mime_type: str = "image/jpeg",
    title: str = "Document",
) -> None:
    """Display document with page navigation.

    Args:
        pages: List of image bytes per page
        mime_type: Image MIME type
        title: Display title
    """
    st.subheader(title)

    if not pages:
        st.info("No document preview available")
        return

    total_pages = len(pages)

    if total_pages > 1:
        page_num = st.slider("Page", min_value=1, max_value=total_pages, value=1, key=f"{title}_page")
    else:
        page_num = 1

    st.image(pages[page_num - 1], use_column_width=True)

    if total_pages > 1:
        st.caption(f"Page {page_num} of {total_pages}")
