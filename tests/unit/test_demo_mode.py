"""Tests for demo mode data loader."""
import json
from pathlib import Path
import pytest
from frontend.demo_mode import (
    load_demo_extraction,
    load_demo_search,
    load_demo_eval,
    list_demo_doc_types,
)


def test_list_demo_doc_types_returns_expected():
    types = list_demo_doc_types()
    assert set(types) == {"invoice", "contract", "receipt"}


def test_load_demo_extraction_invoice():
    result = load_demo_extraction("invoice")
    assert result["document_type"] == "invoice"
    assert "extracted_data" in result
    assert "field_confidence" in result
    assert 0 < result["confidence"] <= 1.0


def test_load_demo_extraction_contract():
    result = load_demo_extraction("contract")
    assert result["document_type"] == "contract"
    assert "parties" in result["extracted_data"]


def test_load_demo_extraction_receipt():
    result = load_demo_extraction("receipt")
    assert result["document_type"] == "receipt"
    assert "total" in result["extracted_data"]


def test_load_demo_extraction_invalid_type_raises():
    with pytest.raises(ValueError, match="No demo data"):
        load_demo_extraction("unknown_type")


def test_load_demo_search_structure():
    result = load_demo_search()
    assert "results" in result
    assert len(result["results"]) > 0
    for r in result["results"]:
        assert "content" in r
        assert "score" in r
        assert 0 <= r["score"] <= 1.0


def test_load_demo_eval_structure():
    result = load_demo_eval()
    assert "summary" in result
    summary = result["summary"]
    for metric in ("context_recall", "faithfulness", "answer_relevancy", "overall"):
        assert metric in summary
        assert 0 <= summary[metric] <= 1.0


def test_demo_data_files_are_valid_json():
    demo_dir = Path("frontend/demo_data")
    json_files = list(demo_dir.glob("*.json"))
    assert len(json_files) >= 4
    for f in json_files:
        data = json.loads(f.read_text())
        assert isinstance(data, dict)


def test_field_confidence_values_in_range():
    for doc_type in list_demo_doc_types():
        result = load_demo_extraction(doc_type)
        for field, score in result["field_confidence"].items():
            assert 0 <= score <= 1.0, f"Field {field} has out-of-range confidence {score}"
