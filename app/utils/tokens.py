from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Estimate token count: len(text)/4 * 1.5 rounded to int."""
    return int(len(text) / 4 * 1.5)
