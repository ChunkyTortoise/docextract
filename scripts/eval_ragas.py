#!/usr/bin/env python3
"""
Ragas eval runner for DocExtract.

Computes faithfulness, answer_relevancy, and context_precision over the
golden set using Claude as the judge LLM (no OpenAI dependency).

Usage:
  python scripts/eval_ragas.py --golden evals/golden_set.jsonl --out eval_artifacts/ragas.json
  python scripts/eval_ragas.py --single invoice_01   # one case for debugging

Requires:
  pip install ragas>=0.4.3 langchain-anthropic>=0.3.0 datasets>=2.14.0
  ANTHROPIC_API_KEY env var

Output JSON:
  {
    "timestamp": "...",
    "case_count": 16,
    "metrics": {
      "faithfulness": 0.88,
      "answer_relevancy": 0.83,
      "context_precision": 0.79
    },
    "per_case": [{"id": "invoice_01", "faithfulness": 0.91, ...}, ...]
  }
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def load_jsonl(path: Path) -> list[dict]:
    cases = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = json.loads(line)
        if "_meta" in parsed:
            continue
        cases.append(parsed)
    return cases


def build_ragas_dataset(cases: list[dict]) -> "datasets.Dataset":
    """
    Build a Ragas-compatible Dataset from our golden JSONL format.

    Ragas expects columns: question, answer, contexts (list[str]), ground_truth.
    We map:
      question  → "Extract all fields from this {doc_type} document"
      answer    → expected_output serialized as JSON string
      contexts  → ground_truth_contexts (verbatim spans from input_text)
      ground_truth → expected_output as JSON string (same as answer for extraction)
    """
    import datasets

    rows = {
        "question": [],
        "answer": [],
        "contexts": [],
        "ground_truth": [],
        "case_id": [],
    }
    for case in cases:
        rows["question"].append(
            f"Extract all structured data from this {case['doc_type']} document."
        )
        rows["answer"].append(json.dumps(case["expected_output"]))
        # ground_truth_contexts are short spans — Ragas faithfulness scores against them
        ctx = case.get("ground_truth_contexts") or [case["input_text"][:200]]
        rows["contexts"].append(ctx)
        rows["ground_truth"].append(json.dumps(case["expected_output"]))
        rows["case_id"].append(case["id"])

    return datasets.Dataset.from_dict(rows)


def run_ragas_eval(cases: list[dict]) -> dict:
    """Run Ragas metrics and return scores dict."""
    try:
        from langchain_anthropic import ChatAnthropic
        from ragas import evaluate
        from ragas.metrics import answer_relevancy, context_precision, faithfulness
    except ImportError as e:
        print(f"ERROR: Missing dependency — {e}")
        print("Install: pip install ragas>=0.4.3 langchain-anthropic>=0.3.0 datasets>=2.14.0")
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY is not set", file=sys.stderr)
        sys.exit(1)

    # Use Claude as judge — avoids OpenAI dependency, keeps eval costs on one API
    judge_llm = ChatAnthropic(
        model="claude-haiku-4-5-20251001",  # cheapest capable model for judge
        temperature=0,
        anthropic_api_key=api_key,
    )

    dataset = build_ragas_dataset(cases)
    case_ids = dataset["case_id"]

    # Evaluate with the three core RAG metrics relevant to extraction
    result = evaluate(
        dataset.remove_columns(["case_id"]),  # Ragas doesn't want extra columns
        metrics=[faithfulness, answer_relevancy, context_precision],
        llm=judge_llm,
    )

    result_df = result.to_pandas()

    # Per-case breakdown
    per_case = []
    for i, case_id in enumerate(case_ids):
        row = result_df.iloc[i]
        per_case.append({
            "id": case_id,
            "faithfulness": round(float(row.get("faithfulness", 0)), 4),
            "answer_relevancy": round(float(row.get("answer_relevancy", 0)), 4),
            "context_precision": round(float(row.get("context_precision", 0)), 4),
        })

    def safe_mean(col: str) -> float:
        vals = result_df[col].dropna().tolist()
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    return {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "case_count": len(cases),
        "metrics": {
            "faithfulness": safe_mean("faithfulness"),
            "answer_relevancy": safe_mean("answer_relevancy"),
            "context_precision": safe_mean("context_precision"),
        },
        "per_case": per_case,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Ragas eval over DocExtract golden set")
    parser.add_argument("--golden", type=Path, default=REPO_ROOT / "evals" / "golden_set.jsonl")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "eval_artifacts" / "ragas.json")
    parser.add_argument("--single", type=str, default=None, help="Run only this case ID")
    parser.add_argument("--dry-run", action="store_true", help="Validate dataset, no API calls")
    args = parser.parse_args()

    cases = load_jsonl(args.golden)
    if args.single:
        cases = [c for c in cases if c["id"] == args.single]
        if not cases:
            print(f"Case {args.single!r} not found in {args.golden}")
            sys.exit(1)

    print(f"Running Ragas eval on {len(cases)} cases...", file=sys.stderr)

    if args.dry_run:
        print("Dry run — validating dataset shape only")
        ds = build_ragas_dataset(cases)
        print(f"Dataset columns: {ds.column_names}")
        print(f"Dataset size: {len(ds)}")
        return

    scores = run_ragas_eval(cases)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(scores, indent=2))

    print(f"\nRagas results ({scores['case_count']} cases):")
    for metric, val in scores["metrics"].items():
        print(f"  {metric}: {val:.4f}")
    print(f"\nWritten to {args.out}")


if __name__ == "__main__":
    main()
