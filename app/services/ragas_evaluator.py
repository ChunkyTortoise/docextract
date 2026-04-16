"""RAGAS-inspired evaluation metrics using Claude as judge.

Feature-flagged behind RAGAS_ENABLED=true (default off to avoid API costs in CI).

Metrics:
    context_recall    — fraction of ground truth captured in retrieved contexts
    faithfulness      — fraction of answer claims supported by contexts
    answer_relevancy  — how well the answer addresses the question

All scores are 0–1 floats. None values are returned when the flag is off or an
API error occurs, so callers never crash on missing eval data.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from anthropic import AsyncAnthropic

from app.config import settings

logger = logging.getLogger(__name__)

_RECALL_PROMPT = """\
You are an evaluation judge measuring context recall.

TASK: Determine what fraction of the information in GROUND TRUTH is present in
the CONTEXTS below. A statement is "recalled" if the contexts contain the same
fact (exact match or clear paraphrase).

GROUND TRUTH:
{ground_truth}

CONTEXTS:
{contexts}

Evaluate carefully. Return a JSON object with exactly two keys:
  "score": a float between 0.0 and 1.0 representing recall fraction
  "reasoning": one concise sentence explaining your score

Example output:
{{"score": 0.75, "reasoning": "3 of 4 ground-truth facts appear in the contexts; the invoice date is missing."}}

Return only valid JSON, nothing else.
"""

_FAITHFULNESS_PROMPT = """\
You are an evaluation judge measuring faithfulness.

TASK: Break the ANSWER below into individual factual claims. For each claim,
decide whether it is supported by at least one statement in CONTEXTS.
Score = (supported claims) / (total claims). If the answer has no claims, score 1.0.

ANSWER:
{answer}

CONTEXTS:
{contexts}

Return a JSON object with exactly two keys:
  "score": float 0.0–1.0
  "reasoning": one sentence explaining which claims were or were not supported

Example output:
{{"score": 0.8, "reasoning": "4 of 5 claims in the answer are supported; the claim about currency is not found in any context."}}

Return only valid JSON, nothing else.
"""

_RELEVANCY_PROMPT = """\
You are an evaluation judge measuring answer relevancy.

TASK: Assess how directly and completely the ANSWER addresses the QUESTION.
Consider:
  1. Does the answer address what was asked?
  2. Is the answer focused (not full of irrelevant content)?

Score 1.0 = perfectly addresses the question with no irrelevant content.
Score 0.0 = completely off-topic or empty.

QUESTION:
{question}

ANSWER:
{answer}

Return a JSON object with exactly two keys:
  "score": float 0.0–1.0
  "reasoning": one sentence explaining the score

Example output:
{{"score": 0.9, "reasoning": "The answer directly states the invoice total but includes an unnecessary disclaimer."}}

Return only valid JSON, nothing else.
"""


@dataclass
class RAGASScores:
    context_recall: float | None      # 0-1: is ground truth captured in contexts?
    faithfulness: float | None        # 0-1: is answer grounded in contexts?
    answer_relevancy: float | None    # 0-1: does answer address the question?
    overall: float | None             # weighted average of available scores


class RAGASEvaluator:
    """Feature-flagged RAGAS-inspired evaluation using Claude as judge.

    Set RAGAS_ENABLED=true to activate. Default off to avoid API costs in CI.
    """

    # Weights for the overall score (must sum to 1.0 across the three metrics)
    _WEIGHTS = {
        "context_recall": 0.35,
        "faithfulness": 0.40,
        "answer_relevancy": 0.25,
    }

    def __init__(self) -> None:
        self._client: AsyncAnthropic | None = None

    def _get_client(self) -> AsyncAnthropic:
        if self._client is None:
            self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._client

    async def evaluate(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str | None = None,
    ) -> RAGASScores:
        """Compute all three metrics. Returns None values if disabled."""
        if not settings.ragas_enabled:
            return RAGASScores(
                context_recall=None,
                faithfulness=None,
                answer_relevancy=None,
                overall=None,
            )

        contexts_text = "\n\n".join(  # noqa: F841
            f"[Context {i+1}]\n{c}" for i, c in enumerate(contexts)
        )

        recall: float | None = None
        if ground_truth:
            recall = await self.compute_context_recall(question, contexts, ground_truth)

        faithfulness = await self.compute_faithfulness(answer, contexts)
        relevancy = await self.compute_answer_relevancy(question, answer)

        overall = self._compute_overall(recall, faithfulness, relevancy)

        return RAGASScores(
            context_recall=recall,
            faithfulness=faithfulness,
            answer_relevancy=relevancy,
            overall=overall,
        )

    async def compute_context_recall(
        self,
        question: str,
        contexts: list[str],
        ground_truth: str,
    ) -> float:
        """Measures what fraction of ground truth is captured in retrieved contexts."""
        contexts_text = "\n\n".join(f"[Context {i+1}]\n{c}" for i, c in enumerate(contexts))
        prompt = _RECALL_PROMPT.format(
            ground_truth=ground_truth,
            contexts=contexts_text,
        )
        return await self._call_judge(prompt)

    async def compute_faithfulness(
        self,
        answer: str,
        contexts: list[str],
    ) -> float:
        """Measures if each claim in the answer is supported by the contexts."""
        contexts_text = "\n\n".join(f"[Context {i+1}]\n{c}" for i, c in enumerate(contexts))
        prompt = _FAITHFULNESS_PROMPT.format(
            answer=answer,
            contexts=contexts_text,
        )
        return await self._call_judge(prompt)

    async def compute_answer_relevancy(
        self,
        question: str,
        answer: str,
    ) -> float:
        """Measures if the answer actually addresses the question."""
        prompt = _RELEVANCY_PROMPT.format(question=question, answer=answer)
        return await self._call_judge(prompt)

    async def _call_judge(self, prompt: str) -> float:
        """Call Claude and parse the {'score': float, 'reasoning': str} response."""
        try:
            client = self._get_client()
            response = await client.messages.create(
                model=settings.classification_models[0],
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text
            parsed = _parse_score_json(raw)
            score = float(parsed.get("score", 0.0))
            return max(0.0, min(1.0, score))
        except Exception as exc:
            logger.warning("RAGASEvaluator._call_judge failed: %s", exc)
            return 0.0

    def _compute_overall(
        self,
        context_recall: float | None,
        faithfulness: float | None,
        answer_relevancy: float | None,
    ) -> float | None:
        """Weighted average of available metrics."""
        scores: list[tuple[float, float]] = []
        if context_recall is not None:
            scores.append((context_recall, self._WEIGHTS["context_recall"]))
        if faithfulness is not None:
            scores.append((faithfulness, self._WEIGHTS["faithfulness"]))
        if answer_relevancy is not None:
            scores.append((answer_relevancy, self._WEIGHTS["answer_relevancy"]))

        if not scores:
            return None

        total_weight = sum(w for _, w in scores)
        if total_weight == 0:
            return None
        return sum(s * w for s, w in scores) / total_weight


def _parse_score_json(text: str) -> dict:
    """Extract JSON from a Claude response that should contain {score, reasoning}."""
    text = text.strip()
    # Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # JSON inside code fence
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Any JSON object
    obj_match = re.search(r"\{.*\}", text, re.DOTALL)
    if obj_match:
        try:
            return json.loads(obj_match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning("Could not parse score JSON from: %s...", text[:120])
    return {}
