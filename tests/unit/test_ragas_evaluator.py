"""Tests for RAGAS-inspired evaluator — no real API calls."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ragas_evaluator import RAGASEvaluator, RAGASScores, _parse_score_json

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


def _score_json(score: float, reasoning: str = "test reasoning") -> str:
    return json.dumps({"score": score, "reasoning": reasoning})


# ---------------------------------------------------------------------------
# _parse_score_json
# ---------------------------------------------------------------------------


class TestParseScoreJson:
    def test_direct_json(self):
        result = _parse_score_json('{"score": 0.9, "reasoning": "good"}')
        assert result == {"score": 0.9, "reasoning": "good"}

    def test_json_in_code_fence(self):
        text = '```json\n{"score": 0.8, "reasoning": "ok"}\n```'
        result = _parse_score_json(text)
        assert result["score"] == 0.8

    def test_json_embedded_in_prose(self):
        text = 'Here is my answer: {"score": 0.75, "reasoning": "partial"} done.'
        result = _parse_score_json(text)
        assert result["score"] == 0.75

    def test_invalid_returns_empty_dict(self):
        result = _parse_score_json("no json at all")
        assert result == {}


# ---------------------------------------------------------------------------
# Feature flag off — all metrics return None
# ---------------------------------------------------------------------------


class TestFeatureFlagOff:
    @pytest.mark.asyncio
    async def test_evaluate_returns_none_values_when_disabled(self):
        with patch("app.services.ragas_evaluator.settings") as mock_settings:
            mock_settings.ragas_enabled = False
            evaluator = RAGASEvaluator()
            result = await evaluator.evaluate(
                question="What is the total?",
                answer="The total is $100.",
                contexts=["Total: $100"],
                ground_truth="Total is one hundred dollars.",
            )
        assert isinstance(result, RAGASScores)
        assert result.context_recall is None
        assert result.faithfulness is None
        assert result.answer_relevancy is None
        assert result.overall is None


# ---------------------------------------------------------------------------
# context_recall
# ---------------------------------------------------------------------------


class TestComputeContextRecall:
    @pytest.mark.asyncio
    @patch("app.services.ragas_evaluator.AsyncAnthropic")
    async def test_returns_float_between_0_and_1(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        client.messages.create = AsyncMock(return_value=_make_response(_score_json(0.85)))

        evaluator = RAGASEvaluator()
        evaluator._client = client

        score = await evaluator.compute_context_recall(
            question="What is vendor?",
            contexts=["Vendor: Acme Corp"],
            ground_truth="Vendor is Acme Corp",
        )
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    @patch("app.services.ragas_evaluator.AsyncAnthropic")
    async def test_score_clamped_to_max_1(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        client.messages.create = AsyncMock(return_value=_make_response(_score_json(1.5)))

        evaluator = RAGASEvaluator()
        evaluator._client = client

        score = await evaluator.compute_context_recall("q", ["ctx"], "gt")
        assert score <= 1.0

    @pytest.mark.asyncio
    @patch("app.services.ragas_evaluator.AsyncAnthropic")
    async def test_score_clamped_to_min_0(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        client.messages.create = AsyncMock(return_value=_make_response(_score_json(-0.5)))

        evaluator = RAGASEvaluator()
        evaluator._client = client

        score = await evaluator.compute_context_recall("q", ["ctx"], "gt")
        assert score >= 0.0


# ---------------------------------------------------------------------------
# faithfulness
# ---------------------------------------------------------------------------


class TestComputeFaithfulness:
    @pytest.mark.asyncio
    @patch("app.services.ragas_evaluator.AsyncAnthropic")
    async def test_returns_float_between_0_and_1(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        client.messages.create = AsyncMock(return_value=_make_response(_score_json(0.9)))

        evaluator = RAGASEvaluator()
        evaluator._client = client

        score = await evaluator.compute_faithfulness(
            answer="The total is $100.",
            contexts=["Invoice total: $100"],
        )
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    @patch("app.services.ragas_evaluator.AsyncAnthropic")
    async def test_uses_classification_model(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        client.messages.create = AsyncMock(return_value=_make_response(_score_json(0.7)))

        with patch("app.services.ragas_evaluator.settings") as mock_settings:
            mock_settings.ragas_enabled = True
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.classification_models = ["claude-haiku-4-5-20251001"]
            evaluator = RAGASEvaluator()
            evaluator._client = client
            await evaluator.compute_faithfulness("answer", ["context"])

        call_kwargs = client.messages.create.call_args
        assert call_kwargs.kwargs["model"] == "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# answer_relevancy
# ---------------------------------------------------------------------------


class TestComputeAnswerRelevancy:
    @pytest.mark.asyncio
    @patch("app.services.ragas_evaluator.AsyncAnthropic")
    async def test_returns_float_between_0_and_1(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        client.messages.create = AsyncMock(return_value=_make_response(_score_json(0.95)))

        evaluator = RAGASEvaluator()
        evaluator._client = client

        score = await evaluator.compute_answer_relevancy(
            question="What is the total?",
            answer="The total is $100.",
        )
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# evaluate() — full pipeline
# ---------------------------------------------------------------------------


class TestEvaluate:
    @pytest.mark.asyncio
    @patch("app.services.ragas_evaluator.AsyncAnthropic")
    async def test_returns_ragas_scores_with_all_metrics(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        client.messages.create = AsyncMock(return_value=_make_response(_score_json(0.8)))

        with patch("app.services.ragas_evaluator.settings") as mock_settings:
            mock_settings.ragas_enabled = True
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.classification_models = ["claude-haiku-4-5-20251001"]
            evaluator = RAGASEvaluator()
            evaluator._client = client
            result = await evaluator.evaluate(
                question="What is the total?",
                answer="The total is $100.",
                contexts=["Total: $100"],
                ground_truth="Total is one hundred dollars.",
            )

        assert isinstance(result, RAGASScores)
        assert result.context_recall is not None
        assert result.faithfulness is not None
        assert result.answer_relevancy is not None
        assert result.overall is not None
        assert 0.0 <= result.overall <= 1.0

    @pytest.mark.asyncio
    @patch("app.services.ragas_evaluator.AsyncAnthropic")
    async def test_skips_context_recall_when_no_ground_truth(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        client.messages.create = AsyncMock(return_value=_make_response(_score_json(0.8)))

        with patch("app.services.ragas_evaluator.settings") as mock_settings:
            mock_settings.ragas_enabled = True
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.classification_models = ["claude-haiku-4-5-20251001"]
            evaluator = RAGASEvaluator()
            evaluator._client = client
            result = await evaluator.evaluate(
                question="q",
                answer="a",
                contexts=["ctx"],
                ground_truth=None,
            )

        assert result.context_recall is None
        # faithfulness and relevancy should still be computed
        assert result.faithfulness is not None
        assert result.answer_relevancy is not None

    @pytest.mark.asyncio
    async def test_graceful_degradation_on_api_error(self):
        """When the API raises, _call_judge returns 0.0 (no crash)."""
        with patch("app.services.ragas_evaluator.settings") as mock_settings:
            mock_settings.ragas_enabled = True
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.classification_models = ["claude-haiku-4-5-20251001"]

            evaluator = RAGASEvaluator()
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(side_effect=Exception("API error"))
            evaluator._client = mock_client

            score = await evaluator.compute_faithfulness("answer", ["ctx"])

        assert score == 0.0
