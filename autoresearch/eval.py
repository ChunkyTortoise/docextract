"""Autoresearch eval harness: load dataset, run extraction, score against ground truth.

Usage:
    python -m autoresearch.eval [--prompts PATH] [--dry-run]

Exit codes:
    0  — eval completed, score printed to stdout
    1  — eval failed (API error, bad config, etc.)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

DATASET_PATH = Path(__file__).parent / "eval_dataset.json"
RESULTS_PATH = Path(__file__).parent / "results.tsv"


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _levenshtein(a: str, b: str) -> int:
    """Compute edit distance between two strings."""
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            curr[j] = min(
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + (0 if ca == cb else 1),
            )
        prev = curr
    return prev[len(b)]


def _string_similarity(a: str, b: str) -> float:
    """Normalized Levenshtein similarity (0.0–1.0)."""
    if not a and not b:
        return 1.0
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    return 1.0 - _levenshtein(a, b) / max_len


def _score_scalar(extracted: Any, expected: Any) -> float:
    """Score a single non-list field."""
    if expected is None:
        return 1.0 if extracted is None else 0.5  # null expected — partial credit

    if extracted is None:
        return 0.0  # null when expected

    # Numeric comparison
    if isinstance(expected, (int, float)):
        try:
            ext_val = float(extracted)
            if expected == 0:
                return 1.0 if ext_val == 0 else 0.0
            return 1.0 if abs(ext_val - expected) / abs(expected) <= 0.01 else 0.0
        except (TypeError, ValueError):
            return 0.0

    # String comparison
    return _string_similarity(str(extracted).strip(), str(expected).strip())


def _score_list_item(extracted_item: dict, expected_item: dict) -> float:
    """Score one list item against an expected item (best-effort field match)."""
    if not expected_item:
        return 1.0
    scores = []
    for key, exp_val in expected_item.items():
        if exp_val is None:
            continue
        ext_val = extracted_item.get(key) if extracted_item else None
        scores.append(_score_scalar(ext_val, exp_val))
    return sum(scores) / len(scores) if scores else 0.0


def _score_list(extracted: Any, expected: list) -> float:
    """Best-pair alignment: each expected item matched to best extracted item."""
    if not expected:
        return 1.0
    if not extracted or not isinstance(extracted, list):
        return 0.0

    total = 0.0
    for exp_item in expected:
        best = max(
            (_score_list_item(ext_item, exp_item) for ext_item in extracted),
            default=0.0,
        )
        total += best
    return total / len(expected)


def score_extraction(extracted: dict[str, Any], expected: dict[str, Any], critical_fields: list[str]) -> float:
    """Compute weighted field-level accuracy.

    Critical fields weighted 2x. Returns scalar 0.0–1.0.
    """
    total_weight = 0.0
    total_score = 0.0

    for key, exp_val in expected.items():
        weight = 2.0 if key in critical_fields else 1.0

        if isinstance(exp_val, list):
            ext_val = extracted.get(key, [])
            field_score = _score_list(ext_val, exp_val)
        else:
            ext_val = extracted.get(key)
            field_score = _score_scalar(ext_val, exp_val)

        total_weight += weight
        total_score += weight * field_score

    if total_weight == 0:
        return 0.0
    return total_score / total_weight


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------

def load_dataset(path: Path = DATASET_PATH) -> list[dict]:
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Dry-run mock extraction
# ---------------------------------------------------------------------------

def _mock_extraction(case: dict) -> dict[str, Any]:
    """Return a plausible but imperfect extraction for dry-run mode."""
    expected = case["expected"]
    mock: dict[str, Any] = {}
    for key, val in expected.items():
        if isinstance(val, list):
            # Return items with half the fields filled
            mock_items = []
            for item in val:
                mock_item = {k: v for i, (k, v) in enumerate(item.items()) if i % 2 == 0}
                mock_items.append(mock_item)
            mock[key] = mock_items
        elif isinstance(val, (int, float)):
            mock[key] = val  # perfect numeric match
        elif isinstance(val, str) and len(val) > 4:
            mock[key] = val[:-2] + "XX"  # slight string degradation
        else:
            mock[key] = val
    return mock


# ---------------------------------------------------------------------------
# Eval runner
# ---------------------------------------------------------------------------

async def run_eval(
    dataset: list[dict],
    dry_run: bool = False,
    semaphore_limit: int = 3,
) -> float:
    """Run all eval cases, return weighted mean accuracy score."""
    from app.services.claude_extractor import extract

    sem = asyncio.Semaphore(semaphore_limit)

    async def _eval_case(case: dict) -> tuple[float, float]:
        """Returns (score, weight)."""
        async with sem:
            if dry_run:
                extracted = _mock_extraction(case)
            else:
                result = await extract(case["input_text"], case["doc_type"])
                extracted = result.data

        score = score_extraction(extracted, case["expected"], case["critical_fields"])
        return score, case.get("weight", 1.0)

    tasks = [_eval_case(case) for case in dataset]
    results = await asyncio.gather(*tasks)

    total_score = sum(s * w for s, w in results)
    total_weight = sum(w for _, w in results)
    return total_score / total_weight if total_weight > 0 else 0.0


def _append_result(score: float, prompts_path: Path) -> None:
    """Append a result line to results.tsv."""
    import datetime

    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    header_needed = not RESULTS_PATH.exists()
    with open(RESULTS_PATH, "a") as f:
        if header_needed:
            f.write("timestamp\tscore\tprompts_path\n")
        f.write(f"{timestamp}\t{score:.6f}\t{prompts_path}\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Docextract prompt eval harness")
    parser.add_argument(
        "--prompts",
        type=Path,
        default=None,
        help="Path to prompts.yaml (default: autoresearch/prompts.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use mock extractions instead of calling Claude API",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DATASET_PATH,
        help="Path to eval_dataset.json",
    )
    args = parser.parse_args()

    # Load dataset
    dataset = load_dataset(args.dataset)
    print(f"Loaded {len(dataset)} eval cases", file=sys.stderr)

    # Run eval
    score = asyncio.run(run_eval(dataset, dry_run=args.dry_run))

    prompts_path = args.prompts or (Path(__file__).parent / "prompts.yaml")
    _append_result(score, prompts_path)

    print(f"SCORE: {score:.6f}")


if __name__ == "__main__":
    main()
