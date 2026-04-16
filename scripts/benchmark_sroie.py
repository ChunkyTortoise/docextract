#!/usr/bin/env python3
"""SROIE receipt benchmark for DocExtract AI.

Evaluates extraction accuracy on the SROIE test set (receipts with ground truth).

Usage:
    python scripts/benchmark_sroie.py --dry-run         # validate scoring logic only
    python scripts/benchmark_sroie.py --api-url URL --api-key KEY  # run against live API
    python scripts/benchmark_sroie.py --results-file results.json  # load existing results

SROIE ground truth fields: company, date, address, total
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

# SROIE target fields for evaluation
SROIE_FIELDS = ["company", "date", "address", "total"]


@dataclass
class FieldScore:
    field: str
    exact_matches: int = 0
    total: int = 0
    true_positives: float = 0.0
    false_positives: float = 0.0
    false_negatives: float = 0.0

    @property
    def precision(self) -> float:
        if self.true_positives + self.false_positives == 0:
            return 0.0
        return self.true_positives / (self.true_positives + self.false_positives)

    @property
    def recall(self) -> float:
        if self.true_positives + self.false_negatives == 0:
            return 0.0
        return self.true_positives / (self.true_positives + self.false_negatives)

    @property
    def f1(self) -> float:
        if self.precision + self.recall == 0:
            return 0.0
        return 2 * (self.precision * self.recall) / (self.precision + self.recall)

    @property
    def exact_match_accuracy(self) -> float:
        if self.total == 0:
            return 0.0
        return self.exact_matches / self.total


@dataclass
class BenchmarkResults:
    total_documents: int = 0
    field_scores: dict[str, FieldScore] = field(default_factory=dict)
    confidence_scores: list[float] = field(default_factory=list)

    @property
    def macro_f1(self) -> float:
        if not self.field_scores:
            return 0.0
        return sum(s.f1 for s in self.field_scores.values()) / len(self.field_scores)

    @property
    def overall_exact_match(self) -> float:
        """Fraction of documents where ALL fields matched exactly."""
        if self.total_documents == 0:
            return 0.0
        exact_all = sum(
            1 for i in range(self.total_documents)
            if all(
                s.exact_matches > 0
                for s in self.field_scores.values()
                if s.total > 0
            )
        )
        return exact_all / self.total_documents

    @property
    def mean_confidence(self) -> float:
        if not self.confidence_scores:
            return 0.0
        return sum(self.confidence_scores) / len(self.confidence_scores)


def normalize_text(text: str | None) -> str:
    """Normalize text for comparison: lowercase, strip whitespace."""
    if text is None:
        return ""
    return " ".join(text.lower().strip().split())


def compute_token_f1(predicted: str, ground_truth: str) -> tuple[float, float, float]:
    """Compute token-level precision, recall, F1 between two strings.

    Standard SQuAD-style token F1 for soft matching.
    """
    pred_tokens = normalize_text(predicted).split()
    gt_tokens = normalize_text(ground_truth).split()

    if not pred_tokens and not gt_tokens:
        return 1.0, 1.0, 1.0
    if not pred_tokens or not gt_tokens:
        return 0.0, 0.0, 0.0

    common = set(pred_tokens) & set(gt_tokens)
    num_common = sum(min(pred_tokens.count(t), gt_tokens.count(t)) for t in common)

    if num_common == 0:
        return 0.0, 0.0, 0.0

    precision = num_common / len(pred_tokens)
    recall = num_common / len(gt_tokens)
    f1 = 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def score_single_document(
    predicted: dict[str, Any],
    ground_truth: dict[str, str],
    field_scores: dict[str, FieldScore],
) -> None:
    """Update field_scores in-place with results from one document."""
    for field_name in SROIE_FIELDS:
        if field_name not in field_scores:
            field_scores[field_name] = FieldScore(field=field_name)

        score = field_scores[field_name]
        score.total += 1

        pred_val = str(predicted.get(field_name) or "")
        gt_val = str(ground_truth.get(field_name) or "")

        # Exact match (normalized)
        if normalize_text(pred_val) == normalize_text(gt_val):
            score.exact_matches += 1

        # Token F1
        _, _, f1 = compute_token_f1(pred_val, gt_val)
        score.true_positives += f1
        score.false_positives += 1 - f1 if pred_val else 0
        score.false_negatives += 1 - f1 if gt_val else 0


def format_results_table(results: BenchmarkResults) -> str:
    """Format benchmark results as a markdown table."""
    lines = [
        "## SROIE Benchmark Results",
        "",
        f"**Documents evaluated**: {results.total_documents}  ",
        f"**Macro F1**: {results.macro_f1:.3f}  ",
        f"**Mean confidence**: {results.mean_confidence:.3f}  ",
        "",
        "| Field | Exact Match | Precision | Recall | F1 |",
        "|-------|------------|-----------|--------|-----|",
    ]
    for field_name in SROIE_FIELDS:
        if field_name in results.field_scores:
            s = results.field_scores[field_name]
            lines.append(
                f"| {field_name} | {s.exact_match_accuracy:.3f} | "
                f"{s.precision:.3f} | {s.recall:.3f} | {s.f1:.3f} |"
            )

    return "\n".join(lines)


def run_dry_run() -> BenchmarkResults:
    """Run scoring logic against synthetic SROIE-format fixtures.

    Validates the scoring pipeline without API calls.
    """
    fixtures = [
        {
            "predicted": {
                "company": "MYDIN MALL",
                "date": "17/11/2018",
                "address": "Lot 8, Jalan Bukit Kemuning",
                "total": "50.10",
            },
            "ground_truth": {
                "company": "MYDIN MALL",
                "date": "17/11/2018",
                "address": "Lot 8, Jalan Bukit Kemuning",
                "total": "50.10",
            },
            "confidence": 0.92,
        },
        {
            "predicted": {
                "company": "KEDAI RUNCIT",
                "date": "2018-12-01",  # format differs from GT
                "address": "No 12 Jalan Utama",
                "total": "25.50",
            },
            "ground_truth": {
                "company": "KEDAI RUNCIT MURAH",  # partial match
                "date": "01/12/2018",
                "address": "No 12 Jalan Utama",
                "total": "25.50",
            },
            "confidence": 0.78,
        },
        {
            "predicted": {
                "company": None,  # missed field
                "date": "15/09/2018",
                "address": "Plaza Masalam",
                "total": "12.30",
            },
            "ground_truth": {
                "company": "AEON CO (M) BHD",
                "date": "15/09/2018",
                "address": "Plaza Masalam",
                "total": "12.30",
            },
            "confidence": 0.65,
        },
    ]

    results = BenchmarkResults(total_documents=len(fixtures))
    for fixture in fixtures:
        score_single_document(
            fixture["predicted"],
            fixture["ground_truth"],
            results.field_scores,
        )
        results.confidence_scores.append(fixture["confidence"])

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DocExtract SROIE benchmark")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run scoring validation against synthetic fixtures (no API calls)",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("DOCEXTRACT_API_URL", "http://localhost:8000/api/v1"),
        help="DocExtract API URL",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("DOCEXTRACT_API_KEY", ""),
        help="DocExtract API key",
    )
    parser.add_argument(
        "--results-file",
        help="Load pre-computed results from JSON file instead of running extraction",
    )
    parser.add_argument(
        "--output",
        default="benchmark_results.json",
        help="Write results JSON to this file",
    )
    args = parser.parse_args(argv)

    if args.dry_run:
        print("Running dry-run with synthetic fixtures...")
        results = run_dry_run()
        print(format_results_table(results))
        print(f"\nDry run complete. Macro F1: {results.macro_f1:.3f}")
        return 0

    if args.results_file:
        with open(args.results_file) as f:
            data = json.load(f)
        # Reconstruct results from saved JSON
        results = BenchmarkResults(
            total_documents=data["total_documents"],
            confidence_scores=data.get("confidence_scores", []),
        )
        for field_name, scores in data.get("field_scores", {}).items():
            fs = FieldScore(field=field_name, **scores)
            results.field_scores[field_name] = fs
        print(format_results_table(results))
        return 0

    print("Live benchmark requires --dry-run or --results-file.")
    print("To run against live API, download the SROIE dataset and implement the extraction loop.")
    print("See docs/SROIE_BENCHMARK.md for setup instructions.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
