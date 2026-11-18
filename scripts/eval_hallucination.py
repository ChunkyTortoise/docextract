"""Hallucination (faithfulness) scoring over the committed replay fixtures.

Scores every recorded extraction in ``autoresearch/golden_responses/`` against the
source document it was extracted from, claim by claim (see
``autoresearch/grounding.py`` for the matching rules). No API key, no network.

Two tiers:

* **Deterministic (default, runs in CI).** Each case runs through a DeepEval
  custom metric, ``FieldGroundingMetric`` (a ``deepeval.metrics.BaseMetric``),
  over an ``LLMTestCase`` whose ``retrieval_context`` is the source document.
  If ``deepeval`` is not installed (the lean CI image), the same scorer runs
  directly; the numbers are identical and the artifact records which engine ran.

* **LLM judge (``--judge``, optional).** Also runs DeepEval's built-in
  ``FaithfulnessMetric`` and ``HallucinationMetric`` on the same test cases.
  Needs a judge model key (``ANTHROPIC_API_KEY`` or ``OPENAI_API_KEY``) and
  costs money per run; without a key it is skipped and reported as skipped.

Also runs a **detection self-test**: for every fixture with claims, plant one
fabricated string and one wrong number and check the scorer flags both. This
measures that the metric catches hallucinations, not only that clean data passes.

Fails (exit 1) if:
  * fewer than --min-cases fixtures are scored
  * the claim-level hallucination rate exceeds --max-rate
  * the self-test misses any planted hallucination

Run:  python scripts/eval_hallucination.py [--judge] [--verbose]
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from autoresearch.grounding import (  # noqa: E402
    NORMALIZED_FIELDS,
    GroundingResult,
    iter_claims,
    score_grounding,
)

DATASET = REPO / "autoresearch" / "eval_dataset_72.json"
FIXTURE_DIR = REPO / "autoresearch" / "golden_responses"

FABRICATED_STRING = "Zephyrine Holdings Ltd"


# ---------------------------------------------------------------------------
# DeepEval wrapper (optional dependency)
# ---------------------------------------------------------------------------


def _make_deepeval_metric() -> Any | None:
    try:
        from deepeval.metrics import BaseMetric
        from deepeval.test_case import LLMTestCase  # noqa: F401
    except ImportError:
        return None

    class FieldGroundingMetric(BaseMetric):
        """Deterministic faithfulness: share of extracted field values found in the source."""

        def __init__(self, threshold: float = 0.9) -> None:
            self.threshold = threshold
            self.include_reason = True
            self.async_mode = False
            self.strict_mode = False
            self.evaluation_model = "deterministic (no LLM)"
            self.result: GroundingResult | None = None

        def measure(self, test_case, *args, **kwargs) -> float:  # type: ignore[override]
            extraction = json.loads(test_case.actual_output) if test_case.actual_output else {}
            source = "\n".join(test_case.retrieval_context or [])
            self.result = score_grounding(extraction, source)
            self.score = self.result.faithfulness
            self.success = self.score >= self.threshold
            bad = self.result.unsupported
            self.reason = (
                "All extracted values are grounded in the source."
                if not bad
                else "Unsupported: " + "; ".join(f"{c.path}={c.value!r}" for c in bad)
            )
            return self.score

        async def a_measure(self, test_case, *args, **kwargs) -> float:  # type: ignore[override]
            return self.measure(test_case)

        def is_successful(self) -> bool:
            return bool(self.success)

        @property
        def __name__(self) -> str:  # DeepEval reads the metric name from here
            return "Field Grounding (faithfulness)"

    return FieldGroundingMetric


def _test_case(case: dict, extraction: dict) -> Any:
    from deepeval.test_case import LLMTestCase

    return LLMTestCase(
        input=f"Extract the {case['doc_type']} fields from this document as JSON.",
        actual_output=json.dumps(extraction),
        retrieval_context=[case["input_text"]],
        context=[case["input_text"]],
    )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _score(case: dict, extraction: dict, metric_cls: Any | None) -> GroundingResult:
    if metric_cls is None:
        return score_grounding(extraction, case["input_text"])
    metric = metric_cls()
    metric.measure(_test_case(case, extraction))
    assert metric.result is not None
    return metric.result


def _plant(extraction: dict, kind: str) -> tuple[dict, str] | None:
    """Return a copy with one fabricated value of the given kind, plus its path."""
    for path, key, value in iter_claims(extraction):
        if key in NORMALIZED_FIELDS:
            continue
        if kind == "string" and isinstance(value, str) and not value[:4].isdigit():
            planted, new = copy.deepcopy(extraction), FABRICATED_STRING
        elif kind == "number" and isinstance(value, int | float) and not isinstance(value, bool):
            planted, new = copy.deepcopy(extraction), round(float(value) * 1.37 + 11.11, 2)
        else:
            continue
        _set_path(planted, path, new)
        return planted, path
    return None


def _set_path(obj: Any, path: str, new: Any) -> None:
    import re

    parts = re.findall(r"[^.\[\]]+|\[\d+\]", path)
    for p in parts[:-1]:
        obj = obj[int(p[1:-1])] if p.startswith("[") else obj[p]
    last = parts[-1]
    if last.startswith("["):
        obj[int(last[1:-1])] = new
    else:
        obj[last] = new


def _judge(cases: list[tuple[dict, dict]]) -> dict:
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")):
        return {"status": "skipped", "reason": "no ANTHROPIC_API_KEY or OPENAI_API_KEY set"}
    try:
        from deepeval.metrics import FaithfulnessMetric, HallucinationMetric
    except ImportError:
        return {"status": "skipped", "reason": "deepeval not installed"}

    model: Any = None
    if os.getenv("ANTHROPIC_API_KEY") and not os.getenv("OPENAI_API_KEY"):
        from deepeval.models import AnthropicModel

        model = AnthropicModel(model=os.getenv("DEEPEVAL_JUDGE_MODEL", "claude-haiku-4-5"))

    rows = []
    for case, extraction in cases:
        tc = _test_case(case, extraction)
        faith = FaithfulnessMetric(threshold=0.7, model=model, async_mode=False)
        hall = HallucinationMetric(threshold=0.5, model=model, async_mode=False)
        faith.measure(tc)
        hall.measure(tc)
        rows.append({"id": case["id"], "faithfulness": faith.score, "hallucination": hall.score})
    n = len(rows) or 1
    return {
        "status": "ran",
        "model": getattr(model, "name", None) or "deepeval default",
        "mean_faithfulness": round(sum(r["faithfulness"] for r in rows) / n, 4),
        "mean_hallucination": round(sum(r["hallucination"] for r in rows) / n, 4),
        "per_case": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--max-rate", type=float, default=0.05, help="max claim-level hallucination rate"
    )
    ap.add_argument("--min-cases", type=int, default=28)
    ap.add_argument(
        "--judge", action="store_true", help="also run DeepEval LLM-judge metrics (needs a key)"
    )
    ap.add_argument("--verbose", action="store_true", help="print every unsupported claim")
    ap.add_argument("--out", default="eval_artifacts/hallucination.json")
    args = ap.parse_args()

    metric_cls = _make_deepeval_metric()
    engine = (
        "deepeval.BaseMetric (FieldGroundingMetric)"
        if metric_cls
        else "autoresearch.grounding (deepeval not installed)"
    )

    dataset = json.loads(DATASET.read_text())
    per_case: list[dict] = []
    replayed: list[tuple[dict, dict]] = []
    match_counts: dict[str, int] = {}
    for case in dataset:
        fx = FIXTURE_DIR / f"{case['id']}.json"
        if not fx.exists():
            continue
        extraction = json.loads(fx.read_text()).get("parsed_extraction") or {}
        replayed.append((case, extraction))
        r = _score(case, extraction, metric_cls)
        for c in r.scored:
            k = c.match or "unsupported"
            match_counts[k] = match_counts.get(k, 0) + 1
        per_case.append(
            {
                "id": case["id"],
                "split": case["split"],
                "doc_type": case["doc_type"],
                "claims_scored": len(r.scored),
                "claims_unscored": len(r.claims) - len(r.scored),
                "faithfulness": round(r.faithfulness, 4),
                "unsupported": [{"path": c.path, "value": c.value} for c in r.unsupported],
            }
        )

    scored = sum(c["claims_scored"] for c in per_case)
    unsupported = sum(len(c["unsupported"]) for c in per_case)
    rate = unsupported / scored if scored else 0.0
    clean = sum(1 for c in per_case if not c["unsupported"])

    # Self-test: planted hallucinations must be caught.
    planted = caught = 0
    misses: list[str] = []
    for case, extraction in replayed:
        for kind in ("string", "number"):
            p = _plant(extraction, kind)
            if p is None:
                continue
            mutated, path = p
            planted += 1
            r = _score(case, mutated, metric_cls)
            if any(c.path == path for c in r.unsupported):
                caught += 1
            else:
                misses.append(f"{case['id']}:{path}")

    summary = {
        "engine": engine,
        "cases": len(per_case),
        "cases_fully_grounded": clean,
        "claims_scored": scored,
        "claims_unsupported": unsupported,
        "faithfulness_claim_level": round(1 - rate, 4),
        "hallucination_rate_claim_level": round(rate, 4),
        "faithfulness_mean_per_case": round(
            sum(c["faithfulness"] for c in per_case) / len(per_case), 4
        )
        if per_case
        else None,
        "match_breakdown": dict(sorted(match_counts.items())),
        "self_test": {"planted": planted, "caught": caught, "misses": misses},
        "max_rate": args.max_rate,
        "per_case": per_case,
    }
    if args.judge:
        summary["llm_judge"] = _judge(replayed)

    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, default=str))

    print(f"engine: {engine}")
    print(
        f"{len(per_case)} cases, {scored} claims scored: faithfulness {1 - rate:.4f}, "
        f"hallucination rate {rate:.4f} ({unsupported} unsupported); {clean}/{len(per_case)} cases fully grounded"
    )
    print(f"match breakdown: {summary['match_breakdown']}")
    print(f"self-test: caught {caught}/{planted} planted hallucinations")
    for c in per_case:
        if c["unsupported"] and args.verbose:
            for u in c["unsupported"]:
                print(f"  {c['id']}: {u['path']} = {u['value']!r}")
    if args.judge:
        print(
            f"llm judge: {json.dumps({k: v for k, v in summary['llm_judge'].items() if k != 'per_case'})}"
        )

    if len(per_case) < args.min_cases:
        print(f"\nFAIL: only {len(per_case)} fixtures scored; need >= {args.min_cases}")
        return 1
    if rate > args.max_rate:
        print(f"\nFAIL: hallucination rate {rate:.4f} > max {args.max_rate}")
        return 1
    if caught != planted:
        print(f"\nFAIL: self-test missed {planted - caught} planted hallucinations: {misses}")
        return 1
    print(f"\nPASS: hallucination rate {rate:.4f} <= {args.max_rate}; self-test {caught}/{planted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
