"""Model A/B testing with deterministic variant assignment and statistical significance.

Uses SHA-256 hash of request_id for deterministic routing so the same request
always maps to the same model variant. Statistical significance is determined
via a two-sample z-test on quality scores (requires n >= 30 per group).
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

# Minimum samples per group required before running the z-test.
MIN_SAMPLE_SIZE = 30


@dataclass
class ABTestVariant:
    """Tracks metrics for one variant (control or treatment) of an A/B test."""

    model: str
    traffic_pct: float  # 0.0–1.0
    call_count: int = 0
    total_cost_usd: float = 0.0
    avg_latency_ms: float = 0.0
    quality_scores: list[float] = field(default_factory=list)

    @property
    def avg_quality(self) -> float | None:
        if not self.quality_scores:
            return None
        return sum(self.quality_scores) / len(self.quality_scores)

    @property
    def avg_cost(self) -> float:
        if self.call_count == 0:
            return 0.0
        return self.total_cost_usd / self.call_count


@dataclass
class ABTestResult:
    """Outcome of a two-sample z-test comparing control vs treatment."""

    control: ABTestVariant
    treatment: ABTestVariant
    z_score: float
    p_value: float
    statistically_significant: bool  # True when p_value < 0.05
    winner: str | None  # model name, or None if not yet significant
    cost_reduction_pct: float  # % cost reduction of treatment vs control (negative = more expensive)


def _erf_approx(x: float) -> float:
    """Abramowitz & Stegun approximation of the error function (max error ~1.5e-7)."""
    # Coefficients from A&S 7.1.26
    p = 0.3275911
    a = [0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429]
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1.0 / (1.0 + p * x)
    poly = t * (a[0] + t * (a[1] + t * (a[2] + t * (a[3] + t * a[4]))))
    return sign * (1.0 - poly * math.exp(-(x * x)))


def _p_value_from_z(z: float) -> float:
    """Two-tailed p-value from a z-score using the error function."""
    # P(|Z| > z) = 2 * (1 - Phi(|z|)) = erfc(|z| / sqrt(2))
    return 1.0 - _erf_approx(abs(z) / math.sqrt(2))


class ModelABTest:
    """Deterministic A/B routing and statistical significance testing.

    Uses request hash for deterministic variant assignment (same request always
    routes to the same model). Implements a z-test for comparing quality scores.

    Example:
        ab = ModelABTest()
        variant = ab.assign_variant(request_id, control_pct=0.5)
        # variant == "control" or "treatment"

        result = ab.compute_significance(control_scores, treatment_scores)
        if result.statistically_significant:
            print(f"Winner: {result.winner}")
    """

    # Default A/B tests — override via subclass or config as needed.
    _DEFAULT_TESTS: list[dict] = [
        {
            "name": "classification_haiku_vs_sonnet",
            "operation": "classify",
            "control": "claude-sonnet-4-6",
            "treatment": "claude-haiku-4-5-20251001",
            "control_pct": 0.5,
            "description": "Test Haiku for classification at 50% traffic",
        },
        {
            "name": "extraction_haiku_vs_sonnet",
            "operation": "extract",
            "control": "claude-sonnet-4-6",
            "treatment": "claude-haiku-4-5-20251001",
            "control_pct": 0.8,
            "description": "Test Haiku for extraction at 20% traffic",
        },
    ]

    def assign_variant(self, request_id: str, control_pct: float = 0.5) -> str:
        """Deterministically assign a request to control or treatment.

        The same request_id always maps to the same variant. Distribution
        across many IDs matches control_pct / (1 - control_pct) split.

        Args:
            request_id: Unique identifier for the request (e.g. UUID string).
            control_pct: Fraction of traffic to send to control (0.0–1.0).

        Returns:
            "control" or "treatment".
        """
        digest = hashlib.sha256(request_id.encode()).hexdigest()
        # Use the first 8 hex chars (32-bit space) for sufficient distribution
        bucket = int(digest[:8], 16) % 100
        return "control" if bucket < int(control_pct * 100) else "treatment"

    def compute_significance(
        self,
        control_scores: list[float],
        treatment_scores: list[float],
        control_variant: ABTestVariant | None = None,
        treatment_variant: ABTestVariant | None = None,
    ) -> ABTestResult:
        """Run a two-sample z-test to compare quality scores between variants.

        Requires at least MIN_SAMPLE_SIZE (30) samples per group to produce a
        valid result. Returns statistically_significant=False with z_score=0 and
        p_value=1.0 when either group is too small.

        Args:
            control_scores: Quality scores (0.0–1.0) for the control model.
            treatment_scores: Quality scores (0.0–1.0) for the treatment model.
            control_variant: Optional ABTestVariant for cost comparison data.
            treatment_variant: Optional ABTestVariant for cost comparison data.

        Returns:
            ABTestResult with z_score, p_value, significance flag, and winner.
        """
        # Build variants from score lists if not provided
        if control_variant is None:
            control_variant = ABTestVariant(
                model="control",
                traffic_pct=0.5,
                call_count=len(control_scores),
                quality_scores=list(control_scores),
            )
        if treatment_variant is None:
            treatment_variant = ABTestVariant(
                model="treatment",
                traffic_pct=0.5,
                call_count=len(treatment_scores),
                quality_scores=list(treatment_scores),
            )

        n1 = len(control_scores)
        n2 = len(treatment_scores)

        # Insufficient data — return early without running test
        if n1 < MIN_SAMPLE_SIZE or n2 < MIN_SAMPLE_SIZE:
            return ABTestResult(
                control=control_variant,
                treatment=treatment_variant,
                z_score=0.0,
                p_value=1.0,
                statistically_significant=False,
                winner=None,
                cost_reduction_pct=self._cost_reduction_pct(
                    control_variant, treatment_variant
                ),
            )

        mean1 = sum(control_scores) / n1
        mean2 = sum(treatment_scores) / n2

        var1 = sum((x - mean1) ** 2 for x in control_scores) / n1
        var2 = sum((x - mean2) ** 2 for x in treatment_scores) / n2

        pooled_se = math.sqrt(var1 / n1 + var2 / n2)

        if pooled_se == 0.0:
            # Identical distributions — no effect
            z_score = 0.0
            p_value = 1.0
        else:
            z_score = (mean1 - mean2) / pooled_se
            p_value = _p_value_from_z(z_score)

        significant = p_value < 0.05

        # Winner is the model with higher mean quality, only if significant
        winner: str | None = None
        if significant:
            if mean1 >= mean2:
                winner = control_variant.model
            else:
                winner = treatment_variant.model

        return ABTestResult(
            control=control_variant,
            treatment=treatment_variant,
            z_score=z_score,
            p_value=p_value,
            statistically_significant=significant,
            winner=winner,
            cost_reduction_pct=self._cost_reduction_pct(
                control_variant, treatment_variant
            ),
        )

    def get_active_tests(self) -> list[dict]:
        """Return currently configured A/B test definitions.

        Returns a copy of the default test configurations. In a production
        system these would be loaded from a database or config file.
        """
        return list(self._DEFAULT_TESTS)

    @staticmethod
    def _cost_reduction_pct(
        control: ABTestVariant, treatment: ABTestVariant
    ) -> float:
        """Compute the % cost reduction of treatment vs control.

        Positive value means treatment is cheaper. Negative means more expensive.
        Returns 0.0 when control cost is zero (no data yet).
        """
        ctrl_cost = control.avg_cost
        trt_cost = treatment.avg_cost
        if ctrl_cost == 0.0:
            return 0.0
        return (ctrl_cost - trt_cost) / ctrl_cost * 100.0
