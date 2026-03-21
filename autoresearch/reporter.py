"""Report generation for eval results."""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autoresearch.eval import CaseResult

RESULTS_PATH = Path(__file__).parent / "results.tsv"


def generate_report(
    case_results: list["CaseResult"],
    overall_score: float,
    format: str = "json",
) -> str:
    """Generate a report from eval case results.

    Args:
        case_results: List of CaseResult objects
        overall_score: Overall weighted score
        format: "json" or "markdown"

    Returns:
        Formatted report string
    """
    if format == "markdown":
        return _markdown_report(case_results, overall_score)
    return _json_report(case_results, overall_score)


def compare_runs(
    current_results: list["CaseResult"],
    previous_score: float,
) -> str:
    """Generate a markdown delta table comparing current vs previous run.

    Args:
        current_results: CaseResult objects from current run
        previous_score: Overall score from previous run

    Returns:
        Markdown delta table
    """
    if not current_results:
        return "No results to compare."

    current_score = sum(r.score * r.weight for r in current_results) / sum(r.weight for r in current_results)
    delta = current_score - previous_score
    sign = "+" if delta >= 0 else ""

    lines = [
        "## Eval Comparison",
        "",
        f"| Metric | Previous | Current | Delta |",
        f"|--------|----------|---------|-------|",
        f"| Overall Score | {previous_score:.4f} | {current_score:.4f} | {sign}{delta:.4f} |",
        f"| Cases | - | {len(current_results)} | - |",
        "",
        "### Per-Case Results",
        "",
        "| Case ID | Doc Type | Score | Completeness | Hallucinations | Format Valid |",
        "|---------|----------|-------|-------------|----------------|--------------|",
    ]

    for r in sorted(current_results, key=lambda x: x.score):
        lines.append(
            f"| {r.case_id} | {r.doc_type} | {r.score:.3f} | {r.completeness:.3f} | {r.hallucination_count} | {'yes' if r.format_valid else 'no'} |"
        )

    return "\n".join(lines)


def _json_report(case_results: list["CaseResult"], overall_score: float) -> str:
    data = {
        "overall_score": overall_score,
        "case_count": len(case_results),
        "cases": [
            {
                "case_id": r.case_id,
                "doc_type": r.doc_type,
                "score": r.score,
                "weight": r.weight,
                "completeness": r.completeness,
                "hallucination_count": r.hallucination_count,
                "format_valid": r.format_valid,
            }
            for r in case_results
        ],
    }
    return json.dumps(data, indent=2)


def _markdown_report(case_results: list["CaseResult"], overall_score: float) -> str:
    lines = [
        f"# Eval Report",
        f"",
        f"**Overall Score:** {overall_score:.4f}",
        f"**Cases Evaluated:** {len(case_results)}",
        f"",
        "| Case ID | Doc Type | Score | Completeness | Hallucinations | Format Valid |",
        "|---------|----------|-------|-------------|----------------|--------------|",
    ]
    for r in case_results:
        lines.append(
            f"| {r.case_id} | {r.doc_type} | {r.score:.3f} | {r.completeness:.3f} | {r.hallucination_count} | {'yes' if r.format_valid else 'no'} |"
        )
    return "\n".join(lines)
