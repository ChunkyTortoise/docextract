"""Presentation of stored fixture results. No service calls or fixture writes."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import cast

import streamlit as st

from frontend.comparison_samples import DATA_DIR, LABEL

_SETUP_URL = (
    "https://github.com/ChunkyTortoise/docextract/blob/"
    "8f175edb080b177f7ed92c589f645ccd502cc077/README.md#quickstart-no-api-key"
)


def _value_html(value: object, path: str) -> str:
    if isinstance(value, dict):
        if not value:
            return '<span class="desk-empty">Empty object</span>'
        return (
            '<dl class="desk-nested">'
            + "".join(
                f"<div><dt>{escape(str(key).replace('_', ' '))}</dt>"
                f"<dd>{_value_html(item, f'{path}.{key}')}</dd></div>"
                for key, item in value.items()
            )
            + "</dl>"
        )
    if isinstance(value, list):
        if not value:
            return '<span class="desk-empty">Empty list</span>'
        return (
            '<ol class="desk-list">'
            + "".join(
                f"<li>{_value_html(item, f'{path}[{index}]')}</li>"
                for index, item in enumerate(value)
            )
            + "</ol>"
        )
    text = value if isinstance(value, str) else json.dumps(value)
    return f'<span data-field-path="{escape(path, quote=True)}">{escape(text)}</span>'


def _summary_html(doc_type: str, fields: dict[str, object]) -> str:
    if doc_type == "invoice":
        title, subtitle = fields["invoice_number"], fields["vendor_name"]
    elif doc_type == "contract":
        title = fields["contract_type"]
        subtitle = " · ".join(str(p) for p in cast(list[object], fields["parties"]))
    else:
        title, subtitle = fields["merchant_name"], fields["receipt_number"]
    amount = ""
    if "total" in fields:
        amount = (
            '<div class="desk-total"><p class="desk-eyebrow">Stored total</p>'
            f'<p class="desk-amount">{escape(str(fields["total"]))}</p></div>'
        )
    return (
        '<section class="desk-summary"><div>'
        f'<p class="desk-eyebrow">Stored {escape(doc_type)} result</p>'
        f'<h2>{escape(str(title))}</h2><p class="desk-subtitle">{escape(str(subtitle))}</p>'
        f"</div>{amount}</section>"
    )


def apply_demo_styles() -> None:
    """Load scoped styles independently of fixture loading or Fields rendering."""
    css = Path(__file__).with_suffix(".css").read_text()
    st.html(f"<style>{css}</style>")


def render_stored_result(doc_type: str, result: dict[str, object]) -> None:
    """Render complete supplied values with native disclosures and downloads."""
    if doc_type not in ("invoice", "contract", "receipt"):
        raise ValueError(f"Unknown stored document type: {doc_type!r}")
    fields = cast(dict[str, object], result["extracted_data"])
    with st.container(key="stored-result"):
        apply_demo_styles()
        st.html(_summary_html(doc_type, fields))
        st.caption(
            f"Source: frontend/demo_data/{doc_type}_sample.json | "
            f"Stored sample: {result['filename']}"
        )
        st.caption("Stored outputs, not an extraction of a document in this session.")
        st.markdown("[Reproduce / setup](#reproduce)")
        with st.container(key="result-workbench"):
            fields_column, specimen_column = st.columns([1.13, 1], gap="large")
            with fields_column:
                entries = []
                for key, value in fields.items():
                    wide = isinstance(value, dict | list) or "address" in key
                    classes = "desk-field desk-field-wide" if wide else "desk-field"
                    entries.append(
                        f'<div class="{classes}"><dt>{escape(key.replace("_", " "))}</dt>'
                        f"<dd>{_value_html(value, f'extracted_data.{key}')}</dd></div>"
                    )
                st.html(
                    '<section class="desk-fields"><h3>01 / Complete stored fields</h3>'
                    '<dl class="desk-field-grid">' + "".join(entries) + "</dl></section>"
                )
                st.caption(
                    "Stored confidence is not calibrated accuracy or the offline replay score. "
                    "Confidence and processing time are stored sample metadata."
                )
                with st.expander("Stored sample metadata"):
                    st.json(
                        {key: value for key, value in result.items() if key != "extracted_data"}
                    )
                with st.expander("Inspect the complete fixture JSON"):
                    st.json(result)
                st.download_button(
                    "Download stored JSON",
                    json.dumps(result, indent=2),
                    file_name=f"{doc_type}_sample.json",
                    mime="application/json",
                    key=f"stored_json_{doc_type}",
                )
                st.html('<h3 id="reproduce">Reproduce / setup</h3>')
                st.markdown("In an already prepared demo environment, start the fixture explorer:")
                st.code("python -m streamlit run streamlit_demo.py", language="bash")
                st.caption("Separate offline evaluation, not a fresh extraction:")
                st.code("python scripts/eval_offline_replay.py --floor 0.85", language="bash")
                st.markdown(f"[Setup instructions]({_SETUP_URL})")
            with specimen_column:
                st.html(
                    '<div class="desk-specimen-heading"><h3>02 / Optional reconstruction</h3></div>'
                )
                st.caption(
                    "Synthetic reconstruction from stored fields. "
                    "Cannot verify extraction or original PDF layout."
                )
                with st.expander("Synthetic comparison, not the original PDF", expanded=False):
                    st.caption(LABEL)
                    comparison = (DATA_DIR / "comparison" / f"{doc_type}.html").read_text()
                    st.html(comparison)
                    st.download_button(
                        "Download synthetic comparison HTML",
                        comparison,
                        file_name=f"synthetic_{doc_type}_comparison.html",
                        mime="text/html",
                        key=f"comparison_download_{doc_type}",
                    )
