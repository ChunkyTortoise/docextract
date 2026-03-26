"""Unit tests for QLoRA/DPO training scripts and eval pipeline.

All tests run without GPU, torch, peft, or trl — only pure Python logic is
exercised. ML-heavy functions are covered by dry-run integration tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.train_qlora import (
    LORA_CONFIG,
    QUANT_CONFIG,
    build_training_texts,
    get_adapters_by_doc_type,
    load_jsonl_file,
    load_registry,
    update_registry,
)
from scripts.train_dpo import build_dpo_pairs, validate_dpo_pairs
from scripts.eval_adapter import calculate_metrics, format_comparison_table, parse_ground_truth


# ---------------------------------------------------------------------------
# JSONL file loading
# ---------------------------------------------------------------------------


def test_load_jsonl_file_reads_all_records(tmp_path: Path):
    data = [
        {"messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "doc"}, {"role": "assistant", "content": "invoice"}]},
        {"messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "doc2"}, {"role": "assistant", "content": "receipt"}]},
    ]
    jsonl_file = tmp_path / "train.jsonl"
    jsonl_file.write_text("\n".join(json.dumps(r) for r in data))

    records = load_jsonl_file(jsonl_file)
    assert len(records) == 2


def test_load_jsonl_file_skips_blank_lines(tmp_path: Path):
    jsonl_file = tmp_path / "train.jsonl"
    jsonl_file.write_text('{"messages": []}\n\n{"messages": []}\n')

    records = load_jsonl_file(jsonl_file)
    assert len(records) == 2


# ---------------------------------------------------------------------------
# build_training_texts
# ---------------------------------------------------------------------------


def test_build_training_texts_formats_correctly():
    records = [
        {
            "messages": [
                {"role": "system", "content": "You are a classifier."},
                {"role": "user", "content": '{"total": "100.00"}'},
                {"role": "assistant", "content": "invoice"},
            ]
        }
    ]
    texts = build_training_texts(records)
    assert len(texts) == 1
    assert "[INST]" in texts[0]
    assert "You are a classifier." in texts[0]
    assert "invoice" in texts[0]


def test_build_training_texts_skips_short_messages():
    records = [{"messages": [{"role": "user", "content": "hello"}]}]
    texts = build_training_texts(records)
    assert texts == []


def test_build_training_texts_mistral_instruct_format():
    records = [
        {
            "messages": [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "usr"},
                {"role": "assistant", "content": "ans"},
            ]
        }
    ]
    text = build_training_texts(records)[0]
    assert text.startswith("<s>[INST]")
    assert "[/INST]" in text
    assert text.endswith("</s>")


# ---------------------------------------------------------------------------
# build_dpo_pairs and validate_dpo_pairs
# ---------------------------------------------------------------------------


def test_build_dpo_pairs_extracts_fields():
    records = [
        {"prompt": "classify", "chosen": "invoice", "rejected": "receipt", "doc_type": "invoice"},
    ]
    pairs = build_dpo_pairs(records)
    assert len(pairs) == 1
    assert pairs[0]["chosen"] == "invoice"
    assert pairs[0]["rejected"] == "receipt"


def test_build_dpo_pairs_skips_incomplete_records():
    records = [
        {"prompt": "classify", "chosen": "invoice"},  # missing rejected
        {"prompt": "classify", "chosen": "invoice", "rejected": "receipt"},
    ]
    pairs = build_dpo_pairs(records)
    assert len(pairs) == 1


def test_validate_dpo_pairs_detects_identical():
    pairs = [{"prompt": "p", "chosen": "same", "rejected": "same"}]
    errors = validate_dpo_pairs(pairs)
    assert len(errors) == 1
    assert "identical" in errors[0]


def test_validate_dpo_pairs_valid_pairs_no_errors():
    pairs = [{"prompt": "classify", "chosen": "invoice", "rejected": "receipt"}]
    errors = validate_dpo_pairs(pairs)
    assert errors == []


# ---------------------------------------------------------------------------
# Registry CRUD
# ---------------------------------------------------------------------------


def test_registry_initial_state(tmp_path: Path):
    reg_path = tmp_path / "registry.json"
    registry = load_registry(reg_path)
    assert registry["version"] == "1.0"
    assert registry["adapters"] == []


def test_update_registry_creates_file(tmp_path: Path):
    reg_path = tmp_path / "registry.json"
    adapter_dir = tmp_path / "invoice" / "20260326_120000"
    adapter_dir.mkdir(parents=True)

    entry = update_registry(
        adapter_path=adapter_dir,
        doc_type="invoice",
        base_model="mistralai/Mistral-7B-Instruct-v0.2",
        n_samples=42,
        training_format="qlora",
        eval_metrics={"accuracy": 0.94},
        registry_path=reg_path,
    )

    assert reg_path.exists()
    assert entry["doc_type"] == "invoice"
    assert entry["training_samples"] == 42


def test_update_registry_appends_entries(tmp_path: Path):
    reg_path = tmp_path / "registry.json"
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir()

    for i in range(3):
        update_registry(
            adapter_path=adapter_dir,
            doc_type=f"type_{i}",
            base_model="model",
            n_samples=10,
            training_format="qlora",
            eval_metrics={},
            registry_path=reg_path,
        )

    registry = load_registry(reg_path)
    assert len(registry["adapters"]) == 3


def test_get_adapters_by_doc_type_filters_correctly(tmp_path: Path):
    reg_path = tmp_path / "registry.json"
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir()

    update_registry(adapter_dir, "invoice", "model", 10, "qlora", {}, reg_path)
    update_registry(adapter_dir, "receipt", "model", 5, "qlora", {}, reg_path)
    update_registry(adapter_dir, "invoice", "model", 15, "qlora", {}, reg_path)

    invoice_adapters = get_adapters_by_doc_type("invoice", reg_path)
    assert len(invoice_adapters) == 2
    assert all(a["doc_type"] == "invoice" for a in invoice_adapters)


# ---------------------------------------------------------------------------
# calculate_metrics
# ---------------------------------------------------------------------------


def test_calculate_metrics_perfect_accuracy():
    preds = ["invoice", "receipt", "invoice"]
    gold = ["invoice", "receipt", "invoice"]
    metrics = calculate_metrics(preds, gold)
    assert metrics["accuracy"] == 1.0
    assert metrics["f1_macro"] == 1.0


def test_calculate_metrics_partial_accuracy():
    preds = ["invoice", "receipt", "invoice"]
    gold = ["invoice", "invoice", "receipt"]
    metrics = calculate_metrics(preds, gold)
    assert 0.0 < metrics["accuracy"] < 1.0


def test_calculate_metrics_returns_confusion_matrix():
    preds = ["invoice", "receipt"]
    gold = ["invoice", "invoice"]
    metrics = calculate_metrics(preds, gold)
    assert "confusion_matrix" in metrics
    assert "invoice" in metrics["confusion_matrix"]


def test_calculate_metrics_empty_input():
    metrics = calculate_metrics([], [])
    assert metrics["accuracy"] == 0.0


# ---------------------------------------------------------------------------
# parse_ground_truth
# ---------------------------------------------------------------------------


def test_parse_ground_truth_extracts_doc_types():
    records = [
        {"input": "...", "expected_output": "...", "doc_type": "invoice"},
        {"input": "...", "expected_output": "...", "doc_type": "receipt"},
    ]
    gt = parse_ground_truth(records)
    assert gt == ["invoice", "receipt"]


def test_parse_ground_truth_defaults_unknown():
    records = [{"input": "..."}]
    gt = parse_ground_truth(records)
    assert gt == ["unknown"]


# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------


def test_lora_config_has_expected_keys():
    assert "r" in LORA_CONFIG
    assert "lora_alpha" in LORA_CONFIG
    assert "target_modules" in LORA_CONFIG
    assert LORA_CONFIG["r"] == 16
    assert LORA_CONFIG["lora_alpha"] == 32


def test_lora_config_scale():
    """alpha/r should equal 2.0 (standard setting from notebook)."""
    assert LORA_CONFIG["lora_alpha"] / LORA_CONFIG["r"] == 2.0


def test_quant_config_uses_4bit():
    assert QUANT_CONFIG["load_in_4bit"] is True
    assert QUANT_CONFIG["bnb_4bit_quant_type"] == "nf4"


# ---------------------------------------------------------------------------
# format_comparison_table
# ---------------------------------------------------------------------------


def test_format_comparison_table_contains_accuracy():
    adapter = {"accuracy": 0.94, "f1_macro": 0.93, "n_samples": 100}
    baseline = {"accuracy": 0.88, "f1_macro": 0.87, "n_samples": 100}
    table = format_comparison_table(adapter, baseline)
    assert "Accuracy" in table
    assert "0.9400" in table
    assert "0.8800" in table
