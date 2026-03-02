"""Tests for document embedder service."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def clear_model_cache():
    """Clear the lru_cache between tests."""
    from app.services.embedder import _get_model
    _get_model.cache_clear()
    yield
    _get_model.cache_clear()


@patch("app.services.embedder.SentenceTransformer", create=True)
def test_embed_returns_list_of_floats(mock_st_class):
    """Test embed() returns a list of floats with correct dimensionality."""
    mock_model = MagicMock()
    mock_model.encode.return_value = np.random.randn(384).astype(np.float32)
    mock_st_class.return_value = mock_model

    # Patch at module level after import
    with patch("app.services.embedder._get_model", return_value=mock_model):
        from app.services.embedder import embed
        result = embed("This is a test document.")

    assert isinstance(result, list)
    assert len(result) == 384
    assert all(isinstance(v, float) for v in result)


@patch("app.services.embedder.SentenceTransformer", create=True)
def test_embed_truncates_long_text(mock_st_class):
    """Test that long text is truncated before encoding."""
    mock_model = MagicMock()
    mock_model.encode.return_value = np.random.randn(384).astype(np.float32)
    mock_st_class.return_value = mock_model

    long_text = "x" * 10000

    with patch("app.services.embedder._get_model", return_value=mock_model):
        from app.services.embedder import embed
        embed(long_text)

    # Check the text passed to encode was truncated
    called_text = mock_model.encode.call_args[0][0]
    assert len(called_text) == 2048  # MAX_TOKENS(512) * 4


@patch("app.services.embedder.SentenceTransformer", create=True)
def test_embed_batch_returns_correct_shape(mock_st_class):
    """Test embed_batch() returns list of lists with correct dimensions."""
    mock_model = MagicMock()
    mock_model.encode.return_value = np.random.randn(3, 384).astype(np.float32)
    mock_st_class.return_value = mock_model

    texts = ["doc one", "doc two", "doc three"]

    with patch("app.services.embedder._get_model", return_value=mock_model):
        from app.services.embedder import embed_batch
        results = embed_batch(texts)

    assert len(results) == 3
    assert all(len(v) == 384 for v in results)
    assert all(isinstance(v, list) for v in results)
