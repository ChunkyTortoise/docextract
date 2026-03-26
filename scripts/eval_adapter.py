"""Evaluate a trained LoRA adapter against the eval dataset and Claude baseline.

Loads eval JSONL (GET /finetune/export?format=eval), runs predictions with
the fine-tuned adapter, and compares accuracy/F1 against prompted Claude.

Usage
-----
python scripts/eval_adapter.py \\
    --source http://localhost:8000/finetune/export \\
    --api-key $DOCEXTRACT_API_KEY \\
    --adapter-path adapters/invoice/20260326_143022 \\
    --doc-type invoice

python scripts/eval_adapter.py \\
    --source data/eval.jsonl \\
    --adapter-path adapters/invoice/20260326_143022 \\
    --dry-run   # uses stub predictions (all correct) to test pipeline logic
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from scripts.train_qlora import load_jsonl_file, load_jsonl_url

logger = logging.getLogger(__name__)

DOCUMENT_TYPES = [
    "invoice",
    "purchase_order",
    "receipt",
    "bank_statement",
    "identity_document",
    "medical_record",
    "unknown",
]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def load_eval_records(source: str, api_key: str = "", doc_type: str | None = None) -> list[dict[str, Any]]:
    """Load eval JSONL from file or API."""
    if source.startswith("http"):
        params: dict[str, str] = {"format": "eval", "split": "val"}
        if doc_type:
            params["doc_type"] = doc_type
        return load_jsonl_url(source, api_key, params)
    return load_jsonl_file(Path(source))


def parse_ground_truth(records: list[dict[str, Any]]) -> list[str]:
    """Extract ground-truth doc_types from eval JSONL records."""
    return [rec.get("doc_type", "unknown") for rec in records]


def calculate_metrics(
    predictions: list[str],
    ground_truth: list[str],
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Compute accuracy, per-class F1, and confusion matrix.

    Returns a plain dict with no numpy/sklearn dependency so it's always
    importable for tests.
    """
    if not predictions or not predictions:
        return {"accuracy": 0.0, "f1_macro": 0.0, "confusion_matrix": {}}

    if labels is None:
        labels = sorted(set(ground_truth) | set(predictions))

    n = len(predictions)
    correct = sum(p == g for p, g in zip(predictions, ground_truth))
    accuracy = correct / n if n > 0 else 0.0

    # Per-class TP/FP/FN for F1
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)
    for pred, gold in zip(predictions, ground_truth):
        if pred == gold:
            tp[gold] += 1
        else:
            fp[pred] += 1
            fn[gold] += 1

    f1_scores: dict[str, float] = {}
    for label in labels:
        prec = tp[label] / (tp[label] + fp[label]) if (tp[label] + fp[label]) > 0 else 0.0
        rec = tp[label] / (tp[label] + fn[label]) if (tp[label] + fn[label]) > 0 else 0.0
        f1_scores[label] = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0

    f1_macro = sum(f1_scores.values()) / len(f1_scores) if f1_scores else 0.0

    # Confusion matrix: {gold: {predicted: count}}
    matrix: dict[str, dict[str, int]] = {label: defaultdict(int) for label in labels}
    for pred, gold in zip(predictions, ground_truth):
        if gold in matrix:
            matrix[gold][pred] += 1

    return {
        "accuracy": round(accuracy, 4),
        "f1_macro": round(f1_macro, 4),
        "per_class_f1": {k: round(v, 4) for k, v in f1_scores.items()},
        "confusion_matrix": {k: dict(v) for k, v in matrix.items()},
        "n_samples": n,
    }


def format_comparison_table(adapter_metrics: dict, baseline_metrics: dict) -> str:
    """Format a side-by-side comparison table for CLI output."""
    lines = [
        "",
        "=" * 50,
        f"{'Metric':<20} {'Adapter':>12} {'Baseline (Claude)':>16}",
        "=" * 50,
        f"{'Accuracy':<20} {adapter_metrics.get('accuracy', 0):>12.4f} {baseline_metrics.get('accuracy', 0):>16.4f}",
        f"{'F1 (macro)':<20} {adapter_metrics.get('f1_macro', 0):>12.4f} {baseline_metrics.get('f1_macro', 0):>16.4f}",
        f"{'Samples':<20} {adapter_metrics.get('n_samples', 0):>12} {baseline_metrics.get('n_samples', 0):>16}",
        "=" * 50,
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ML inference (lazy imports)
# ---------------------------------------------------------------------------


def _predict_with_adapter(
    records: list[dict[str, Any]],
    adapter_path: str,
    base_model_id: str,
) -> list[str]:
    """Run doc_type predictions using the fine-tuned adapter."""
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(base_model_id)
    model = AutoModelForCausalLM.from_pretrained(
        base_model_id, torch_dtype=torch.float16, device_map="auto"
    )
    model = PeftModel.from_pretrained(model, adapter_path)
    model.eval()

    predictions: list[str] = []
    for rec in records:
        prompt = f"Classify the document type of this extracted data:\n{rec.get('input', '')}"
        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)
        with torch.no_grad():
            outputs = model.generate(**inputs, max_new_tokens=20)
        decoded = tokenizer.decode(outputs[0], skip_special_tokens=True)
        # Extract first matching document type token from output
        pred = "unknown"
        for doc_type in DOCUMENT_TYPES:
            if doc_type in decoded.lower():
                pred = doc_type
                break
        predictions.append(pred)
    return predictions


def _predict_with_claude(records: list[dict[str, Any]], api_key: str) -> list[str]:
    """Run doc_type predictions using prompted Claude (baseline)."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    predictions: list[str] = []
    for rec in records:
        prompt = (
            f"Classify the document type. Reply with exactly one of: "
            f"{', '.join(DOCUMENT_TYPES)}.\n\nData:\n{rec.get('input', '')}"
        )
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip().lower()
        pred = next((dt for dt in DOCUMENT_TYPES if dt in text), "unknown")
        predictions.append(pred)
    return predictions


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    """Run adapter evaluation. Returns metrics dict."""
    records = load_eval_records(args.source, api_key=args.api_key, doc_type=args.doc_type)
    if not records:
        logger.error("No eval records found.")
        return {}

    ground_truth = parse_ground_truth(records)
    logger.info("Evaluating on %d samples", len(records))

    if args.dry_run:
        # Stub: predict everything correctly
        adapter_preds = list(ground_truth)
        baseline_preds = list(ground_truth)
    else:
        adapter_preds = _predict_with_adapter(records, args.adapter_path, args.model)
        baseline_preds = _predict_with_claude(records, args.api_key) if args.api_key else list(ground_truth)

    adapter_metrics = calculate_metrics(adapter_preds, ground_truth)
    baseline_metrics = calculate_metrics(baseline_preds, ground_truth)

    print(format_comparison_table(adapter_metrics, baseline_metrics))

    return {
        "adapter": adapter_metrics,
        "baseline": baseline_metrics,
        "delta_accuracy": round(adapter_metrics["accuracy"] - baseline_metrics["accuracy"], 4),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate DocExtract adapter vs Claude baseline")
    parser.add_argument("--source", required=True, help="Eval JSONL file path or API URL")
    parser.add_argument("--api-key", default="", help="DocExtract + Anthropic API key")
    parser.add_argument("--adapter-path", required=True, help="Path to trained LoRA adapter")
    parser.add_argument("--doc-type", default=None, help="Filter by document type")
    parser.add_argument("--model", default="mistralai/Mistral-7B-Instruct-v0.2", help="Base model ID")
    parser.add_argument("--dry-run", action="store_true", help="Use stub predictions")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)
    result = evaluate(args)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
