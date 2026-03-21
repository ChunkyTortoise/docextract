"""Screen 5: Human review interface with queue workflow."""
import os

import streamlit as st
import frontend.api_client as api


DOCUMENT_TYPES = ["All", "Invoice", "Purchase Order", "Receipt", "Bank Statement", "Identity Document", "Medical Record"]
QUEUE_STATUSES = ["All", "pending", "claimed", "approved", "rejected"]


def _review_record_form(record_id: str, demo_mode: bool) -> None:
    """Render the editable review form for a single record (legacy path)."""
    try:
        record = api.get_record(record_id)

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Document Type", record.get("document_type", "Unknown").replace("_", " ").title())
        with col2:
            conf = record.get("confidence_score", 0)
            st.metric("Confidence", f"{conf:.1%}")
        with col3:
            st.metric("Status", record.get("review_status") or "Pending")

        st.subheader("Edit Extracted Data")

        extracted = record.get("extracted_data") or {}
        corrected = record.get("corrected_data") or {}
        current_data = {**extracted, **corrected}

        corrections = {}
        for key, value in current_data.items():
            if key.startswith("_") or isinstance(value, (list, dict)):
                continue
            new_value = st.text_input(
                key.replace("_", " ").title(),
                value=str(value) if value is not None else "",
                key=f"field_{key}",
            )
            if new_value != str(value or ""):
                corrections[key] = new_value

        reviewer_notes = st.text_area("Reviewer Notes")

        st.divider()
        if demo_mode:
            st.info("Review actions are disabled in demo mode.")
            return
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Approve", type="primary"):
                with st.spinner("Submitting review..."):
                    try:
                        api.review_record(
                            record_id=record_id,
                            decision="approve",
                            corrections=corrections if corrections else None,
                            reviewer_notes=reviewer_notes or None,
                        )
                        st.success("Record approved!")
                        st.session_state["current_record_id"] = None
                    except Exception as e:
                        st.error(f"Review failed: {e}")
        with col2:
            if st.button("Reject", type="secondary"):
                with st.spinner("Submitting review..."):
                    try:
                        api.review_record(
                            record_id=record_id,
                            decision="reject",
                            corrections=corrections if corrections else None,
                            reviewer_notes=reviewer_notes or None,
                        )
                        st.warning("Record rejected.")
                        st.session_state["current_record_id"] = None
                    except Exception as e:
                        st.error(f"Review failed: {e}")
    except Exception as e:
        st.error(f"Could not load record: {e}")


def render() -> None:
    st.title("Document Review")

    demo_mode = os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")

    tab_queue, tab_direct = st.tabs(["Review Queue", "Direct Review"])

    # --- Tab 1: Queue-based review ---
    with tab_queue:
        # Metrics row
        try:
            metrics = api.get_review_metrics()
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Pending", metrics.get("pending", 0))
            with col2:
                st.metric("Claimed", metrics.get("claimed", 0))
            with col3:
                st.metric("Total Open", metrics.get("total_open", 0))
            with col4:
                sla_rate = metrics.get("sla_breach_rate", 0)
                st.metric("SLA Breach Rate", f"{sla_rate:.1%}")
        except Exception as e:
            st.warning(f"Could not load queue metrics: {e}")

        st.divider()

        # Filters
        col_status, col_type, col_page = st.columns(3)
        with col_status:
            status_filter = st.selectbox("Status", QUEUE_STATUSES, index=0, key="q_status")
        with col_type:
            type_filter = st.selectbox("Document Type", DOCUMENT_TYPES, index=0, key="q_type")
        with col_page:
            q_page = st.number_input("Page", min_value=1, value=1, step=1, key="q_page")

        # Build filter params
        q_params: dict = {}
        if status_filter != "All":
            q_params["status"] = status_filter
        if type_filter != "All":
            q_params["doc_type"] = type_filter.lower().replace(" ", "_")

        try:
            queue_data = api.get_review_items(page=q_page, page_size=20, **q_params)
            queue_items = queue_data.get("items", [])
            total_queue = queue_data.get("total", len(queue_items))

            st.caption(f"Showing {len(queue_items)} of {total_queue} items")

            if not queue_items:
                st.info("No review items match your filters.")
            else:
                import pandas as pd
                df_cols = ["id", "document_type", "confidence_score", "status", "assignee", "created_at"]
                df = pd.DataFrame(queue_items)
                display_df = df[[c for c in df_cols if c in df.columns]]

                selected = st.dataframe(
                    display_df,
                    use_container_width=True,
                    hide_index=True,
                    on_select="rerun",
                    selection_mode="single-row",
                )

                if selected and selected.selection.rows:
                    row_idx = selected.selection.rows[0]
                    item = queue_items[row_idx]
                    item_id = item.get("id", "")
                    item_status = item.get("status", "")

                    st.subheader(f"Action Panel — `{item_id[:8]}...`")

                    if demo_mode:
                        st.info("Queue actions are disabled in demo mode.")
                    else:
                        action_col1, action_col2, action_col3 = st.columns(3)

                        with action_col1:
                            if item_status == "pending":
                                if st.button("Claim", type="primary"):
                                    try:
                                        api.claim_review_item(item_id)
                                        st.success("Item claimed.")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Claim failed: {e}")

                        with action_col2:
                            if item_status == "claimed":
                                if st.button("Approve", type="primary"):
                                    try:
                                        api.approve_review_item(item_id)
                                        st.success("Item approved.")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Approve failed: {e}")

                        with action_col3:
                            if item_status == "claimed":
                                if st.button("Correct & Submit"):
                                    st.session_state["correcting_item"] = item_id

                        # Corrections form
                        if st.session_state.get("correcting_item") == item_id:
                            st.subheader("Corrections")
                            extracted = item.get("extracted_data") or {}
                            corrections: dict = {}
                            for key, value in extracted.items():
                                if key.startswith("_") or isinstance(value, (list, dict)):
                                    continue
                                new_val = st.text_input(
                                    key.replace("_", " ").title(),
                                    value=str(value) if value is not None else "",
                                    key=f"qfield_{item_id}_{key}",
                                )
                                if new_val != str(value or ""):
                                    corrections[key] = new_val

                            notes = st.text_area("Reviewer Notes", key=f"qnotes_{item_id}")
                            if st.button("Submit Corrections", type="primary"):
                                try:
                                    api.correct_review_item(item_id, corrections, reviewer_notes=notes or None)
                                    st.success("Corrections submitted.")
                                    st.session_state["correcting_item"] = None
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Correction failed: {e}")

        except Exception as e:
            st.error(f"Could not load review queue: {e}")

    # --- Tab 2: Direct record review (legacy) ---
    with tab_direct:
        record_id = st.session_state.get("current_record_id")
        if not record_id:
            record_id = st.text_input("Enter Record ID to review")
            if not record_id:
                st.info("No record selected. Browse records and click 'Review'.")
                return

        st.caption(f"Record ID: `{record_id}`")
        _review_record_form(record_id, demo_mode)
