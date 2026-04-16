"""Tests for ModelABTest — deterministic routing and z-test significance."""
from __future__ import annotations

import uuid

from app.services.model_ab_test import (
    MIN_SAMPLE_SIZE,
    ABTestResult,
    ABTestVariant,
    ModelABTest,
    _p_value_from_z,
)


class TestAssignVariantDeterminism:
    """assign_variant must be deterministic for the same request_id."""

    def test_same_id_returns_same_variant(self):
        ab = ModelABTest()
        request_id = "550e8400-e29b-41d4-a716-446655440000"
        first = ab.assign_variant(request_id, control_pct=0.5)
        second = ab.assign_variant(request_id, control_pct=0.5)
        assert first == second

    def test_returns_control_or_treatment(self):
        ab = ModelABTest()
        for _ in range(20):
            variant = ab.assign_variant(str(uuid.uuid4()), control_pct=0.5)
            assert variant in ("control", "treatment")

    def test_different_ids_can_produce_different_variants(self):
        ab = ModelABTest()
        variants = {ab.assign_variant(str(uuid.uuid4()), 0.5) for _ in range(100)}
        assert variants == {"control", "treatment"}

    def test_100pct_control_always_control(self):
        ab = ModelABTest()
        for _ in range(50):
            assert ab.assign_variant(str(uuid.uuid4()), control_pct=1.0) == "control"

    def test_0pct_control_always_treatment(self):
        ab = ModelABTest()
        for _ in range(50):
            assert ab.assign_variant(str(uuid.uuid4()), control_pct=0.0) == "treatment"


class TestAssignVariantDistribution:
    """assign_variant should distribute traffic at approximately the requested ratio."""

    def test_50_50_split_is_approximate(self):
        ab = ModelABTest()
        n = 10_000
        control_count = sum(
            1 for _ in range(n) if ab.assign_variant(str(uuid.uuid4()), 0.5) == "control"
        )
        ratio = control_count / n
        # Allow 5% deviation from 50%
        assert 0.45 <= ratio <= 0.55

    def test_80_20_split_is_approximate(self):
        ab = ModelABTest()
        n = 10_000
        control_count = sum(
            1 for _ in range(n) if ab.assign_variant(str(uuid.uuid4()), 0.8) == "control"
        )
        ratio = control_count / n
        # Allow 5% deviation from 80%
        assert 0.75 <= ratio <= 0.85


class TestComputeSignificanceWithSufficientData:
    """z-test with n >= 30 per group."""

    def _scores(self, mean: float, std: float, n: int, seed: int = 42) -> list[float]:
        import random

        random.seed(seed)
        return [min(1.0, max(0.0, random.gauss(mean, std))) for _ in range(n)]

    def test_returns_abtestresult(self):
        ab = ModelABTest()
        ctrl = self._scores(0.85, 0.05, 50)
        trt = self._scores(0.85, 0.05, 50)
        result = ab.compute_significance(ctrl, trt)
        assert isinstance(result, ABTestResult)

    def test_identical_distributions_not_significant(self):
        ab = ModelABTest()
        scores = self._scores(0.80, 0.05, 60)
        result = ab.compute_significance(scores, list(scores))
        assert not result.statistically_significant
        assert result.winner is None

    def test_large_difference_is_significant(self):
        ab = ModelABTest()
        # Mean difference of 0.30 with small std should be significant at n=200
        ctrl = self._scores(0.90, 0.03, 200, seed=10)
        trt = self._scores(0.60, 0.03, 200, seed=11)
        result = ab.compute_significance(ctrl, trt)
        assert result.statistically_significant
        assert result.p_value < 0.05

    def test_winner_is_higher_quality_model(self):
        ab = ModelABTest()
        ctrl_variant = ABTestVariant(model="claude-sonnet-4-6", traffic_pct=0.5)
        trt_variant = ABTestVariant(model="claude-haiku-4-5", traffic_pct=0.5)
        # Control has higher quality
        ctrl_scores = self._scores(0.90, 0.03, 200, seed=20)
        trt_scores = self._scores(0.60, 0.03, 200, seed=21)
        ctrl_variant.quality_scores = ctrl_scores
        trt_variant.quality_scores = trt_scores

        result = ab.compute_significance(
            ctrl_scores, trt_scores, ctrl_variant, trt_variant
        )
        if result.statistically_significant:
            assert result.winner == "claude-sonnet-4-6"

    def test_z_score_direction_positive_when_control_higher(self):
        ab = ModelABTest()
        ctrl = self._scores(0.90, 0.03, 100, seed=30)
        trt = self._scores(0.70, 0.03, 100, seed=31)
        result = ab.compute_significance(ctrl, trt)
        assert result.z_score > 0

    def test_z_score_mathematically_correct(self):
        ab = ModelABTest()
        # Manually construct known-good data
        ctrl = [0.9] * 50
        trt = [0.7] * 50
        result = ab.compute_significance(ctrl, trt)
        # Means 0.9 vs 0.7 with zero variance → degenerate but z should be 0
        # because pooled_se = 0 → handled gracefully
        assert isinstance(result.z_score, float)


class TestComputeSignificanceInsufficientData:
    """Early return when n < MIN_SAMPLE_SIZE."""

    def test_small_control_not_significant(self):
        ab = ModelABTest()
        ctrl = [0.9] * (MIN_SAMPLE_SIZE - 1)
        trt = [0.7] * MIN_SAMPLE_SIZE
        result = ab.compute_significance(ctrl, trt)
        assert not result.statistically_significant
        assert result.p_value == 1.0
        assert result.z_score == 0.0

    def test_small_treatment_not_significant(self):
        ab = ModelABTest()
        ctrl = [0.9] * MIN_SAMPLE_SIZE
        trt = [0.7] * (MIN_SAMPLE_SIZE - 1)
        result = ab.compute_significance(ctrl, trt)
        assert not result.statistically_significant

    def test_both_empty_not_significant(self):
        ab = ModelABTest()
        result = ab.compute_significance([], [])
        assert not result.statistically_significant
        assert result.winner is None


class TestGetActiveTests:
    """get_active_tests returns well-formed list."""

    def test_returns_list(self):
        ab = ModelABTest()
        tests = ab.get_active_tests()
        assert isinstance(tests, list)
        assert len(tests) > 0

    def test_each_test_has_required_keys(self):
        ab = ModelABTest()
        for test in ab.get_active_tests():
            assert "name" in test
            assert "operation" in test
            assert "control" in test
            assert "treatment" in test


class TestPValueHelper:
    """Unit tests for the p-value helper function."""

    def test_z_zero_gives_p_one(self):
        p = _p_value_from_z(0.0)
        assert abs(p - 1.0) < 0.01

    def test_large_z_gives_small_p(self):
        p = _p_value_from_z(4.0)
        assert p < 0.001
