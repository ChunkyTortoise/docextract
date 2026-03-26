"""Tests for USE_LOCAL_ADAPTER feature flag in classifier."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.classifier import (
    ClassificationResult,
    _get_best_adapter,
    _predict_with_adapter,
    classify,
)


def _tool_use_response(doc_type: str, confidence: float) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = "classify_document"
    block.input = {"document_type": doc_type, "confidence": confidence, "reasoning": "Claude"}
    resp = MagicMock()
    resp.content = [block]
    return resp


# ---------------------------------------------------------------------------
# _get_best_adapter
# ---------------------------------------------------------------------------


def test_get_best_adapter_empty_registry_returns_none(tmp_path):
    import json

    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps({"version": "1.0", "adapters": []}))

    with patch("scripts.train_qlora.REGISTRY_PATH", reg):
        result = _get_best_adapter()

    assert result is None


def test_get_best_adapter_prefers_all_type(tmp_path):
    import json
    from datetime import datetime

    adapters = [
        {"doc_type": "invoice", "trained_at": "2026-03-01T00:00:00", "adapter_path": "/inv"},
        {"doc_type": "all", "trained_at": "2026-03-02T00:00:00", "adapter_path": "/all"},
    ]
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps({"version": "1.0", "adapters": adapters}))

    with patch("scripts.train_qlora.REGISTRY_PATH", reg):
        result = _get_best_adapter()

    assert result is not None
    assert result["doc_type"] == "all"


# ---------------------------------------------------------------------------
# _predict_with_adapter
# ---------------------------------------------------------------------------


def test_predict_with_adapter_returns_none_on_import_error():
    """When torch/peft not importable, returns None gracefully."""
    with patch.dict("sys.modules", {"torch": None, "peft": None, "transformers": None}):
        result = _predict_with_adapter("some text", {"adapter_path": "/fake", "base_model": "m"})
    assert result is None


# ---------------------------------------------------------------------------
# classify() with USE_LOCAL_ADAPTER
# ---------------------------------------------------------------------------


@patch("app.services.classifier.settings")
@patch("app.services.classifier._get_best_adapter", return_value=None)
@patch("app.services.classifier.AsyncAnthropic")
@pytest.mark.asyncio
async def test_no_registry_falls_back_to_claude(mock_anthropic_cls, mock_get_adapter, mock_settings):
    """When adapter flag on but registry empty, Claude is called."""
    mock_settings.use_local_adapter = True
    mock_settings.anthropic_api_key = "key"
    mock_settings.circuit_breaker_failure_threshold = 5
    mock_settings.circuit_breaker_recovery_seconds = 60.0
    mock_settings.classification_models = ["claude-haiku-4-5-20251001"]

    client = MagicMock()
    mock_anthropic_cls.return_value = client
    client.messages.create = AsyncMock(return_value=_tool_use_response("receipt", 0.90))

    result = await classify("some receipt text", db=None)
    assert result.doc_type == "receipt"
    client.messages.create.assert_called_once()


@patch("app.services.classifier.settings")
@patch("app.services.classifier._get_best_adapter")
@patch("app.services.classifier._predict_with_adapter")
@pytest.mark.asyncio
async def test_adapter_result_returned_without_claude(mock_predict, mock_get_adapter, mock_settings):
    """When adapter succeeds, Claude is NOT called."""
    mock_settings.use_local_adapter = True
    mock_get_adapter.return_value = {"adapter_path": "/fake", "base_model": "mistral"}
    mock_predict.return_value = ClassificationResult("invoice", 0.85, "Local adapter prediction")

    with patch("app.services.classifier.AsyncAnthropic") as mock_claude:
        result = await classify("Invoice #001", db=None)
        mock_claude.assert_not_called()

    assert result.doc_type == "invoice"
    assert result.confidence == 0.85


@patch("app.services.classifier.settings")
@patch("app.services.classifier._get_best_adapter")
@patch("app.services.classifier._predict_with_adapter", return_value=None)
@patch("app.services.classifier.AsyncAnthropic")
@pytest.mark.asyncio
async def test_adapter_failure_falls_back_to_claude(
    mock_anthropic_cls, mock_predict, mock_get_adapter, mock_settings
):
    """When adapter inference fails (returns None), Claude is called."""
    mock_settings.use_local_adapter = True
    mock_settings.anthropic_api_key = "key"
    mock_settings.circuit_breaker_failure_threshold = 5
    mock_settings.circuit_breaker_recovery_seconds = 60.0
    mock_settings.classification_models = ["claude-haiku-4-5-20251001"]
    mock_get_adapter.return_value = {"adapter_path": "/fake", "base_model": "mistral"}

    client = MagicMock()
    mock_anthropic_cls.return_value = client
    client.messages.create = AsyncMock(return_value=_tool_use_response("bank_statement", 0.91))

    result = await classify("bank statement text", db=None)
    assert result.doc_type == "bank_statement"
    client.messages.create.assert_called_once()


@patch("app.services.classifier.settings")
@patch("app.services.classifier.AsyncAnthropic")
@pytest.mark.asyncio
async def test_flag_off_skips_adapter_lookup(mock_anthropic_cls, mock_settings):
    """When use_local_adapter=False, _get_best_adapter is never called."""
    mock_settings.use_local_adapter = False
    mock_settings.anthropic_api_key = "key"
    mock_settings.circuit_breaker_failure_threshold = 5
    mock_settings.circuit_breaker_recovery_seconds = 60.0
    mock_settings.classification_models = ["claude-haiku-4-5-20251001"]

    client = MagicMock()
    mock_anthropic_cls.return_value = client
    client.messages.create = AsyncMock(return_value=_tool_use_response("invoice", 0.95))

    with patch("app.services.classifier._get_best_adapter") as mock_get:
        result = await classify("Invoice text", db=None)
        mock_get.assert_not_called()

    assert result.doc_type == "invoice"
