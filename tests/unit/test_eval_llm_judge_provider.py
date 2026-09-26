"""Judge default provider: Gemini-first with an explicit anthropic fallback.

Lane A P1: default --provider gemini, falling back to anthropic with a logged
warning. Acceptance: llm_judge.json records judge_model gemini-* when
GEMINI_API_KEY is set, and README's "Gemini-first judge" wording matches.
"""
from __future__ import annotations

from scripts.eval_llm_judge import DEFAULT_JUDGE_MODELS, resolve_provider, summarize


def test_resolve_provider_defaults_gemini_with_key():
    assert resolve_provider("gemini", env={"GEMINI_API_KEY": "k"}) == "gemini"


def test_resolve_provider_falls_back_to_anthropic_without_key():
    assert resolve_provider("gemini", env={}) == "anthropic"


def test_resolve_provider_keeps_explicit_choice():
    assert resolve_provider("openai", env={}) == "openai"


def test_summarize_records_judge_model_gemini():
    summary = summarize([], provider="gemini", model=DEFAULT_JUDGE_MODELS["gemini"])
    assert summary["judge_model"].startswith("gemini-")
    assert summary["provider"] == "gemini"
