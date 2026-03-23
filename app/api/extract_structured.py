"""Structured extraction endpoints — typed Pydantic output per document type."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.middleware import get_api_key
from app.config import settings
from app.dependencies import get_db
from app.models.api_key import APIKey
from app.schemas.extraction_models import BatchExtractionResult, StructuredExtractionResponse
from app.services.model_router import ModelRouter

router = APIRouter(tags=["structured-extraction"])


class SingleExtractionRequest(BaseModel):
    doc_id: str
    doc_type: str | None = None


class BatchExtractionRequest(BaseModel):
    doc_ids: list[str]


def _make_extractor() -> "object":
    from app.services.structured_extractor import StructuredExtractor

    model_router = ModelRouter(
        failure_threshold=settings.circuit_breaker_failure_threshold,
        recovery_timeout=settings.circuit_breaker_recovery_seconds,
    )
    return StructuredExtractor(model_router=model_router)


@router.post("/extract/structured", response_model=StructuredExtractionResponse)
async def extract_structured(
    request: SingleExtractionRequest,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
) -> StructuredExtractionResponse:
    """Extract structured data from a single document using a Pydantic schema.

    Classifies the document type if not provided, then calls Claude with a
    type-specific extraction prompt. Returns a validated, typed extraction result.
    """
    extractor = _make_extractor()
    return await extractor.extract(
        doc_id=request.doc_id,
        doc_type=request.doc_type,
        db=db,
    )


@router.post("/extract/structured/batch", response_model=BatchExtractionResult)
async def extract_structured_batch(
    request: BatchExtractionRequest,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
) -> BatchExtractionResult:
    """Extract structured data from multiple documents in parallel.

    Uses asyncio.gather with a semaphore (max 5 concurrent Claude calls).
    Returns aggregated results with success/failure counts.
    """
    extractor = _make_extractor()
    return await extractor.extract_batch(doc_ids=request.doc_ids, db=db)
