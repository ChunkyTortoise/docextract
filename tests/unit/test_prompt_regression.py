"""Unit tests for PromptRegressionTester — uses mocked evaluator and registry."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.prompt_registry import PromptRegistry
from app.services.prompt_regression import (
    PromptRegressionResult,
    PromptRegressionTester,
    _classify_changes,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry(tmp_path: Path, versions: dict[str, dict[str, str]] | None = None) -> PromptRegistry:
    """Create an isolated PromptRegistry with optional seeded version content.

    versions: {category: {version_tag: content}}
    """
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    reg = PromptRegistry(prompts_dir=prompts_dir)
    if versions:
        for category, ver_map in versions.items():
            cat_dir = prompts_dir / category
            cat_dir.mkdir(parents=True, exist_ok=True)
            for ver, content in ver_map.items():
                (cat_dir / f"{ver}.txt").write_text(content, encoding="utf-8")
    return reg


def _make_evaluator(side_effects: list[dict[str, float]]) -> MagicMock:
    """Return a mock evaluator whose run() returns each dict in side_effects in order."""
    evaluator = MagicMock()
    evaluator.run = AsyncMock(side_effect=side_effects)
    return evaluator


# ---------------------------------------------------------------------------
# _classify_changes unit tests
# ---------------------------------------------------------------------------


class TestClassifyChanges:
    def test_no_changes_within_threshold(self) -> None:
        baseline = {"accuracy": 0.90}
        candidate = {"accuracy": 0.91}  # +0.01, below improvement threshold
        regressions, improvements = _classify_changes(baseline, candidate, 0.02, 0.02)
        assert regressions == []
        assert improvements == []

    def test_regression_detected_above_threshold(self) -> None:
        baseline = {"accuracy": 0.90}
        candidate = {"accuracy": 0.87}  # -0.03 > 0.02 threshold
        regressions, improvements = _classify_changes(baseline, candidate, 0.02, 0.02)
        assert len(regressions) == 1
        assert "accuracy" in regressions[0]

    def test_improvement_detected_above_threshold(self) -> None:
        baseline = {"accuracy": 0.85}
        candidate = {"accuracy": 0.88}  # +0.03 > 0.02 threshold
        regressions, improvements = _classify_changes(baseline, candidate, 0.02, 0.02)
        assert improvements == ["accuracy: 0.8500 -> 0.8800 (gained 0.0300)"]

    def test_metric_missing_from_one_side_is_skipped(self) -> None:
        baseline = {"accuracy": 0.90, "completeness": 0.80}
        candidate = {"accuracy": 0.87}  # completeness missing from candidate
        regressions, improvements = _classify_changes(baseline, candidate, 0.02, 0.02)
        assert all("accuracy" in r for r in regressions)
        assert not any("completeness" in r for r in regressions + improvements)


# ---------------------------------------------------------------------------
# PromptRegressionTester tests
# ---------------------------------------------------------------------------


class TestPromptRegressionTesterCompare:
    @pytest.mark.asyncio
    async def test_compare_runs_evals_on_both_versions(self, tmp_path: Path) -> None:
        registry = _make_registry(
            tmp_path,
            {"extraction": {"v1.0.0": "old prompt", "v1.1.0": "new prompt"}},
        )
        metrics = {"accuracy": 0.90}
        evaluator = _make_evaluator([metrics, metrics])
        tester = PromptRegressionTester(registry, evaluator)
        result = await tester.compare("extraction", "v1.0.0", "v1.1.0")  # noqa: F841
        assert evaluator.run.call_count == 2

    @pytest.mark.asyncio
    async def test_compare_returns_regression_result_type(self, tmp_path: Path) -> None:
        registry = _make_registry(
            tmp_path,
            {"extraction": {"v1.0.0": "prompt A", "v1.1.0": "prompt B"}},
        )
        evaluator = _make_evaluator([{"accuracy": 0.90}, {"accuracy": 0.90}])
        tester = PromptRegressionTester(registry, evaluator)
        result = await tester.compare("extraction", "v1.0.0", "v1.1.0")  # noqa: F841
        assert isinstance(result, PromptRegressionResult)

    @pytest.mark.asyncio
    async def test_regression_detected_when_metric_drops(self, tmp_path: Path) -> None:
        registry = _make_registry(
            tmp_path,
            {"extraction": {"v1.0.0": "baseline", "v1.1.0": "candidate"}},
        )
        evaluator = _make_evaluator(
            [{"accuracy": 0.90}, {"accuracy": 0.87}]  # 3% drop
        )
        tester = PromptRegressionTester(registry, evaluator)
        result = await tester.compare("extraction", "v1.0.0", "v1.1.0")  # noqa: F841
        assert len(result.regressions) == 1
        assert "accuracy" in result.regressions[0]

    @pytest.mark.asyncio
    async def test_improvement_detected_when_metric_rises(self, tmp_path: Path) -> None:
        registry = _make_registry(
            tmp_path,
            {"extraction": {"v1.0.0": "baseline", "v1.1.0": "candidate"}},
        )
        evaluator = _make_evaluator(
            [{"accuracy": 0.85}, {"accuracy": 0.89}]  # +4%
        )
        tester = PromptRegressionTester(registry, evaluator)
        result = await tester.compare("extraction", "v1.0.0", "v1.1.0")  # noqa: F841
        assert len(result.improvements) == 1
        assert "accuracy" in result.improvements[0]

    @pytest.mark.asyncio
    async def test_passed_true_when_no_regressions(self, tmp_path: Path) -> None:
        registry = _make_registry(
            tmp_path,
            {"extraction": {"v1.0.0": "baseline", "v1.1.0": "candidate"}},
        )
        evaluator = _make_evaluator(
            [{"accuracy": 0.90}, {"accuracy": 0.90}]
        )
        tester = PromptRegressionTester(registry, evaluator)
        result = await tester.compare("extraction", "v1.0.0", "v1.1.0")  # noqa: F841
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_passed_false_when_regression_detected(self, tmp_path: Path) -> None:
        registry = _make_registry(
            tmp_path,
            {"extraction": {"v1.0.0": "baseline", "v1.1.0": "candidate"}},
        )
        evaluator = _make_evaluator(
            [{"accuracy": 0.92}, {"accuracy": 0.88}]  # -4% > threshold
        )
        tester = PromptRegressionTester(registry, evaluator)
        result = await tester.compare("extraction", "v1.0.0", "v1.1.0")  # noqa: F841
        assert result.passed is False
        assert result.regressions

    @pytest.mark.asyncio
    async def test_result_contains_both_metric_sets(self, tmp_path: Path) -> None:
        registry = _make_registry(
            tmp_path,
            {"extraction": {"v1.0.0": "baseline", "v1.1.0": "candidate"}},
        )
        baseline_m = {"accuracy": 0.90, "completeness": 0.85}
        candidate_m = {"accuracy": 0.91, "completeness": 0.86}
        evaluator = _make_evaluator([baseline_m, candidate_m])
        tester = PromptRegressionTester(registry, evaluator)
        result = await tester.compare("extraction", "v1.0.0", "v1.1.0")  # noqa: F841
        assert result.baseline_metrics == baseline_m
        assert result.metrics == candidate_m


class TestPromptRegressionTesterTestCurrent:
    @pytest.mark.asyncio
    async def test_test_current_compares_latest_vs_previous(self, tmp_path: Path) -> None:
        registry = _make_registry(
            tmp_path,
            {"extraction": {"v1.0.0": "old", "v1.1.0": "new", "v2.0.0": "newest"}},
        )
        metrics = {"accuracy": 0.90}
        evaluator = _make_evaluator([metrics, metrics])
        tester = PromptRegressionTester(registry, evaluator)
        result = await tester.test_current("extraction")
        # latest = v2.0.0, previous = v1.1.0
        assert result.candidate_version == "v2.0.0"
        assert result.baseline_version == "v1.1.0"

    @pytest.mark.asyncio
    async def test_test_current_raises_with_single_version(self, tmp_path: Path) -> None:
        registry = _make_registry(
            tmp_path,
            {"extraction": {"v1.0.0": "only version"}},
        )
        evaluator = _make_evaluator([])
        tester = PromptRegressionTester(registry, evaluator)
        with pytest.raises(ValueError, match="at least 2 versions"):
            await tester.test_current("extraction")
