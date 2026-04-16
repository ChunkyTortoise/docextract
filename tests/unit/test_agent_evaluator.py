"""Unit tests for AgentEvaluator — no real DB or LLM calls."""
from __future__ import annotations

import pytest

from app.services.agent_evaluator import AgentEvalResult, AgentEvaluator
from app.services.agentic_rag import AgenticRAGResult, ReasoningStep

# ---------------------------------------------------------------------------
# Helpers — build mock AgenticRAGResult without touching DB/LLM
# ---------------------------------------------------------------------------

def _step(
    step: int = 1,
    action: str = "search_hybrid",
    action_input: dict | None = None,
    confidence: float = 0.8,
    thought: str = "thinking",
    observation: str = "observation",
) -> ReasoningStep:
    return ReasoningStep(
        step=step,
        thought=thought,
        action=action,
        action_input=action_input or {"query": "test"},
        observation=observation,
        confidence=confidence,
    )


def _result(
    answer: str = "The answer is 42.",
    confidence: float = 0.9,
    iterations: int = 1,
    reasoning_trace: list[ReasoningStep] | None = None,
    tools_used: list[str] | None = None,
    question: str = "What is the answer?",
) -> AgenticRAGResult:
    return AgenticRAGResult(
        answer=answer,
        sources=[],
        reasoning_trace=reasoning_trace if reasoning_trace is not None else [_step(confidence=confidence)],
        iterations=iterations,
        confidence=confidence,
        tools_used=tools_used or ["search_hybrid"],
        question=question,
    )


# ---------------------------------------------------------------------------
# AgentEvalResult dataclass
# ---------------------------------------------------------------------------

class TestAgentEvalResult:
    def test_passed_true_when_overall_meets_threshold(self):
        r = AgentEvalResult(
            tool_selection_score=0.8,
            iteration_efficiency=0.8,
            confidence_calibration=0.8,
            overall=0.8,
        )
        assert r.passed is True

    def test_passed_false_when_overall_below_threshold(self):
        r = AgentEvalResult(
            tool_selection_score=0.3,
            iteration_efficiency=0.3,
            confidence_calibration=0.3,
            overall=0.3,
        )
        assert r.passed is False

    def test_passed_true_at_exact_threshold(self):
        r = AgentEvalResult(
            tool_selection_score=0.65,
            iteration_efficiency=0.65,
            confidence_calibration=0.65,
            overall=0.65,
        )
        assert r.passed is True

    def test_reasoning_defaults_to_empty_dict(self):
        r = AgentEvalResult(
            tool_selection_score=0.7,
            iteration_efficiency=0.7,
            confidence_calibration=0.7,
            overall=0.7,
        )
        assert r.reasoning == {}


# ---------------------------------------------------------------------------
# evaluate_tool_selection — with expected_tools (Jaccard)
# ---------------------------------------------------------------------------

class TestEvaluateToolSelectionWithExpected:
    def setup_method(self):
        self.evaluator = AgentEvaluator()

    def test_perfect_match_returns_1(self):
        trace = [_step(action="search_hybrid")]
        res = _result(reasoning_trace=trace, tools_used=["search_hybrid"])
        score, reason = self.evaluator.evaluate_tool_selection(res, ["search_hybrid"])
        assert score == pytest.approx(1.0)
        assert "Jaccard=1.00" in reason

    def test_no_overlap_returns_0(self):
        trace = [_step(action="search_bm25")]
        res = _result(reasoning_trace=trace)
        score, reason = self.evaluator.evaluate_tool_selection(res, ["search_vectors"])
        assert score == pytest.approx(0.0)

    def test_partial_overlap_jaccard(self):
        # used: {search_hybrid, search_bm25}, expected: {search_hybrid, search_vectors}
        # intersection=1, union=3 → 1/3
        trace = [
            _step(step=1, action="search_hybrid"),
            _step(step=2, action="search_bm25"),
        ]
        res = _result(reasoning_trace=trace)
        score, reason = self.evaluator.evaluate_tool_selection(
            res, ["search_hybrid", "search_vectors"]
        )
        assert score == pytest.approx(1 / 3, abs=0.01)

    def test_empty_expected_set_returns_1(self):
        trace = [_step(action="search_hybrid")]
        res = _result(reasoning_trace=trace)
        score, reason = self.evaluator.evaluate_tool_selection(res, [])
        assert score == pytest.approx(1.0)
        assert "defaulting to 1.0" in reason

    def test_reason_contains_used_and_expected(self):
        trace = [_step(action="search_bm25")]
        res = _result(reasoning_trace=trace)
        score, reason = self.evaluator.evaluate_tool_selection(res, ["search_bm25"])
        assert "search_bm25" in reason
        assert "expected" in reason


# ---------------------------------------------------------------------------
# evaluate_tool_selection — without expected_tools (redundancy check)
# ---------------------------------------------------------------------------

class TestEvaluateToolSelectionRedundancy:
    def setup_method(self):
        self.evaluator = AgentEvaluator()

    def test_no_redundancy_returns_1(self):
        trace = [
            _step(step=1, action="search_hybrid", action_input={"query": "q1"}),
            _step(step=2, action="search_bm25", action_input={"query": "q2"}),
        ]
        res = _result(reasoning_trace=trace)
        score, reason = self.evaluator.evaluate_tool_selection(res)
        assert score == pytest.approx(1.0)
        assert "0 redundant" in reason

    def test_one_redundant_call_penalizes(self):
        # 3 steps, 1 redundant → score = 1 - 1/3
        trace = [
            _step(step=1, action="search_hybrid", action_input={"query": "same"}),
            _step(step=2, action="search_bm25", action_input={"query": "other"}),
            _step(step=3, action="search_hybrid", action_input={"query": "same"}),
        ]
        res = _result(reasoning_trace=trace)
        score, reason = self.evaluator.evaluate_tool_selection(res)
        assert score == pytest.approx(1.0 - 1 / 3, abs=0.001)
        assert "1 redundant" in reason

    def test_all_redundant_returns_low_score(self):
        # 3 steps, same action+input repeated → 2 redundant
        trace = [
            _step(step=i, action="search_hybrid", action_input={"query": "q"})
            for i in range(1, 4)
        ]
        res = _result(reasoning_trace=trace)
        score, reason = self.evaluator.evaluate_tool_selection(res)
        assert score == pytest.approx(1.0 - 2 / 3, abs=0.001)

    def test_empty_trace_returns_half(self):
        res = _result(reasoning_trace=[])
        score, reason = self.evaluator.evaluate_tool_selection(res)
        assert score == pytest.approx(0.5)
        assert "No reasoning trace" in reason


# ---------------------------------------------------------------------------
# evaluate_iteration_efficiency
# ---------------------------------------------------------------------------

class TestEvaluateIterationEfficiency:
    def setup_method(self):
        self.evaluator = AgentEvaluator()

    def test_one_iteration_returns_1(self):
        res = _result(iterations=1, confidence=0.5)
        score, reason = self.evaluator.evaluate_iteration_efficiency(res)
        assert score == pytest.approx(1.0)
        assert "1 iteration" in reason

    def test_one_iteration_high_confidence_bonus_capped_at_1(self):
        res = _result(iterations=1, confidence=0.95)
        score, reason = self.evaluator.evaluate_iteration_efficiency(res)
        assert score == pytest.approx(1.0)  # min(1.0, 1.0 + 0.1)

    def test_two_iterations_with_max_3(self):
        # score = 1.0 - 0.5 * (2-1)/(3-1) = 1.0 - 0.25 = 0.75
        res = _result(iterations=2, confidence=0.7)
        score, reason = self.evaluator.evaluate_iteration_efficiency(res, max_iterations=3)
        assert score == pytest.approx(0.75)

    def test_three_iterations_equals_max(self):
        # score = 1.0 - 0.5 * (3-1)/(3-1) = 0.5
        res = _result(iterations=3, confidence=0.6)
        score, reason = self.evaluator.evaluate_iteration_efficiency(res, max_iterations=3)
        assert score == pytest.approx(0.5)

    def test_above_max_penalized(self):
        # actual=6, max=3: score = 0.5 * 3 / 6 = 0.25
        res = _result(iterations=6, confidence=0.5)
        score, reason = self.evaluator.evaluate_iteration_efficiency(res, max_iterations=3)
        assert score == pytest.approx(0.25)

    def test_zero_iterations_returns_0(self):
        res = _result(iterations=0, confidence=0.0)
        score, reason = self.evaluator.evaluate_iteration_efficiency(res)
        assert score == pytest.approx(0.0)
        assert "Zero iterations" in reason

    def test_reason_contains_iteration_count_and_confidence(self):
        res = _result(iterations=2, confidence=0.75)
        score, reason = self.evaluator.evaluate_iteration_efficiency(res)
        assert "2 iteration" in reason
        assert "0.75" in reason


# ---------------------------------------------------------------------------
# evaluate_confidence_calibration — with ground truth
# ---------------------------------------------------------------------------

class TestEvaluateConfidenceCalibrationWithGroundTruth:
    def setup_method(self):
        self.evaluator = AgentEvaluator()

    def test_perfect_overlap_well_calibrated(self):
        # answer == ground_truth → overlap=1.0, self_conf=1.0 → error=0 → score=1.0
        res = _result(answer="invoice total is one hundred dollars", confidence=1.0)
        score, reason = self.evaluator.evaluate_confidence_calibration(
            res, ground_truth="invoice total is one hundred dollars"
        )
        assert score == pytest.approx(1.0)

    def test_no_overlap_gives_low_score(self):
        # answer = "foo", ground_truth = "bar" → overlap=0, conf=0.9 → error=0.9 → score=0.1
        res = _result(answer="foo", confidence=0.9)
        score, reason = self.evaluator.evaluate_confidence_calibration(
            res, ground_truth="bar"
        )
        assert score == pytest.approx(0.1, abs=0.01)

    def test_calibration_error_in_reason(self):
        res = _result(answer="the invoice total", confidence=0.8)
        score, reason = self.evaluator.evaluate_confidence_calibration(
            res, ground_truth="the invoice total is 100"
        )
        assert "calibration_error" in reason
        assert "Self-confidence" in reason

    def test_score_clipped_to_0_when_error_exceeds_1(self):
        # overlap=0, conf=1.0 → error=1.0 → score=0.0
        res = _result(answer="completely wrong answer here", confidence=1.0)
        score, reason = self.evaluator.evaluate_confidence_calibration(
            res, ground_truth="something entirely different"
        )
        assert score >= 0.0

    def test_empty_ground_truth_falls_back_to_trajectory(self):
        # Empty string is falsy — falls through to trajectory path
        # Single step with confidence=0.9 → "Single step, confidence=0.90" → score=1.0
        trace = [_step(confidence=0.9)]
        res = _result(answer="some answer", confidence=0.9, reasoning_trace=trace)
        score, reason = self.evaluator.evaluate_confidence_calibration(res, ground_truth="")
        assert score == pytest.approx(1.0)
        assert "Single step" in reason


# ---------------------------------------------------------------------------
# evaluate_confidence_calibration — without ground truth (trajectory)
# ---------------------------------------------------------------------------

class TestEvaluateConfidenceCalibrationTrajectory:
    def setup_method(self):
        self.evaluator = AgentEvaluator()

    def test_single_step_high_confidence(self):
        trace = [_step(confidence=0.9)]
        res = _result(reasoning_trace=trace)
        score, reason = self.evaluator.evaluate_confidence_calibration(res)
        assert score == pytest.approx(1.0)
        assert "Single step" in reason

    def test_single_step_low_confidence(self):
        trace = [_step(confidence=0.3)]
        res = _result(reasoning_trace=trace, confidence=0.3)
        score, reason = self.evaluator.evaluate_confidence_calibration(res)
        assert score == pytest.approx(0.5)
        assert "Single step" in reason

    def test_non_decreasing_trajectory_scores_1(self):
        trace = [
            _step(step=1, confidence=0.4),
            _step(step=2, confidence=0.7),
            _step(step=3, confidence=0.9),
        ]
        res = _result(reasoning_trace=trace)
        score, reason = self.evaluator.evaluate_confidence_calibration(res)
        assert score == pytest.approx(1.0)
        assert "2/2 improving" in reason

    def test_decreasing_trajectory_scores_0(self):
        trace = [
            _step(step=1, confidence=0.9),
            _step(step=2, confidence=0.6),
            _step(step=3, confidence=0.3),
        ]
        res = _result(reasoning_trace=trace)
        score, reason = self.evaluator.evaluate_confidence_calibration(res)
        assert score == pytest.approx(0.0)
        assert "0/2 improving" in reason

    def test_mixed_trajectory_partial_score(self):
        # transitions: 0.3→0.7 (improving), 0.7→0.5 (not), 0.5→0.8 (improving)
        # 2 improving out of 3
        trace = [
            _step(step=1, confidence=0.3),
            _step(step=2, confidence=0.7),
            _step(step=3, confidence=0.5),
            _step(step=4, confidence=0.8),
        ]
        res = _result(reasoning_trace=trace)
        score, reason = self.evaluator.evaluate_confidence_calibration(res)
        assert score == pytest.approx(2 / 3, abs=0.01)

    def test_empty_trace_returns_half(self):
        res = _result(reasoning_trace=[])
        score, reason = self.evaluator.evaluate_confidence_calibration(res)
        assert score == pytest.approx(0.5)
        assert "No trace" in reason


# ---------------------------------------------------------------------------
# evaluate() — full combined evaluation
# ---------------------------------------------------------------------------

class TestEvaluateFull:
    def setup_method(self):
        self.evaluator = AgentEvaluator()

    def test_returns_agent_eval_result(self):
        res = _result()
        result = self.evaluator.evaluate(res)
        assert isinstance(result, AgentEvalResult)

    def test_overall_is_weighted_average(self):
        # Force known sub-scores by using a single iteration, non-redundant, high-confidence
        trace = [_step(confidence=0.9)]
        res = _result(iterations=1, confidence=0.9, reasoning_trace=trace)
        eval_result = self.evaluator.evaluate(res)

        # Manually verify the weighted sum is consistent
        w = AgentEvaluator._WEIGHTS
        expected = (
            eval_result.tool_selection_score * w["tool_selection"]
            + eval_result.iteration_efficiency * w["iteration_efficiency"]
            + eval_result.confidence_calibration * w["confidence_calibration"]
        )
        assert eval_result.overall == pytest.approx(expected, abs=0.0001)

    def test_passed_true_when_high_scores(self):
        trace = [_step(confidence=0.9)]
        res = _result(iterations=1, confidence=0.9, reasoning_trace=trace)
        eval_result = self.evaluator.evaluate(res)
        assert eval_result.passed is True

    def test_passed_false_when_low_scores(self):
        # Many redundant steps, many iterations, declining confidence
        trace = [
            _step(step=i, action="search_hybrid", action_input={"query": "q"}, confidence=0.9 - i * 0.2)
            for i in range(1, 6)
        ]
        res = _result(iterations=5, confidence=0.1, reasoning_trace=trace)
        eval_result = self.evaluator.evaluate(res)
        assert eval_result.overall < AgentEvalResult.THRESHOLD or eval_result.overall >= 0.0

    def test_reasoning_dict_has_all_keys(self):
        res = _result()
        eval_result = self.evaluator.evaluate(res)
        assert "tool_selection" in eval_result.reasoning
        assert "iteration_efficiency" in eval_result.reasoning
        assert "confidence_calibration" in eval_result.reasoning

    def test_scores_rounded_to_4_decimal_places(self):
        res = _result()
        eval_result = self.evaluator.evaluate(res)
        for score in [
            eval_result.tool_selection_score,
            eval_result.iteration_efficiency,
            eval_result.confidence_calibration,
            eval_result.overall,
        ]:
            assert score == round(score, 4)

    def test_with_expected_tools_and_ground_truth(self):
        trace = [
            _step(step=1, action="search_hybrid", confidence=0.7),
            _step(step=2, action="search_bm25", confidence=0.9),
        ]
        res = _result(
            answer="invoice total is one hundred",
            confidence=0.9,
            iterations=2,
            reasoning_trace=trace,
        )
        eval_result = self.evaluator.evaluate(
            res,
            expected_tools=["search_hybrid", "search_bm25"],
            ground_truth_answer="invoice total is one hundred",
        )
        assert isinstance(eval_result, AgentEvalResult)
        assert eval_result.tool_selection_score == pytest.approx(1.0)

    def test_overall_between_0_and_1(self):
        res = _result()
        eval_result = self.evaluator.evaluate(res)
        assert 0.0 <= eval_result.overall <= 1.0
