"""Tests for default model routing config — Anthropic-only chains."""
from app.config import Settings


def test_extraction_models_anthropic_only():
    s = Settings()
    assert s.extraction_models == ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"]
    assert all("glm" not in m for m in s.extraction_models)


def test_classification_models_anthropic_only():
    s = Settings()
    assert s.classification_models == ["claude-haiku-4-5-20251001", "claude-sonnet-4-6"]
    assert all("glm" not in m for m in s.classification_models)
