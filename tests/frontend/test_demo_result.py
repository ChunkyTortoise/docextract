"""Stored values, context and actions survive the examination desk presentation."""

from __future__ import annotations

import importlib
import json
from copy import deepcopy
from html import escape
from html.parser import HTMLParser
from unittest.mock import MagicMock

import pytest

from frontend.demo_mode import load_demo_extraction


class LeafReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.leaves = {}
        self.path = None

    def handle_starttag(self, tag, attrs):
        if tag == "span":
            self.path = dict(attrs).get("data-field-path")
            if self.path is not None:
                self.leaves[self.path] = ""

    def handle_data(self, data):
        if self.path is not None:
            self.leaves[self.path] += data

    def handle_endtag(self, tag):
        if tag == "span":
            self.path = None


def leaves(value, path="extracted_data"):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from leaves(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from leaves(item, f"{path}[{index}]")
    else:
        yield path, value if isinstance(value, str) else json.dumps(value)


def render(monkeypatch, doc_type, result):
    module = importlib.import_module("frontend.demo_result")
    ui = MagicMock()
    ui.columns.return_value = [MagicMock(), MagicMock()]
    monkeypatch.setattr(module, "st", ui)
    module.render_stored_result(doc_type, result)
    html = "\n".join(str(c.args[0]) for c in ui.html.call_args_list)
    return ui, html


@pytest.mark.parametrize("doc_type", ["invoice", "contract", "receipt"])
def test_all_nested_leaves_keep_context_and_download_is_original(monkeypatch, doc_type):
    original = load_demo_extraction(doc_type)
    result = deepcopy(original)
    ui, html = render(monkeypatch, doc_type, result)
    reader = LeafReader()
    reader.feed(html)
    assert reader.leaves == dict(leaves(original["extracted_data"]))
    for key in original["extracted_data"]:
        assert f"<dt>{escape(key.replace('_', ' '))}</dt>" in html
    payload = next(
        c.args[1] for c in ui.download_button.call_args_list if c.args[0] == "Download stored JSON"
    )
    assert json.loads(payload) == original
    assert result == original
    assert any(
        c.args[0] == {k: v for k, v in original.items() if k != "extracted_data"}
        for c in ui.json.call_args_list
    )
    assert any(c.args[0] == original for c in ui.json.call_args_list)
    captions = " ".join(c.args[0] for c in ui.caption.call_args_list)
    assert "not calibrated accuracy" in captions
    assert f"{doc_type}_sample.json" in captions
    assert "Cannot verify extraction" in captions
    assert any(
        c.args[0] == "Download synthetic comparison HTML" for c in ui.download_button.call_args_list
    )


@pytest.mark.parametrize(
    "doc_type,identity,total",
    [
        ("invoice", "INV-2024-00847", "$5,286.50"),
        ("contract", "Non-Disclosure Agreement", None),
        ("receipt", "Blue Bottle Coffee", "$31.28"),
    ],
)
def test_summary_uses_own_identity_and_totals(monkeypatch, doc_type, identity, total):
    _, html = render(monkeypatch, doc_type, load_demo_extraction(doc_type))
    summary = html.split('<section class="desk-summary">')[1].split("</section>")[0]
    assert identity in summary
    if total:
        assert total in summary
    else:
        assert "Stored total" not in summary
    if doc_type != "invoice":
        assert "INV-2024-00847" not in html
        assert "Invoice Number" not in html
        assert "$5,286.50" not in html


def test_script_like_labels_values_and_long_text_are_preserved_as_text(monkeypatch):
    result = load_demo_extraction("invoice")
    payload = '<script>alert("fixture")</script><img src=x onerror=alert(1)> & ' + "unbroken" * 100
    result["extracted_data"]['<label onclick="bad()">'] = {"nested": [payload, None, False, 0]}
    result["extracted_data"]["empty_object"] = {}
    result["extracted_data"]["empty_array"] = []
    _, html = render(monkeypatch, "invoice", result)
    assert '<script>alert("fixture")</script>' not in html
    assert "<img src=x" not in html
    assert escape(payload) in html
    assert escape('<label onclick="bad()">') in html
    reader = LeafReader()
    reader.feed(html)
    assert reader.leaves == dict(leaves(result["extracted_data"]))
    assert "Empty object" in html
    assert "Empty list" in html


def test_reproduction_actions_precede_collapsed_reconstruction(monkeypatch):
    ui, _ = render(monkeypatch, "invoice", load_demo_extraction("invoice"))
    calls = ui.method_calls
    reproduction = next(
        i for i, c in enumerate(calls) if c[0] == "html" and 'id="reproduce"' in c.args[0]
    )
    reconstruction = next(
        i for i, c in enumerate(calls) if c[0] == "expander" and "not the original PDF" in c.args[0]
    )
    assert reproduction < reconstruction
    assert calls[reconstruction].kwargs["expanded"] is False
    assert any(c[0] == "markdown" and "[Reproduce / setup](#reproduce)" in c.args[0] for c in calls)


def test_json_scalar_spelling_is_preserved_in_nested_fields(monkeypatch):
    result = load_demo_extraction("invoice")
    result["extracted_data"]["json_types"] = [None, True, False, 0, 1.5, "false"]
    _, html = render(monkeypatch, "invoice", result)
    reader = LeafReader()
    reader.feed(html)
    assert {path: text for path, text in reader.leaves.items() if "json_types" in path} == {
        "extracted_data.json_types[0]": "null",
        "extracted_data.json_types[1]": "true",
        "extracted_data.json_types[2]": "false",
        "extracted_data.json_types[3]": "0",
        "extracted_data.json_types[4]": "1.5",
        "extracted_data.json_types[5]": "false",
    }


def test_field_labels_keep_original_case_and_punctuation(monkeypatch):
    result = load_demo_extraction("invoice")
    result["extracted_data"]["tax_ID"] = "CA-123"
    result["extracted_data"]["vendor's"] = {"API_URL": "https://example.invalid"}
    _, html = render(monkeypatch, "invoice", result)
    assert "<dt>tax ID</dt>" in html
    assert "<dt>vendor&#x27;s</dt>" in html
    assert "<dt>API URL</dt>" in html
