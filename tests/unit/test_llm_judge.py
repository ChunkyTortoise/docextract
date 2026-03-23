"""Tests for LLM-as-judge evaluator — no real API calls."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm_judge import JudgeResult, LLMJudge, _parse_judge_json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_text_block(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    return block


def _make_response(text: str) -> MagicMock:
    response = MagicMock()
    response.content = [_make_text_block(text)]
    return response


def _judge_json(
    score: float = 0.8,
    reasoning: str = "looks good",
    passed: bool = True,
    evidence: list[str] | None = None,
    threshold: float = 0.7,
) -> str:
    return json.dumps(
        {
            "score": score,
            "reasoning": reasoning,
            "passed": passed,
            "evidence": evidence or ["supporting quote"],
            "threshold": threshold,
        }
    )


# ---------------------------------------------------------------------------
# Feature flag off — returns None
# ---------------------------------------------------------------------------


class TestFeatureFlagOff:
    @pytest.mark.asyncio
    async def test_returns_none_when_disabled(self):
        with patch("app.services.llm_judge.settings") as mock_settings:
            mock_settings.llm_judge_enabled = False
            judge = LLMJudge()
            result = await judge.evaluate(
                question="What is the total?",
                answer="The total is $100.",
                contexts=["Total: $100"],
                rubric="Score 1.0 if the answer matches the context value.",
            )
        assert result is None


# ---------------------------------------------------------------------------
# JudgeResult fields
# ---------------------------------------------------------------------------


class TestJudgeResultFields:
    @pytest.mark.asyncio
    @patch("app.services.llm_judge.AsyncAnthropic")
    async def test_returns_judge_result_with_correct_fields(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        client.messages.create = AsyncMock(return_value=_make_response(_judge_json(0.85)))

        with patch("app.services.llm_judge.settings") as mock_settings:
            mock_settings.llm_judge_enabled = True
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.classification_models = ["claude-haiku-4-5-20251001"]

            judge = LLMJudge()
            judge._client = client
            result = await judge.evaluate(
                question="What is the vendor?",
                answer="The vendor is Acme Corp.",
                contexts=["Vendor: Acme Corp"],
                rubric="Score 1.0 if vendor name matches.",
                threshold=0.7,
            )

        assert isinstance(result, JudgeResult)
        assert hasattr(result, "score")
        assert hasattr(result, "reasoning")
        assert hasattr(result, "passed")
        assert hasattr(result, "evidence")
        assert hasattr(result, "threshold")

    @pytest.mark.asyncio
    @patch("app.services.llm_judge.AsyncAnthropic")
    async def test_score_is_float_between_0_and_1(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        client.messages.create = AsyncMock(return_value=_make_response(_judge_json(0.9)))

        with patch("app.services.llm_judge.settings") as mock_settings:
            mock_settings.llm_judge_enabled = True
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.classification_models = ["claude-haiku-4-5-20251001"]

            judge = LLMJudge()
            judge._client = client
            result = await judge.evaluate("q", "a", ["ctx"], "rubric")

        assert isinstance(result.score, float)
        assert 0.0 <= result.score <= 1.0


# ---------------------------------------------------------------------------
# passed flag
# ---------------------------------------------------------------------------


class TestPassedFlag:
    @pytest.mark.asyncio
    @patch("app.services.llm_judge.AsyncAnthropic")
    async def test_passed_true_when_score_above_threshold(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        client.messages.create = AsyncMock(
            return_value=_make_response(_judge_json(score=0.85, passed=True, threshold=0.7))
        )

        with patch("app.services.llm_judge.settings") as mock_settings:
            mock_settings.llm_judge_enabled = True
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.classification_models = ["claude-haiku-4-5-20251001"]

            judge = LLMJudge()
            judge._client = client
            result = await judge.evaluate("q", "a", ["ctx"], "rubric", threshold=0.7)

        assert result.passed is True

    @pytest.mark.asyncio
    @patch("app.services.llm_judge.AsyncAnthropic")
    async def test_passed_false_when_score_below_threshold(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        # API returns passed=False for score 0.5
        client.messages.create = AsyncMock(
            return_value=_make_response(_judge_json(score=0.5, passed=False, threshold=0.7))
        )

        with patch("app.services.llm_judge.settings") as mock_settings:
            mock_settings.llm_judge_enabled = True
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.classification_models = ["claude-haiku-4-5-20251001"]

            judge = LLMJudge()
            judge._client = client
            result = await judge.evaluate("q", "a", ["ctx"], "rubric", threshold=0.7)

        assert result.passed is False

    @pytest.mark.asyncio
    @patch("app.services.llm_judge.AsyncAnthropic")
    async def test_passed_derived_from_score_if_not_in_json(self, mock_cls):
        """If the API omits 'passed', it is derived from score >= threshold."""
        client = MagicMock()
        mock_cls.return_value = client
        # JSON without 'passed' key
        raw = json.dumps({"score": 0.8, "reasoning": "ok", "evidence": ["q"], "threshold": 0.7})
        client.messages.create = AsyncMock(return_value=_make_response(raw))

        with patch("app.services.llm_judge.settings") as mock_settings:
            mock_settings.llm_judge_enabled = True
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.classification_models = ["claude-haiku-4-5-20251001"]

            judge = LLMJudge()
            judge._client = client
            result = await judge.evaluate("q", "a", ["ctx"], "rubric", threshold=0.7)

        assert result.passed is True  # 0.8 >= 0.7


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    @pytest.mark.asyncio
    async def test_returns_none_on_api_error(self):
        with patch("app.services.llm_judge.settings") as mock_settings:
            mock_settings.llm_judge_enabled = True
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.classification_models = ["claude-haiku-4-5-20251001"]

            judge = LLMJudge()
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(side_effect=Exception("API error"))
            judge._client = mock_client

            result = await judge.evaluate("q", "a", ["ctx"], "rubric")

        assert result is None


# ---------------------------------------------------------------------------
# _parse_judge_json
# ---------------------------------------------------------------------------


class TestParseJudgeJson:
    def test_direct_json(self):
        raw = '{"score": 0.9, "reasoning": "r", "passed": true, "evidence": [], "threshold": 0.7}'
        result = _parse_judge_json(raw)
        assert result["score"] == 0.9
        assert result["passed"] is True

    def test_json_in_code_fence(self):
        raw = '```json\n{"score": 0.7, "reasoning": "ok", "passed": true, "evidence": [], "threshold": 0.7}\n```'
        result = _parse_judge_json(raw)
        assert result["score"] == 0.7

    def test_invalid_returns_empty_dict(self):
        result = _parse_judge_json("not json")
        assert result == {}
