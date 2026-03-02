"""JSON viewer with confidence color coding."""
import streamlit as st


def _confidence_color(confidence: float) -> str:
    """Return CSS color based on confidence score."""
    if confidence >= 0.8:
        return "#2ecc71"  # Green
    elif confidence >= 0.6:
        return "#f39c12"  # Yellow/Orange
    else:
        return "#e74c3c"  # Red


def display_extraction(
    data: dict,
    confidences: dict | None = None,
    title: str = "Extracted Data",
) -> None:
    """Display extracted data with confidence color coding.

    Args:
        data: Extracted field data dict
        confidences: Optional dict of field_name -> confidence score (0-1)
        title: Section title
    """
    st.subheader(title)

    if not data:
        st.warning("No data extracted")
        return

    confidences = confidences or {}

    for key, value in data.items():
        if key.startswith("_"):
            continue  # Skip internal fields

        conf = confidences.get(key, 1.0)
        color = _confidence_color(conf)

        if isinstance(value, list):
            with st.expander(f"**{key}** ({len(value)} items)"):
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        st.json(item)
                    else:
                        st.text(str(item))
        elif isinstance(value, dict):
            with st.expander(f"**{key}**"):
                st.json(value)
        elif value is not None:
            col1, col2 = st.columns([1, 3])
            with col1:
                st.markdown(f"**{key}**")
            with col2:
                st.markdown(
                    f'<span style="color:{color}">{value}</span>',
                    unsafe_allow_html=True,
                )
