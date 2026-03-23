"""Prompt regression testing.

Runs golden evals against two prompt versions and compares metrics.
Regression threshold: a 2% (0.02) degradation in any metric triggers a failure.
Improvement threshold: a 2% (0.02) improvement is flagged as notable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from app.services.prompt_registry import PromptCategory, PromptRegistry

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

REGRESSION_THRESHOLD = 0.02
IMPROVEMENT_THRESHOLD = 0.02


@dataclass
class PromptRegressionResult:
    """Outcome of comparing two prompt versions on the golden eval suite."""

    category: PromptCategory
    baseline_version: str
    candidate_version: str
    metrics: dict[str, float]          # candidate scores
    baseline_metrics: dict[str, float]  # baseline scores
    regressions: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    passed: bool = True


# ---------------------------------------------------------------------------
# Evaluator protocol (allows injection of real or mock evaluators)
# ---------------------------------------------------------------------------

class EvaluatorProtocol(Protocol):
    """Minimal interface expected of the eval harness."""

    async def run(self, prompt_override: str | None = None) -> dict[str, float]:
        """Run evals and return {metric_name: score} mapping."""
        ...


# ---------------------------------------------------------------------------
# Regression tester
# ---------------------------------------------------------------------------

class PromptRegressionTester:
    """Runs golden eval on two prompt versions and compares metrics.

    Regression threshold: 2% degradation triggers a failure.
    Improvement threshold: 2% improvement is flagged as notable.
    """

    def __init__(
        self,
        prompt_registry: PromptRegistry,
        evaluator: EvaluatorProtocol,
    ) -> None:
        self._registry = prompt_registry
        self._evaluator = evaluator

    async def compare(
        self,
        category: PromptCategory,
        baseline_version: str,
        candidate_version: str,
    ) -> PromptRegressionResult:
        """Run evals for both versions and compare.

        Each version's prompt text is retrieved and passed as an override
        to the evaluator. Returns a PromptRegressionResult with pass/fail
        status and annotated regressions/improvements.
        """
        baseline_prompt = self._registry.get_prompt(category, baseline_version)
        candidate_prompt = self._registry.get_prompt(category, candidate_version)

        baseline_metrics = await self._evaluator.run(prompt_override=baseline_prompt)
        candidate_metrics = await self._evaluator.run(prompt_override=candidate_prompt)

        regressions, improvements = _classify_changes(
            baseline_metrics,
            candidate_metrics,
            REGRESSION_THRESHOLD,
            IMPROVEMENT_THRESHOLD,
        )

        return PromptRegressionResult(
            category=category,
            baseline_version=baseline_version,
            candidate_version=candidate_version,
            metrics=candidate_metrics,
            baseline_metrics=baseline_metrics,
            regressions=regressions,
            improvements=improvements,
            passed=len(regressions) == 0,
        )

    async def test_current(self, category: PromptCategory) -> PromptRegressionResult:
        """Compare the latest version against the previous version.

        Raises ValueError if fewer than two versions exist for the category.
        """
        versions = self._registry.list_versions(category)
        if len(versions) < 2:
            raise ValueError(
                f"Need at least 2 versions for regression testing; "
                f"found {len(versions)} for category {category!r}."
            )
        # list_versions returns descending, so [0] = latest, [1] = previous
        candidate_version = versions[0]
        baseline_version = versions[1]
        return await self.compare(category, baseline_version, candidate_version)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _classify_changes(
    baseline: dict[str, float],
    candidate: dict[str, float],
    regression_threshold: float,
    improvement_threshold: float,
) -> tuple[list[str], list[str]]:
    """Compare metric dicts and return (regressions, improvements)."""
    regressions: list[str] = []
    improvements: list[str] = []

    all_metrics = set(baseline.keys()) | set(candidate.keys())
    for metric in sorted(all_metrics):
        b_score = baseline.get(metric)
        c_score = candidate.get(metric)
        if b_score is None or c_score is None:
            continue
        delta = c_score - b_score
        if delta < -regression_threshold:
            regressions.append(
                f"{metric}: {b_score:.4f} -> {c_score:.4f} "
                f"(dropped {abs(delta):.4f})"
            )
        elif delta > improvement_threshold:
            improvements.append(
                f"{metric}: {b_score:.4f} -> {c_score:.4f} "
                f"(gained {delta:.4f})"
            )

    return regressions, improvements
