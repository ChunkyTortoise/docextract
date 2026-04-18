"""LLM-as-judge evaluator — Gemini 2.5 primary, Claude fallback.

Feature-flagged behind LLM_JUDGE_ENABLED=true (default off).

The judge accepts an explicit rubric with few-shot examples embedded in the
prompt, then returns a JudgeResult containing the score, reasoning, pass/fail
flag, and supporting evidence quotes extracted from the contexts.

Provider order: Gemini 2.5 Flash (independent reviewer) → Claude Haiku (fallback).
Using a different provider as the primary judge eliminates self-grading bias where
Claude evaluates its own extractions.
"""
from __future__ import annotations

import json
import logging
import re

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

_JUDGE_PROMPT = """You are a strict evaluation judge. Your job is to score a model's answer against a rubric.

=== RUBRIC ===
{rubric}

=== FEW-SHOT EXAMPLES ===
Example 1 — score 1.0 (perfect):
  Question: "What is the invoice total?"
  Answer: "The total is $1,250.00 including tax."
  Contexts: ["Invoice total: $1,250.00 (tax included)"]
  Output: {{"score": 1.0, "reasoning": "Answer matches context exactly.", "passed": true, "evidence": ["Invoice total: $1,250.00 (tax included)"], "threshold": 0.7}}

Example 2 — score 0.4 (partial):
  Question: "What is the vendor name?"
  Answer: "The vendor is ABC Corp."
  Contexts: ["Invoice issued by XYZ Ltd on 2024-01-15"]
  Output: {{"score": 0.4, "reasoning": "Answer names a different vendor than the context.", "passed": false, "evidence": ["Invoice issued by XYZ Ltd on 2024-01-15"], "threshold": 0.7}}

=== INPUT TO EVALUATE ===
Question: {question}

Answer: {answer}

Contexts:
{contexts}

Threshold for passing: {threshold}

=== INSTRUCTIONS ===
1. Score the answer against the rubric on a scale of 0.0–1.0.
2. Extract 1–3 direct quotes from the contexts that most support your score (or contradict the answer).
3. Set "passed" to true if score >= threshold, false otherwise.
4. Return valid JSON only — no prose before or after.

Required JSON shape:
{{
  "score": <float 0.0–1.0>,
  "reasoning": "<one sentence>",
  "passed": <bool>,
  "evidence": ["<quote 1>", "<quote 2>"],
  "threshold": {threshold}
}}
"""


class JudgeResult(BaseModel):
    score: float          # 0-1
    reasoning: str
    passed: bool          # score >= threshold
    evidence: list[str]   # specific quotes from context supporting score
    threshold: float
    judge_model: str = "unknown"  # which model produced this verdict


class LLMJudge:
    """Feature-flagged LLM-as-judge evaluator.

    Tries Gemini 2.5 Flash first (independent provider), falls back to
    Claude Haiku. Set LLM_JUDGE_ENABLED=true to activate.
    """

    def __init__(self) -> None:
        self._claude_client: AsyncAnthropic | None = None
        self._gemini_client = None  # lazy-init to avoid import cost

    def _get_claude_client(self) -> AsyncAnthropic:
        if self._claude_client is None:
            self._claude_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._claude_client

    def _get_gemini_client(self):
        if self._gemini_client is None:
            from app.services.providers.gemini_provider import GeminiJudgeClient
            gemini_key = getattr(settings, "gemini_api_key", None) or getattr(settings, "google_api_key", None)
            if not gemini_key:
                return None
            self._gemini_client = GeminiJudgeClient(api_key=gemini_key)
        return self._gemini_client

    async def evaluate(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        rubric: str,
        threshold: float = 0.7,
    ) -> JudgeResult | None:
        """Returns None if disabled. Tries Gemini first, falls back to Claude."""
        if not settings.llm_judge_enabled:
            return None

        contexts_text = "\n\n".join(f"[Context {i+1}]\n{c}" for i, c in enumerate(contexts))
        prompt = _JUDGE_PROMPT.format(
            rubric=rubric,
            question=question,
            answer=answer,
            contexts=contexts_text,
            threshold=threshold,
        )

        # Primary: Gemini (independent provider, eliminates self-grading bias)
        gemini = self._get_gemini_client()
        if gemini is not None:
            result = await self._evaluate_with_gemini(gemini, prompt, threshold)
            if result is not None:
                return result
            logger.warning("Gemini judge failed — falling back to Claude")

        # Fallback: Claude Haiku
        return await self._evaluate_with_claude(prompt, threshold)

    async def _evaluate_with_gemini(self, gemini_client, prompt: str, threshold: float) -> JudgeResult | None:
        from app.services.providers.gemini_provider import DEFAULT_JUDGE_MODEL

        try:
            response = await gemini_client.generate(prompt, max_tokens=512)
            raw = response.content[0].text
            data = _parse_judge_json(raw)
            score = max(0.0, min(1.0, float(data.get("score", 0.0))))
            return JudgeResult(
                score=score,
                reasoning=str(data.get("reasoning", "")),
                passed=bool(data.get("passed", score >= threshold)),
                evidence=list(data.get("evidence", [])),
                threshold=threshold,
                judge_model=DEFAULT_JUDGE_MODEL,
            )
        except Exception as exc:
            logger.warning("Gemini judge evaluate failed: %s", exc)
            return None

    async def _evaluate_with_claude(self, prompt: str, threshold: float) -> JudgeResult | None:
        try:
            claude_model = settings.classification_models[0]
            client = self._get_claude_client()
            response = await client.messages.create(
                model=claude_model,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text
            data = _parse_judge_json(raw)
            score = max(0.0, min(1.0, float(data.get("score", 0.0))))
            return JudgeResult(
                score=score,
                reasoning=str(data.get("reasoning", "")),
                passed=bool(data.get("passed", score >= threshold)),
                evidence=list(data.get("evidence", [])),
                threshold=threshold,
                judge_model=claude_model,
            )
        except Exception as exc:
            logger.warning("LLMJudge.evaluate (Claude fallback) failed: %s", exc)
            return None


def _parse_judge_json(text: str) -> dict:
    """Extract JSON from a judge response."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    obj_match = re.search(r"\{.*\}", text, re.DOTALL)
    if obj_match:
        try:
            return json.loads(obj_match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning("Could not parse judge JSON from: %s...", text[:120])
    return {}
