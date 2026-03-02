"""Tests for chunker service."""
import pytest

from app.services.chunker import (
    MAX_CHUNK_TOKENS,
    OVERLAP_CHARS,
    chunk_text,
    _split_on_page_markers,
    _split_if_oversized,
)
from app.utils.tokens import estimate_tokens


class TestChunkTextEmpty:
    def test_empty_string(self):
        assert chunk_text("") == []

    def test_whitespace_only(self):
        assert chunk_text("   \n\t  ") == []


class TestChunkTextSingleChunk:
    def test_short_text(self):
        result = chunk_text("Hello world.")
        assert result == ["Hello world."]

    def test_medium_text_under_limit(self):
        text = "A sentence. " * 50
        result = chunk_text(text.strip())
        assert len(result) == 1


class TestChunkTextPageMarkers:
    def test_two_pages(self):
        text = "Page one content.\n---PAGE 2---\nPage two content."
        result = chunk_text(text)
        assert len(result) == 2
        assert "Page one" in result[0]
        assert "Page two" in result[1]

    def test_three_pages(self):
        text = "First.\n---PAGE 2---\nSecond.\n---PAGE 3---\nThird."
        result = chunk_text(text)
        assert len(result) == 3

    def test_empty_pages_filtered(self):
        text = "Content.\n---PAGE 2---\n\n---PAGE 3---\nMore content."
        result = chunk_text(text)
        assert len(result) == 2


class TestChunkTextOversize:
    def test_long_text_split(self):
        # Generate text that exceeds MAX_CHUNK_TOKENS
        # estimate_tokens = len(text)/4 * 1.5, so need ~10667 chars for 4000 tokens
        text = "This is a test sentence. " * 500  # ~12500 chars
        assert estimate_tokens(text) > MAX_CHUNK_TOKENS
        result = chunk_text(text)
        assert len(result) > 1

    def test_each_chunk_under_limit(self):
        text = "This is a test sentence. " * 500
        result = chunk_text(text)
        # First chunk should be under limit; subsequent may have overlap
        for chunk in result:
            # Allow some slack for overlap
            assert estimate_tokens(chunk) <= MAX_CHUNK_TOKENS + estimate_tokens("x" * OVERLAP_CHARS) + 100


class TestChunkTextOverlap:
    def test_overlap_between_page_chunks(self):
        # Create two pages where second should get overlap from first
        page1 = "First page content is here. " * 20
        page2 = "Second page content. " * 5
        text = f"{page1}\n---PAGE 2---\n{page2}"
        result = chunk_text(text)
        assert len(result) == 2
        # Second chunk should start with overlap from first
        tail_of_first = result[0][-OVERLAP_CHARS:]
        assert result[1].startswith(tail_of_first)


class TestSplitOnPageMarkers:
    def test_basic_split(self):
        text = "A\n---PAGE 2---\nB\n---PAGE 3---\nC"
        result = _split_on_page_markers(text)
        assert result == ["A", "B", "C"]


class TestSplitIfOversized:
    def test_small_text_unchanged(self):
        result = _split_if_oversized("Short text.")
        assert result == ["Short text."]

    def test_large_text_splits(self):
        # estimate_tokens = len/4*1.5; need > 10667 chars for > 4000 tokens
        text = "Sentence number one. " * 600  # 12600 chars -> ~4725 tokens
        assert estimate_tokens(text) > MAX_CHUNK_TOKENS
        result = _split_if_oversized(text)
        assert len(result) > 1
