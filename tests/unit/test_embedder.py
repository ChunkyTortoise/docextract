"""Tests for document embedder service (Gemini Embedding API)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def clear_client_cache():
    """Clear the lru_cache between tests."""
    from app.services.embedder import _get_client
    _get_client.cache_clear()
    yield
    _get_client.cache_clear()


def _make_embedding(values: list[float]) -> MagicMock:
    emb = MagicMock()
    emb.values = values
    return emb


def _make_embed_result(embeddings_values: list[list[float]]) -> MagicMock:
    result = MagicMock()
    result.embeddings = [_make_embedding(v) for v in embeddings_values]
    return result


@pytest.mark.asyncio
async def test_embed_returns_list_of_floats():
    """Test embed() returns a list of floats with correct dimensionality."""
    fake_values = [0.1] * 768
    mock_client = MagicMock()
    mock_client.aio.models.embed_content = AsyncMock(
        return_value=_make_embed_result([fake_values])
    )

    with patch("app.services.embedder._get_client", return_value=mock_client):
        from app.services.embedder import embed
        result = await embed("This is a test document.")

    assert isinstance(result, list)
    assert len(result) == 768
    assert all(isinstance(v, float) for v in result)


@pytest.mark.asyncio
async def test_embed_truncates_long_text():
    """Test that long text is truncated to MAX_CHARS before encoding."""
    fake_values = [0.1] * 768
    mock_client = MagicMock()
    mock_client.aio.models.embed_content = AsyncMock(
        return_value=_make_embed_result([fake_values])
    )

    long_text = "x" * 10000

    with patch("app.services.embedder._get_client", return_value=mock_client):
        from app.services.embedder import embed
        await embed(long_text)

    call_kwargs = mock_client.aio.models.embed_content.call_args
    passed_contents = call_kwargs.kwargs.get("contents") or call_kwargs.args[1]
    # contents is a list with one element
    assert len(passed_contents[0]) == 2048  # MAX_CHARS


@pytest.mark.asyncio
async def test_embed_batch_returns_correct_shape():
    """Test embed_batch() returns list of lists with correct dimensions."""
    fake_batch = [[0.1] * 768, [0.2] * 768, [0.3] * 768]
    mock_client = MagicMock()
    mock_client.aio.models.embed_content = AsyncMock(
        return_value=_make_embed_result(fake_batch)
    )

    texts = ["doc one", "doc two", "doc three"]

    with patch("app.services.embedder._get_client", return_value=mock_client):
        from app.services.embedder import embed_batch
        results = await embed_batch(texts)

    assert len(results) == 3
    assert all(len(v) == 768 for v in results)
    assert all(isinstance(v, list) for v in results)
