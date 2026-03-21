"""Document embedding using Google Gemini Embedding API."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING

from google import genai
from google.genai import types as genai_types

from app.config import settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "gemini-embedding-2-preview"
OUTPUT_DIM = 768
MAX_CHARS = 2048


@lru_cache(maxsize=1)
def _get_client() -> genai.Client:
    """Create and cache a Gemini client."""
    logger.info("Initialising Gemini embedding client (model: %s)", EMBEDDING_MODEL)
    return genai.Client(api_key=settings.gemini_api_key)


async def embed(text: str, db: "AsyncSession | None" = None) -> list[float]:
    """Embed a single text string.

    Returns:
        768-dimensional float vector
    """
    from app.services.llm_tracer import trace_llm_call

    client = _get_client()
    async with trace_llm_call(db, EMBEDDING_MODEL, "embed") as trace_ctx:
        result = await client.aio.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=[text[:MAX_CHARS]],
            config=genai_types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=OUTPUT_DIM,
            ),
        )
    return list(result.embeddings[0].values)


async def embed_batch(texts: list[str], db: "AsyncSession | None" = None) -> list[list[float]]:
    """Embed multiple texts efficiently in batch."""
    from app.services.llm_tracer import trace_llm_call

    client = _get_client()
    truncated = [t[:MAX_CHARS] for t in texts]
    async with trace_llm_call(db, EMBEDDING_MODEL, "embed") as trace_ctx:
        result = await client.aio.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=truncated,
            config=genai_types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=OUTPUT_DIM,
            ),
        )
    return [list(e.values) for e in result.embeddings]
