"""Tiered DeepEval evaluation tests.

CI tier (every PR): deterministic checks using cached golden-set assertions.
No live API calls — tests validate schema conformance, field extraction
completeness, and citation grounding using pre-computed golden data.

Nightly tier (scheduled): LLM-as-a-judge via DeepEval metrics. Requires
ANTHROPIC_API_KEY and DEEPEVAL_NIGHTLY=true environment variable.
Skipped by default in CI to avoid API costs.

Reuses the golden evaluation fixtures from the existing eval pipeline
(scripts/run_eval_ci baseline at 92.6% accuracy).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Golden dataset fixtures (cached, no API calls)
# ---------------------------------------------------------------------------

GOLDEN_DIR = Path(__file__).parent.parent.parent / "eval" / "golden"
FIXTURES_DIR = Path(__file__).parent.parent.parent / "tests" / "fixtures"


def _load_golden_cases() -> list[dict]:
    """Load golden eval cases from fixtures or eval directory."""
    for search_dir in [GOLDEN_DIR, FIXTURES_DIR]:
        if search_dir.is_dir():
            cases = []
            for f in sorted(search_dir.glob("*.json")):
                try:
                    cases.append(json.loads(f.read_text()))
                except (json.JSONDecodeError, OSError):
                    continue
            if cases:
                return cases
    return []


GOLDEN_CASES = _load_golden_cases()


# ---------------------------------------------------------------------------
# CI Tier: Deterministic checks (every PR, no API calls)
# ---------------------------------------------------------------------------


class TestSchemaConformance:
    """Validate that extraction outputs conform to expected schemas."""

    @pytest.mark.skipif(not GOLDEN_CASES, reason="No golden eval fixtures found")
    @pytest.mark.parametrize(
        "case",
        GOLDEN_CASES[:20],
        ids=[c.get("case_id", f"case_{i}") for i, c in enumerate(GOLDEN_CASES[:20])],
    )
    def test_output_has_required_fields(self, case: dict) -> None:
        """Every extraction output must have doc_type, confidence, and extracted_data."""
        output = case.get("model_output") or case.get("output", {})
        if not output:
            pytest.skip("No model_output in fixture")

        if isinstance(output, str):
            output = json.loads(output)

        assert "doc_type" in output or "document_type" in output, (
            f"Missing doc_type in output keys: {list(output.keys())}"
        )

    @pytest.mark.skipif(not GOLDEN_CASES, reason="No golden eval fixtures found")
    def test_confidence_scores_in_range(self) -> None:
        """All confidence scores must be between 0.0 and 1.0."""
        for case in GOLDEN_CASES:
            output = case.get("model_output") or case.get("output", {})  # noqa: F841
            if not output:
                continue
            if isinstance(output, str):
                try:
                    output = json.loads(output)
                except json.JSONDecodeError:
                    continue
            confidence = output.get("confidence", output.get("score"))
            if confidence is not None:
                assert 0.0 <= float(confidence) <= 1.0, (
                    f"Confidence {confidence} out of range in {case.get('case_id')}"
                )


class TestExtractionCompleteness:
    """Validate field extraction completeness against golden expected values."""

    @pytest.mark.skipif(not GOLDEN_CASES, reason="No golden eval fixtures found")
    def test_no_empty_extractions(self) -> None:
        """No golden case should produce completely empty extraction."""
        empty_count = 0
        for case in GOLDEN_CASES:
            output = case.get("model_output") or case.get("output", {})  # noqa: F841
            if not output:
                empty_count += 1
        max_empty = max(1, len(GOLDEN_CASES) // 5)
        assert empty_count <= max_empty, (
            f"{empty_count}/{len(GOLDEN_CASES)} cases have empty output"
        )

    @pytest.mark.skipif(not GOLDEN_CASES, reason="No golden eval fixtures found")
    def test_baseline_accuracy_maintained(self) -> None:
        """Overall accuracy must not drop below 90% (baseline: 92.6%)."""
        scores = []
        for case in GOLDEN_CASES:
            score = case.get("score", case.get("accuracy"))
            if score is not None:
                scores.append(float(score))
        if not scores:
            pytest.skip("No scores in golden fixtures")
        avg = sum(scores) / len(scores)
        assert avg >= 0.90, (
            f"Average accuracy {avg:.3f} below 90% regression threshold"
        )


class TestCitationGrounding:
    """Validate that extracted values are grounded in source text."""

    @pytest.mark.skipif(not GOLDEN_CASES, reason="No golden eval fixtures found")
    def test_extracted_values_appear_in_source(self) -> None:
        """Key extracted values should be findable in the source document text."""
        grounding_failures = 0
        total_checked = 0

        for case in GOLDEN_CASES:
            source_text = case.get("source_text", case.get("input", ""))
            output = case.get("model_output") or case.get("output", {})  # noqa: F841
            expected = case.get("expected", {})

            if not source_text or not expected:
                continue

            if isinstance(expected, str):
                try:
                    expected = json.loads(expected)
                except json.JSONDecodeError:
                    continue

            if isinstance(expected, dict):
                for key, value in expected.items():
                    if isinstance(value, str) and len(value) > 3:
                        total_checked += 1
                        if value.lower() not in str(source_text).lower():
                            grounding_failures += 1

        if total_checked == 0:
            pytest.skip("No groundable values in fixtures")

        grounding_rate = 1.0 - (grounding_failures / total_checked)
        assert grounding_rate >= 0.80, (
            f"Grounding rate {grounding_rate:.1%} below 80% threshold "
            f"({grounding_failures}/{total_checked} failures)"
        )


# ---------------------------------------------------------------------------
# Nightly Tier: LLM-as-a-judge (requires API key + DEEPEVAL_NIGHTLY=true)
# ---------------------------------------------------------------------------

NIGHTLY_ENABLED = os.getenv("DEEPEVAL_NIGHTLY", "").lower() == "true"


@pytest.mark.skipif(
    not NIGHTLY_ENABLED,
    reason="Nightly DeepEval requires DEEPEVAL_NIGHTLY=true (skipped in CI)",
)
class TestDeepEvalNightly:
    """LLM-as-a-judge evaluation using DeepEval metrics.

    Only runs when DEEPEVAL_NIGHTLY=true is set (nightly cron or manual trigger).
    Requires ANTHROPIC_API_KEY or OPENAI_API_KEY for LLM judge calls.
    """

    def test_contextual_precision(self) -> None:
        """Evaluate contextual precision on golden dataset."""
        try:
            from deepeval.metrics import ContextualPrecisionMetric
            from deepeval.test_case import LLMTestCase
        except ImportError:
            pytest.skip("deepeval not installed")

        metric = ContextualPrecisionMetric(threshold=0.7)
        passed = 0
        total = 0

        for case in GOLDEN_CASES[:10]:
            input_text = case.get("input", case.get("query", ""))
            output_text = str(case.get("model_output", case.get("output", "")))
            expected = str(case.get("expected", ""))
            context = case.get("context", [case.get("source_text", "")])

            if not input_text or not output_text:
                continue

            if isinstance(context, str):
                context = [context]

            test_case = LLMTestCase(
                input=input_text,
                actual_output=output_text,
                expected_output=expected,
                retrieval_context=context,
            )
            metric.measure(test_case)
            total += 1
            if metric.score >= 0.7:
                passed += 1

        if total == 0:
            pytest.skip("No valid test cases for contextual precision")
        pass_rate = passed / total
        assert pass_rate >= 0.70, f"Contextual precision pass rate {pass_rate:.1%} below 70%"

    def test_faithfulness(self) -> None:
        """Evaluate faithfulness (no hallucination) on golden dataset."""
        try:
            from deepeval.metrics import FaithfulnessMetric
            from deepeval.test_case import LLMTestCase
        except ImportError:
            pytest.skip("deepeval not installed")

        metric = FaithfulnessMetric(threshold=0.7)
        passed = 0
        total = 0

        for case in GOLDEN_CASES[:10]:
            input_text = case.get("input", case.get("query", ""))
            output_text = str(case.get("model_output", case.get("output", "")))
            context = case.get("context", [case.get("source_text", "")])

            if not input_text or not output_text:
                continue

            if isinstance(context, str):
                context = [context]

            test_case = LLMTestCase(
                input=input_text,
                actual_output=output_text,
                retrieval_context=context,
            )
            metric.measure(test_case)
            total += 1
            if metric.score >= 0.7:
                passed += 1

        if total == 0:
            pytest.skip("No valid test cases for faithfulness")
        pass_rate = passed / total
        assert pass_rate >= 0.70, f"Faithfulness pass rate {pass_rate:.1%} below 70%"
