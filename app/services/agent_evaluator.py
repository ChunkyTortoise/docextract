"""Agent decision quality evaluation.

Evaluates the reasoning trace of an agentic RAG run across three dimensions:
  - Tool selection quality: did the agent pick appropriate tools for the query type?
  - Iteration efficiency: did the agent converge before hitting the iteration limit?
  - Confidence calibration: is self-assessed confidence correlated with answer quality?
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.agentic_rag import AgenticRAGResult

# Tools suited to each rough query type (heuristic for evaluation)
_KEYWORD_TOOLS = {"search_bm25"}  # exact IDs, invoice numbers, names
_SEMANTIC_TOOLS = {"search_vectors"}  # conceptual, open-ended
_BROAD_TOOLS = {"search_hybrid"}  # mixed / fallback
_AUXILIARY_TOOLS = {"lookup_metadata", "rerank_results"}


@dataclass
class AgentEvalResult:
    tool_selection_score: float  # 0.0–1.0
    iteration_efficiency: float  # 0.0–1.0
    confidence_calibration: float  # 0.0–1.0
    overall: float  # weighted average
    reasoning: dict[str, str] = field(default_factory=dict)  # per-dimension notes
    passed: bool = True  # True if overall >= threshold

    THRESHOLD: float = 0.65  # class-level default

    def __post_init__(self) -> None:
        self.passed = self.overall >= self.THRESHOLD


class AgentEvaluator:
    """Evaluate agent reasoning quality from an AgenticRAGResult trace."""

    # Weights for each dimension
    _WEIGHTS = {
        "tool_selection": 0.40,
        "iteration_efficiency": 0.35,
        "confidence_calibration": 0.25,
    }

    def evaluate(
        self,
        result: AgenticRAGResult,
        *,
        expected_tools: list[str] | None = None,
        ground_truth_answer: str | None = None,
    ) -> AgentEvalResult:
        """Run all three evaluations and return a combined result."""
        tool_score, tool_reason = self.evaluate_tool_selection(result, expected_tools)
        iter_score, iter_reason = self.evaluate_iteration_efficiency(result)
        calib_score, calib_reason = self.evaluate_confidence_calibration(result, ground_truth_answer)

        overall = (
            tool_score * self._WEIGHTS["tool_selection"]
            + iter_score * self._WEIGHTS["iteration_efficiency"]
            + calib_score * self._WEIGHTS["confidence_calibration"]
        )

        return AgentEvalResult(
            tool_selection_score=round(tool_score, 4),
            iteration_efficiency=round(iter_score, 4),
            confidence_calibration=round(calib_score, 4),
            overall=round(overall, 4),
            reasoning={
                "tool_selection": tool_reason,
                "iteration_efficiency": iter_reason,
                "confidence_calibration": calib_reason,
            },
        )

    def evaluate_tool_selection(
        self,
        result: AgenticRAGResult,
        expected_tools: list[str] | None = None,
    ) -> tuple[float, str]:
        """Score tool selection quality.

        If expected_tools is provided, compare actual tools used.
        Otherwise, score based on whether the agent avoided redundant identical calls.
        """
        if not result.reasoning_trace:
            return 0.5, "No reasoning trace — cannot evaluate tool selection"

        tools_used = [step.action for step in result.reasoning_trace if step.action]

        # If expected tools provided (even empty list), use Jaccard similarity path
        if expected_tools is not None:
            used_set = set(tools_used)
            expected_set = set(expected_tools)
            if not expected_set:
                return 1.0, "No expected tools specified — defaulting to 1.0"
            intersection = used_set & expected_set
            union = used_set | expected_set
            score = len(intersection) / len(union) if union else 1.0
            reason = f"Used {sorted(used_set)}, expected {sorted(expected_set)}, Jaccard={score:.2f}"
            return score, reason

        # No expected tools: penalize repeated identical (action, action_input) pairs
        seen: set[tuple[str, str]] = set()
        redundant = 0
        for step in result.reasoning_trace:
            key = (step.action or "", str(step.action_input or ""))
            if key in seen:
                redundant += 1
            seen.add(key)

        total = len(result.reasoning_trace)
        score = 1.0 - (redundant / total) if total else 1.0
        reason = f"{redundant} redundant tool calls out of {total} steps"
        return round(score, 4), reason

    def evaluate_iteration_efficiency(
        self,
        result: AgenticRAGResult,
        max_iterations: int = 3,
    ) -> tuple[float, str]:
        """Score iteration efficiency: fewer iterations = better, for same confidence."""
        actual = result.iterations
        if actual <= 0:
            return 0.0, "Zero iterations recorded"
        if actual == 1:
            score = 1.0
            # Bonus: if confidence is high AND iterations are low, reward
            if result.confidence >= 0.9:
                score = min(1.0, score + 0.1)
            reason = f"1 iteration (max={max_iterations}), final confidence={result.confidence:.2f}"
            return round(score, 4), reason

        # Linear decay: 1 iter = 1.0, max_iterations = 0.5, >max = penalized
        if actual <= max_iterations:
            score = 1.0 - 0.5 * (actual - 1) / (max_iterations - 1)
        else:
            score = 0.5 * max_iterations / actual  # diminishing penalty

        reason = f"{actual} iterations (max={max_iterations}), final confidence={result.confidence:.2f}"
        return round(score, 4), reason

    def evaluate_confidence_calibration(
        self,
        result: AgenticRAGResult,
        ground_truth: str | None = None,
    ) -> tuple[float, str]:
        """Score confidence calibration.

        If ground_truth provided: compare semantic similarity of answer to ground_truth.
        Otherwise: check that confidence trajectory is monotonically improving (or stable).
        """
        if not result.reasoning_trace:
            return 0.5, "No trace — cannot evaluate calibration"

        # Confidence trajectory from the trace
        confidences = [
            step.confidence
            for step in result.reasoning_trace
            if step.confidence is not None
        ]
        if not confidences:
            return 0.5, "No per-step confidence values in trace"

        # If ground truth available: simple token overlap (jaccard on words)
        if ground_truth and result.answer:
            answer_words = set(result.answer.lower().split())
            truth_words = set(ground_truth.lower().split())
            if not truth_words:
                return 0.5, "Empty ground truth"
            overlap = len(answer_words & truth_words) / len(answer_words | truth_words)
            # Calibration: |self_confidence - actual_quality| — lower is better
            calibration_error = abs(result.confidence - overlap)
            score = 1.0 - calibration_error
            reason = (
                f"Self-confidence={result.confidence:.2f}, "
                f"answer-ground_truth overlap={overlap:.2f}, "
                f"calibration_error={calibration_error:.2f}"
            )
            return round(max(0.0, score), 4), reason

        # No ground truth: reward non-decreasing confidence trajectory
        improving = sum(
            1 for a, b in zip(confidences, confidences[1:]) if b >= a
        )
        total_transitions = len(confidences) - 1
        if total_transitions == 0:
            return (
                (1.0 if confidences[0] >= 0.5 else 0.5),
                f"Single step, confidence={confidences[0]:.2f}",
            )

        trend_score = improving / total_transitions
        reason = f"{improving}/{total_transitions} improving transitions, final={confidences[-1]:.2f}"
        return round(trend_score, 4), reason
