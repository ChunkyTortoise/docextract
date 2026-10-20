"""Build synthetic comparison documents from stored fields, never original sources."""
from __future__ import annotations

import json
from html import escape
from pathlib import Path

DATA_DIR = Path(__file__).parent / "demo_data"
LABEL = "synthetic comparison sample reconstructed from stored fixture data"


def _value_html(value: object) -> str:
    if isinstance(value, dict):
        return "<dl>" + "".join(
            f"<dt>{escape(key.replace('_', ' ').title())}</dt><dd>{_value_html(item)}</dd>"
            for key, item in value.items()
        ) + "</dl>"
    if isinstance(value, list):
        return "<ul>" + "".join(f"<li>{_value_html(item)}</li>" for item in value) + "</ul>"
    return escape(str(value))


def render_comparison(doc_type: str) -> str:
    """Render all stored fields with escaping and explicit reconstruction provenance."""
    if doc_type not in ("invoice", "contract", "receipt"):
        raise ValueError("Unknown comparison sample")
    fixture = json.loads((DATA_DIR / f"{doc_type}_sample.json").read_text())
    fields = "".join(
        f'<dt>{escape(key.replace("_", " ").title())}</dt>'
        f'<dd data-field="{escape(key)}">{_value_html(value)}</dd>'
        for key, value in fixture["extracted_data"].items()
    )
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Synthetic {doc_type.title()} comparison</title>
<style>
.comparison-sample {{font: 16px/1.5 system-ui, sans-serif; color: #172554;
 background: #f8fafc; padding: 16px; border: 1px solid #94a3b8;
 border-radius: 8px; max-width: 720px; box-sizing: border-box; overflow-wrap: anywhere;}}
.comparison-sample h2 {{font-size: 22px; margin: 0 0 8px;}}
.comparison-sample dt {{font-weight: 650; margin-top: 10px;}}
.comparison-sample dd {{margin: 0;}}
.comparison-sample ul {{padding-left: 22px;}}
</style></head><body>
<article class="comparison-sample" aria-label="Synthetic {doc_type} comparison">
<h2>{doc_type.title()} comparison</h2>
<p><strong>{LABEL}</strong></p>
<p>Synthetic illustration only. This is not the original processed PDF,
 a real transaction or a signed agreement. No extraction was run on this sample.</p>
<dl>{fields}</dl>
<p>Source of values: {doc_type}_sample.json. Reconstructed on October 1, 2026
 with scripts/render_comparison_samples.py. Layout and wording are newly authored;
 no original document layout, signature or extraction correctness is established.
 This comparison does not change the separate 95.5% offline evaluation score.</p>
</article></body></html>
'''
