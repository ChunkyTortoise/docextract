"""Unit tests for eval_llm_judge provider helpers — no API calls."""
from __future__ import annotations

from scripts.eval_llm_judge import (
    DEFAULT_JUDGE_MODELS,
    _parse_score_json,
    summarize,
)


class TestParseScoreJson:
    def test_parses_raw_json(self):
        data = _parse_score_json('{"faithfulness": 5, "verdict": "pass"}')
        assert data == {"faithfulness": 5, "verdict": "pass"}

    def test_parses_fenced_json(self):
        text = 'Here is the result:\n```json\n{"verdict": "fail"}\n```'
        data = _parse_score_json(text)
        assert data == {"verdict": "fail"}

    def test_returns_none_on_invalid(self):
        assert _parse_score_json("not json") is None


class TestSummarizeProviderMetadata:
    def test_includes_provider_and_model(self):
        results = [
            {
                "id": "x",
                "verdict": "pass",
                "scores": {
                    "faithfulness": 5,
                    "completeness": 5,
                    "hallucination_free": 5,
                    "schema_compliance": 5,
                    "safety": 5,
                },
            }
        ]
        summary = summarize(results, provider="openai", model="gpt-4o-mini")
        assert summary["provider"] == "openai"
        assert summary["model"] == "gpt-4o-mini"
        assert summary["pass_rate"] == 1.0

    def test_default_models_defined_for_all_providers(self):
        assert set(DEFAULT_JUDGE_MODELS) == {"anthropic", "openai", "gemini"}
