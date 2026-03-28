"""Tests for eval harness expansion: adversarial fixtures, Brier score, calibration, model comparison."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Fixture loading tests
# ---------------------------------------------------------------------------

DATASET_PATH = Path(__file__).parent.parent.parent / "autoresearch" / "eval_dataset.json"
GOLDEN_DIR = Path(__file__).parent.parent.parent / "autoresearch" / "golden_responses"
ALERTS_PATH = Path(__file__).parent.parent.parent / "deploy" / "prometheus" / "alerts.yml"


def _load_dataset() -> list[dict]:
    with open(DATASET_PATH) as f:
        return json.load(f)


class TestDatasetIntegrity:
    """Verify eval dataset is well-formed and complete."""

    def test_dataset_loads(self) -> None:
        dataset = _load_dataset()
        assert len(dataset) >= 28, f"Expected >= 28 fixtures, got {len(dataset)}"

    def test_all_cases_have_required_fields(self) -> None:
        dataset = _load_dataset()
        required = {"id", "doc_type", "weight", "critical_fields", "input_text", "expected"}
        for case in dataset:
            missing = required - set(case.keys())
            assert not missing, f"Case {case.get('id', '?')} missing fields: {missing}"

    def test_case_ids_are_unique(self) -> None:
        dataset = _load_dataset()
        ids = [c["id"] for c in dataset]
        assert len(ids) == len(set(ids)), f"Duplicate case IDs: {[x for x in ids if ids.count(x) > 1]}"

    def test_weights_are_valid(self) -> None:
        dataset = _load_dataset()
        for case in dataset:
            assert 0 < case["weight"] <= 1.0, f"Case {case['id']}: weight {case['weight']} out of range"

    def test_adversarial_cases_present(self) -> None:
        dataset = _load_dataset()
        adv_ids = {c["id"] for c in dataset if c["id"].startswith("adv_")}
        expected_adv = {
            "adv_corrupted_pdf",
            "adv_blank_page",
            "adv_scanned_table",
            "adv_duplicate_fields",
            "adv_mixed_language",
            "adv_long_document",
            "adv_handwritten_receipt",
            "adv_redacted_statement",
        }
        missing = expected_adv - adv_ids
        assert not missing, f"Missing adversarial fixtures: {missing}"


class TestGoldenResponses:
    """Verify golden response files exist and are well-formed."""

    def test_every_case_has_golden_response(self) -> None:
        dataset = _load_dataset()
        for case in dataset:
            path = GOLDEN_DIR / f"{case['id']}.json"
            assert path.exists(), f"Missing golden response: {path}"

    def test_golden_responses_match_case_ids(self) -> None:
        dataset = _load_dataset()
        for case in dataset:
            path = GOLDEN_DIR / f"{case['id']}.json"
            with open(path) as f:
                golden = json.load(f)
            assert golden["case_id"] == case["id"], (
                f"Golden {path.name} case_id={golden['case_id']} != dataset id={case['id']}"
            )

    def test_golden_responses_have_parsed_extraction(self) -> None:
        dataset = _load_dataset()
        for case in dataset:
            path = GOLDEN_DIR / f"{case['id']}.json"
            with open(path) as f:
                golden = json.load(f)
            assert "parsed_extraction" in golden, f"Golden {path.name} missing parsed_extraction"
            assert isinstance(golden["parsed_extraction"], dict), f"Golden {path.name} parsed_extraction not dict"


# ---------------------------------------------------------------------------
# Brier score tests
# ---------------------------------------------------------------------------

class TestBrierScore:
    """Test Brier score computation with known inputs."""

    def test_perfect_calibration(self) -> None:
        """Confidence exactly matches accuracy -> Brier = 0."""
        from autoresearch.eval import CaseResult, brier_score

        results = [
            CaseResult("a", "invoice", 0.9, 1.0, 1.0, 0, True, confidence=0.9),
            CaseResult("b", "receipt", 0.8, 1.0, 1.0, 0, True, confidence=0.8),
        ]
        assert brier_score(results) == pytest.approx(0.0, abs=1e-10)

    def test_worst_calibration(self) -> None:
        """Confidence 1.0, accuracy 0.0 -> Brier = 1.0."""
        from autoresearch.eval import CaseResult, brier_score

        results = [
            CaseResult("a", "invoice", 0.0, 1.0, 0.0, 0, True, confidence=1.0),
        ]
        assert brier_score(results) == pytest.approx(1.0, abs=1e-10)

    def test_known_value(self) -> None:
        """Confidence 0.9, accuracy 0.7 -> Brier = (0.9-0.7)^2 = 0.04."""
        from autoresearch.eval import CaseResult, brier_score

        results = [
            CaseResult("a", "invoice", 0.7, 1.0, 1.0, 0, True, confidence=0.9),
        ]
        assert brier_score(results) == pytest.approx(0.04, abs=1e-10)

    def test_no_confidence_returns_zero(self) -> None:
        """Cases without confidence should return 0.0."""
        from autoresearch.eval import CaseResult, brier_score

        results = [
            CaseResult("a", "invoice", 0.9, 1.0, 1.0, 0, True, confidence=0.0),
        ]
        assert brier_score(results) == 0.0

    def test_empty_results(self) -> None:
        from autoresearch.eval import brier_score

        assert brier_score([]) == 0.0


# ---------------------------------------------------------------------------
# Calibration curve tests
# ---------------------------------------------------------------------------

class TestCalibrationCurve:
    """Test calibration curve binning."""

    def test_single_bin(self) -> None:
        from autoresearch.eval import CaseResult, calibration_curve

        results = [
            CaseResult("a", "invoice", 0.9, 1.0, 1.0, 0, True, confidence=0.85),
            CaseResult("b", "invoice", 0.95, 1.0, 1.0, 0, True, confidence=0.90),
        ]
        curve = calibration_curve(results, n_bins=5)
        # Both cases fall in 0.8-1.0 bin
        high_bin = [b for b in curve if b["bin_lower"] == 0.8]
        assert len(high_bin) == 1
        assert high_bin[0]["count"] == 2

    def test_empty_results(self) -> None:
        from autoresearch.eval import calibration_curve

        assert calibration_curve([]) == []

    def test_no_confidence(self) -> None:
        from autoresearch.eval import CaseResult, calibration_curve

        results = [CaseResult("a", "invoice", 0.9, 1.0, 1.0, 0, True, confidence=0.0)]
        assert calibration_curve(results) == []


# ---------------------------------------------------------------------------
# Model comparison table tests
# ---------------------------------------------------------------------------

class TestModelComparisonTable:
    """Test model cost/accuracy comparison table generation."""

    def test_generates_rows(self) -> None:
        from autoresearch.eval import CaseResult, model_comparison_table

        results = [
            CaseResult("a", "invoice", 0.9, 1.0, 1.0, 0, True, confidence=0.9, model="claude-sonnet-4-6", input_tokens=1200, output_tokens=400),
            CaseResult("b", "invoice", 0.8, 1.0, 1.0, 0, True, confidence=0.8, model="claude-haiku-4-5", input_tokens=1200, output_tokens=400),
        ]
        table = model_comparison_table(results)
        assert len(table) == 2
        models = {r["model"] for r in table}
        assert "claude-sonnet-4-6" in models
        assert "claude-haiku-4-5" in models

    def test_cost_calculation(self) -> None:
        from autoresearch.eval import CaseResult, model_comparison_table

        results = [
            CaseResult("a", "invoice", 0.9, 1.0, 1.0, 0, True, confidence=0.9,
                       model="claude-sonnet-4-6", input_tokens=1000, output_tokens=1000),
        ]
        table = model_comparison_table(results)
        row = table[0]
        # Expected: (1000/1000 * 0.003) + (1000/1000 * 0.015) = 0.018
        assert row["est_cost_usd"] == pytest.approx(0.018, abs=1e-4)

    def test_empty_results(self) -> None:
        from autoresearch.eval import model_comparison_table

        assert model_comparison_table([]) == []

    def test_groups_by_model_and_doc_type(self) -> None:
        from autoresearch.eval import CaseResult, model_comparison_table

        results = [
            CaseResult("a", "invoice", 0.9, 1.0, 1.0, 0, True, model="sonnet"),
            CaseResult("b", "invoice", 0.8, 1.0, 1.0, 0, True, model="sonnet"),
            CaseResult("c", "receipt", 0.7, 1.0, 1.0, 0, True, model="sonnet"),
        ]
        table = model_comparison_table(results)
        assert len(table) == 2  # sonnet/invoice + sonnet/receipt


# ---------------------------------------------------------------------------
# Alert rules YAML validity
# ---------------------------------------------------------------------------

class TestAlertRules:
    """Verify Prometheus alert rules are valid YAML."""

    @pytest.mark.skipif(not ALERTS_PATH.exists(), reason="alerts.yml not found")
    def test_alerts_yaml_loads(self) -> None:
        with open(ALERTS_PATH) as f:
            data = yaml.safe_load(f)
        assert data is not None
        assert "groups" in data, "alerts.yml missing 'groups' key"

    @pytest.mark.skipif(not ALERTS_PATH.exists(), reason="alerts.yml not found")
    def test_alerts_have_names(self) -> None:
        with open(ALERTS_PATH) as f:
            data = yaml.safe_load(f)
        for group in data.get("groups", []):
            for rule in group.get("rules", []):
                assert "alert" in rule or "record" in rule, f"Rule missing alert/record name: {rule}"


# ---------------------------------------------------------------------------
# Scoring function tests for adversarial inputs
# ---------------------------------------------------------------------------

class TestAdversarialScoring:
    """Test that scoring functions handle adversarial inputs correctly."""

    def test_null_expected_null_extracted(self) -> None:
        from autoresearch.eval import score_extraction

        extracted = {"field": None}
        expected = {"field": None}
        score = score_extraction(extracted, expected, [])
        assert score == 1.0

    def test_empty_input_text_no_hallucination(self) -> None:
        from autoresearch.eval import detect_hallucinations

        result = detect_hallucinations(
            {"field": None},
            {"field": None},
            "",
        )
        assert result == []

    def test_corrupted_text_scoring(self) -> None:
        """Null bytes in input should not crash scoring."""
        from autoresearch.eval import score_extraction

        extracted = {"invoice_number": "INV-2024-CORRUPT", "total_amount": None}
        expected = {"invoice_number": "INV-2024-CORRUPT", "total_amount": None}
        score = score_extraction(extracted, expected, ["invoice_number", "total_amount"])
        assert score == 1.0

    def test_duplicate_content_deduplication(self) -> None:
        """Duplicate page content should not double-count line items."""
        from autoresearch.eval import score_extraction

        extracted = {
            "line_items": [
                {"description": "Consulting Services", "quantity": 10.0, "unit_price": 150.0, "total": 1500.0},
            ],
        }
        expected = {
            "line_items": [
                {"description": "Consulting Services", "quantity": 10.0, "unit_price": 150.0, "total": 1500.0},
            ],
        }
        score = score_extraction(extracted, expected, [])
        assert score == 1.0
