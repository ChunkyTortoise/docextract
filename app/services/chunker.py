"""Page-based text chunker for LLM processing."""
from app.services.prompt_config import config as _prompt_config
from app.utils.tokens import estimate_tokens

# Sourced from prompt_config so autoresearch can tune them; keep as module-level
# names so existing imports (tests, other modules) continue to work.
MAX_CHUNK_TOKENS = _prompt_config.params.max_chunk_tokens
OVERLAP_CHARS = _prompt_config.params.overlap_chars
PAGE_MARKER_PREFIX = "---PAGE "


def chunk_text(text: str) -> list[str]:
    """Split text into chunks suitable for LLM processing.

    Strategy:
    1. Split on page markers if present
    2. If any page chunk > MAX_CHUNK_TOKENS, split further
    3. Add 200-char overlap between chunks

    Returns:
        List of text chunks maintaining reading order
    """
    if not text.strip():
        return []

    # Split on page markers
    if PAGE_MARKER_PREFIX in text:
        pages = _split_on_page_markers(text)
    else:
        pages = [text]

    # Split oversized pages and add overlap
    chunks: list[str] = []
    for page in pages:
        sub_chunks = _split_if_oversized(page)
        if chunks and sub_chunks:
            # Add overlap: prepend end of previous chunk
            overlap = chunks[-1][-OVERLAP_CHARS:] if len(chunks[-1]) > OVERLAP_CHARS else chunks[-1]
            sub_chunks[0] = overlap + sub_chunks[0]
        chunks.extend(sub_chunks)

    return chunks


def _split_on_page_markers(text: str) -> list[str]:
    """Split text on ---PAGE n--- markers."""
    import re

    parts = re.split(r"\n---PAGE \d+---\n", text)
    return [p.strip() for p in parts if p.strip()]


def _split_if_oversized(text: str) -> list[str]:
    """Split text at sentence boundaries if it exceeds MAX_CHUNK_TOKENS."""
    if estimate_tokens(text) <= MAX_CHUNK_TOKENS:
        return [text]

    # Split at sentence boundaries
    import re

    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        candidate = (current + " " + sentence).strip() if current else sentence
        if estimate_tokens(candidate) > MAX_CHUNK_TOKENS and current:
            chunks.append(current)
            current = sentence
        else:
            current = candidate

    if current:
        chunks.append(current)

    return chunks if chunks else [text]
