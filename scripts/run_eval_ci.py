"""CI eval regression gate for docextract.

Runs the golden eval harness (no API calls required) and enforces that the
overall accuracy score has not regressed beyond REGRESSION_TOLERANCE from a
stored baseline. Exits with code 1 on regression so GitHub Actions blocks the PR.

Usage:
    python scripts/run_eval_ci.py           # check regression
    python scripts/run_eval_ci.py --update-baseline   # accept current score as new baseline
    python scripts/run_eval_ci.py --ci      # same as default but prints GitHub-flavoured output
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from autoresearch.eval import (
    CaseResult,
    brier_score,
    calibration_curve,
    load_dataset,
    model_comparison_table,
    run_eval,
)

DATASET_PATH = Path(__file__).parent.parent / "autoresearch" / "eval_dataset.json"
BASELINE_PATH = Path(__file__).parent.parent / "autoresearch" / "baseline.json"

# A score drop beyond this threshold fails CI
REGRESSION_TOLERANCE: float = 0.02


# ---------------------------------------------------------------------------
# Baseline I/O
# ---------------------------------------------------------------------------

def load_baseline(path: Path = BASELINE_PATH) -> dict | None:
    """Load baseline JSON. Returns None if file missing or invalid."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_baseline(
    overall_score: float,
    case_results: list[CaseResult],
    path: Path = BASELINE_PATH,
) -> None:
    """Persist current score as the new baseline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    per_doc: dict[str, dict] = {}
    for r in case_results:
        bucket = per_doc.setdefault(r.doc_type, {"scores": [], "count": 0})
        bucket["scores"].append(r.score)
        bucket["count"] += 1

    data = {
        "overall_score": round(overall_score, 6),
        "case_count": len(case_results),
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "per_doc_type": {
            dt: {
                "score": round(sum(v["scores"]) / len(v["scores"]), 4),
                "count": v["count"],
            }
            for dt, v in per_doc.items()
        },
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Regression check
# ---------------------------------------------------------------------------

def check_regression(
    current_score: float,
    baseline_score: float | None,
) -> tuple[bool, float]:
    """Return (passed, delta). Passed when current >= baseline - tolerance."""
    if baseline_score is None:
        return True, 0.0
    delta = round(current_score - baseline_score, 10)
    passed = delta >= -REGRESSION_TOLERANCE
    return passed, delta


# ---------------------------------------------------------------------------
# Markdown summary
# ---------------------------------------------------------------------------

def build_markdown_summary(
    overall_score: float,
    case_results: list[CaseResult],
    baseline_score: float | None,
    passed: bool,
) -> str:
    """Build a markdown CI summary for stdout / GitHub step summary."""
    status = "✅ PASS" if passed else "❌ FAIL"

    if baseline_score is None:
        delta_str = "N/A (first run — baseline established)"
        baseline_str = "N/A"
    else:
        delta = overall_score - baseline_score
        sign = "+" if delta >= 0 else ""
        delta_str = f"{sign}{delta:.4f}"
        baseline_str = f"{baseline_score:.4f}"

    # Aggregate per doc type
    type_stats: dict[str, list[float]] = {}
    for r in case_results:
        type_stats.setdefault(r.doc_type, []).append(r.score)

    type_rows = "\n".join(
        f"| {dt} | {len(scores)} | {sum(scores)/len(scores):.3f} |"
        for dt, scores in sorted(type_stats.items())
    )

    completeness_vals = [r.completeness for r in case_results]
    avg_completeness = sum(completeness_vals) / len(completeness_vals) if completeness_vals else 0.0
    hallucinations = sum(r.hallucination_count for r in case_results)
    format_ok = sum(1 for r in case_results if r.format_valid)

    # Calibration metrics
    bs = brier_score(case_results)
    cal_curve = calibration_curve(case_results)
    cal_rows = "\n".join(
        f"| {b['bin_lower']:.2f}-{b['bin_upper']:.2f} | {b['avg_confidence']:.3f} | {b['avg_accuracy']:.3f} | {b['count']} |"
        for b in cal_curve
    ) if cal_curve else "| - | - | - | 0 |"

    # Model comparison
    model_rows_data = model_comparison_table(case_results)
    model_rows = "\n".join(
        f"| {r['model']} | {r['doc_type']} | {r['count']} | {r['accuracy']:.3f} | {r['avg_confidence']:.3f} | {r['avg_input_tokens']} | {r['avg_output_tokens']} | ${r['est_cost_usd']:.4f} |"
        for r in model_rows_data
    ) if model_rows_data else "| - | - | - | - | - | - | - | - |"

    return f"""## Eval Regression Gate — {status}

| Metric | Value |
|--------|-------|
| **Overall Score** | {overall_score:.4f} |
| **Baseline** | {baseline_str} |
| **Delta** | {delta_str} |
| **Tolerance** | ±{REGRESSION_TOLERANCE:.2f} |
| **Cases** | {len(case_results)} |
| **Avg Completeness** | {avg_completeness:.3f} |
| **Hallucinations** | {hallucinations} |
| **Format Valid** | {format_ok}/{len(case_results)} |
| **Brier Score** | {bs:.4f} |

### Per-Doc-Type Accuracy

| Doc Type | Cases | Score |
|----------|-------|-------|
{type_rows}

### Confidence Calibration

| Bin | Avg Confidence | Avg Accuracy | Count |
|-----|---------------|-------------|-------|
{cal_rows}

### Model Cost/Accuracy Comparison

| Model | Doc Type | Cases | Accuracy | Confidence | Avg In Tokens | Avg Out Tokens | Est Cost |
|-------|----------|-------|----------|-----------|---------------|----------------|----------|
{model_rows}
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Docextract eval CI regression gate")
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Write current score as the new baseline and exit 0",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="Enable CI-friendly output (same behaviour, explicit flag for clarity)",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DATASET_PATH,
        help="Path to eval_dataset.json",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=BASELINE_PATH,
        help="Path to baseline.json",
    )
    args = parser.parse_args()

    dataset = load_dataset(args.dataset)
    print(f"Loaded {len(dataset)} eval cases (golden mode — no API calls)", file=sys.stderr)

    overall_score, case_results = asyncio.run(run_eval(dataset, golden=True))

    baseline = load_baseline(args.baseline)
    baseline_score = baseline["overall_score"] if baseline else None

    if args.update_baseline:
        save_baseline(overall_score, case_results, args.baseline)
        print(f"Baseline updated: {overall_score:.4f} ({len(case_results)} cases)")
        return 0

    passed, delta = check_regression(overall_score, baseline_score)
    summary = build_markdown_summary(overall_score, case_results, baseline_score, passed)
    print(summary)

    if baseline_score is None:
        # First run: auto-save baseline
        save_baseline(overall_score, case_results, args.baseline)
        print(f"Baseline established: {overall_score:.4f}", file=sys.stderr)

    if not passed:
        print(
            f"\nREGRESSION: score {overall_score:.4f} dropped {abs(delta):.4f} "
            f"below baseline {baseline_score:.4f} (tolerance {REGRESSION_TOLERANCE:.2f})",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
