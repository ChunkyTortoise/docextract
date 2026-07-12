"""Braintrust experiment over the docextract golden corpus.

Mirrors scripts/eval_offline_replay.py's data model: pairs eval_dataset_72.json
cases with the committed autoresearch/golden_responses/<id>.json fixtures
(recorded extractor outputs). Default mode is offline and deterministic (no API
calls, no cost) and logs a Braintrust experiment scored by the same field-F1
scorer the CI offline gate uses (autoresearch.eval.score_extraction). The
optional --judge flag adds the in-repo LLMJudge rubric as a second scorer
(needs an API key + LLM_JUDGE_ENABLED=true).

Only the curated synthetic corpus (fake "Acme Corp" invoices) is sent to
Braintrust; no live client documents flow through this script.

Usage:
    export BRAINTRUST_API_KEY=...
    python scripts/eval_braintrust.py                 # log offline experiment
    python scripts/eval_braintrust.py --judge         # + LLM-judge scorer
    python scripts/eval_braintrust.py --dry-run       # score locally, no upload
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from autoresearch.eval import score_extraction  # noqa: E402

DATASET = REPO / "autoresearch" / "eval_dataset_72.json"
FIXTURE_DIR = REPO / "autoresearch" / "golden_responses"

_JUDGE_RUBRIC = (
    "Score how faithfully the extracted JSON captures the document's key fields "
    "compared with the expected extraction. 1.0 = every critical field matches; "
    "lower as fields are missing, wrong, or hallucinated."
)


def load_cases() -> list[dict]:
    """Return the fixture-backed cases (case + recorded parsed_extraction)."""
    dataset = json.loads(DATASET.read_text())
    cases: list[dict] = []
    for case in dataset:
        fx = FIXTURE_DIR / f"{case['id']}.json"
        if not fx.exists():
            continue
        parsed = json.loads(fx.read_text()).get("parsed_extraction", {}) or {}
        cases.append({"case": case, "parsed": parsed})
    return cases


def build_dataset(cases: list[dict]) -> list[dict]:
    """Braintrust rows: {input, expected, metadata}."""
    rows = []
    for c in cases:
        case = c["case"]
        rows.append(
            {
                "input": {"id": case["id"], "text": case["input_text"]},
                "expected": case["expected"],
                "metadata": {
                    "id": case["id"],
                    "doc_type": case["doc_type"],
                    "split": case.get("split"),
                    "weight": case.get("weight", 1.0),
                    "critical_fields": case.get("critical_fields", []),
                },
            }
        )
    return rows


def make_field_f1(crit_by_id: dict[str, list[str]]):
    """Deterministic field-F1 scorer, reusing the CI offline gate's scorer."""

    def field_f1(input, output, expected, **_):  # noqa: A002 - braintrust arg names
        crit = crit_by_id.get(input["id"], [])
        return score_extraction(output or {}, expected or {}, crit)

    return field_f1


def make_llm_judge():
    """LLMJudge-rubric scorer (async). Returns None when the judge is disabled."""
    from app.services.llm_judge import LLMJudge

    judge = LLMJudge()

    async def llm_judge(input, output, expected, **_):  # noqa: A002
        result = await judge.evaluate(
            question=input["text"],
            answer=json.dumps(output, default=str),
            contexts=[input["text"], json.dumps(expected, default=str)],
            rubric=_JUDGE_RUBRIC,
        )
        return result.score if result is not None else None

    return llm_judge


def run_dry(cases: list[dict], crit_by_id: dict[str, list[str]]) -> int:
    """Score every case locally with field-F1 and print an aggregate. No upload."""
    scorer = make_field_f1(crit_by_id)
    rows = build_dataset(cases)
    parsed_by_id = {c["case"]["id"]: c["parsed"] for c in cases}
    total_w = 0.0
    acc = 0.0
    for row in rows:
        cid = row["input"]["id"]
        s = scorer(row["input"], parsed_by_id.get(cid, {}), row["expected"])
        w = row["metadata"]["weight"]
        total_w += w
        acc += s * w
        print(f"  {cid:32s} f1={s:.3f}")
    combined = acc / total_w if total_w else 0.0
    print(json.dumps({"replayed": len(rows), "field_f1_weighted": round(combined, 4)}, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--judge", action="store_true", help="add the LLMJudge scorer (needs API key)")
    ap.add_argument("--dry-run", action="store_true", help="score locally, do not upload")
    ap.add_argument("--experiment", default=None, help="Braintrust experiment name")
    args = ap.parse_args()

    cases = load_cases()
    if not cases:
        print("No fixture-backed cases found; nothing to evaluate.", file=sys.stderr)
        return 1
    crit_by_id = {c["case"]["id"]: c["case"].get("critical_fields", []) for c in cases}

    if args.dry_run:
        return run_dry(cases, crit_by_id)

    import os

    if not os.environ.get("BRAINTRUST_API_KEY"):
        print("BRAINTRUST_API_KEY not set. Use --dry-run to score locally.", file=sys.stderr)
        return 2

    from braintrust import Eval

    parsed_by_id = {c["case"]["id"]: c["parsed"] for c in cases}

    def task(input):  # noqa: A002 - offline replay of the recorded extraction
        return parsed_by_id.get(input["id"], {})

    scores = [make_field_f1(crit_by_id)]
    if args.judge:
        scores.append(make_llm_judge())

    project = os.environ.get("BRAINTRUST_PROJECT", "docextract")
    Eval(
        project,
        data=lambda: build_dataset(cases),
        task=task,
        scores=scores,
        experiment_name=args.experiment,
        metadata={"mode": "offline-replay", "corpus": "eval_dataset_72", "replayed": len(cases)},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
