"""Document embedding using sentence-transformers."""
from __future__ import annotations

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

MODEL_NAME = "all-MiniLM-L6-v2"
MAX_TOKENS = 512  # Model's max input length


@lru_cache(maxsize=1)
def _get_model():
    """Load model once and cache."""
    from sentence_transformers import SentenceTransformer
    logger.info("Loading embedding model: %s", MODEL_NAME)
    return SentenceTransformer(MODEL_NAME)


def embed(text: str) -> list[float]:
    """Embed a single text string.

    Returns:
        384-dimensional float vector
    """
    # Truncate to avoid exceeding model's max input
    truncated = text[:MAX_TOKENS * 4]  # rough char estimate
    model = _get_model()
    embedding = model.encode(truncated, normalize_embeddings=True)
    return embedding.tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed multiple texts efficiently in batch."""
    truncated = [t[:MAX_TOKENS * 4] for t in texts]
    model = _get_model()
    embeddings = model.encode(truncated, normalize_embeddings=True, batch_size=32)
    return [e.tolist() for e in embeddings]
