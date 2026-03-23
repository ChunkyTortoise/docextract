"""Structured extraction service using document-type-specific Pydantic schemas.

Extracts typed, validated data from documents. Supports single and batch
extraction with parallel processing controlled by an asyncio Semaphore.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import TYPE_CHECKING

from anthropic import AsyncAnthropic
from pydantic import ValidationError

from app.config import settings
from app.schemas.extraction_models import (
    BatchExtractionResult,
    ContractExtraction,
    InvoiceExtraction,
    MedicalRecordExtraction,
    ReceiptExtraction,
    StructuredExtractionResponse,
)

if TYPE_CHECKING:
    from pydantic import BaseModel
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.classifier import Classifier
    from app.services.model_router import ModelRouter

logger = logging.getLogger(__name__)

# Map doc_type strings to the appropriate Pydantic extraction model class.
_SCHEMA_MAP: dict[str, type] = {
    "invoice": InvoiceExtraction,
    "contract": ContractExtraction,
    "receipt": ReceiptExtraction,
    "medical_record": MedicalRecordExtraction,
}

_SYSTEM_PROMPT = (
    "You are a document data extraction specialist. "
    "Extract all structured data from the document and return it as valid JSON. "
    "Be precise — extract exactly what is in the document, do not infer or hallucinate. "
    "If a field is not present, use null."
)


class StructuredExtractor:
    """Extracts typed data from documents using document-type-specific Pydantic schemas.

    Uses asyncio.gather with a semaphore for parallel batch processing.
    Validates extracted JSON against Pydantic models and retries once on parse failure.
    """

    def __init__(
        self,
        model_router: "ModelRouter",
        classifier: "Classifier | None" = None,
    ) -> None:
        self._router = model_router
        self._classifier = classifier
        self._semaphore = asyncio.Semaphore(5)

    async def extract(
        self,
        doc_id: str,
        doc_type: str | None = None,
        db: "AsyncSession | None" = None,
    ) -> StructuredExtractionResponse:
        """Extract structured data from a single document.

        Steps:
        1. Fetch document text from DB (via ExtractedRecord.raw_text)
        2. Classify doc type if not provided
        3. Call Claude with doc-type-specific schema prompt
        4. Parse JSON into Pydantic model
        5. If parse fails, retry once with corrected prompt
        """
        start = time.monotonic()
        retry_count = 0

        # --- 1. Fetch document text ---
        text, resolved_doc_type = await self._fetch_doc(doc_id, doc_type, db)
        if text is None:
            latency_ms = (time.monotonic() - start) * 1000
            return StructuredExtractionResponse(
                doc_id=doc_id,
                doc_type=resolved_doc_type or "unknown",
                extraction=None,
                error=f"Document not found: {doc_id}",
                latency_ms=latency_ms,
                model_used="",
            )

        # --- 2. Classify if needed ---
        if resolved_doc_type is None:
            if self._classifier is not None:
                result = await self._classifier.classify(text, db=db)
                resolved_doc_type = result.doc_type
            else:
                resolved_doc_type = "unknown"

        schema_cls = _SCHEMA_MAP.get(resolved_doc_type)
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)

        # --- 3. First extraction attempt ---
        prompt = self._build_extraction_prompt(resolved_doc_type, text)
        raw_json, model_used = await self._call_claude(client, prompt)

        # --- 4. Parse into Pydantic model ---
        extraction = None
        parse_error: str | None = None
        if schema_cls is not None:
            extraction, parse_error = _try_parse(schema_cls, raw_json)

        # --- 5. Retry once on validation failure ---
        if schema_cls is not None and extraction is None:
            retry_count = 1
            schema_json = json.dumps(schema_cls.model_json_schema(), indent=2)
            retry_prompt = (
                f"Your previous response had invalid JSON. "
                f"Return valid JSON matching schema:\n{schema_json}\n\n"
                f"Document text:\n{text[:8000]}"
            )
            raw_json2, model_used = await self._call_claude(client, retry_prompt)
            extraction, parse_error = _try_parse(schema_cls, raw_json2)

        latency_ms = (time.monotonic() - start) * 1000
        return StructuredExtractionResponse(
            doc_id=doc_id,
            doc_type=resolved_doc_type,
            extraction=extraction,
            error=parse_error if extraction is None else None,
            latency_ms=latency_ms,
            model_used=model_used,
            retry_count=retry_count,
        )

    async def extract_batch(
        self,
        doc_ids: list[str],
        db: "AsyncSession | None" = None,
    ) -> BatchExtractionResult:
        """Extract from multiple documents in parallel using asyncio.gather + semaphore."""
        start = time.monotonic()

        async def _guarded(doc_id: str) -> StructuredExtractionResponse:
            async with self._semaphore:
                return await self.extract(doc_id, db=db)

        results = await asyncio.gather(*[_guarded(doc_id) for doc_id in doc_ids])
        total_latency_ms = (time.monotonic() - start) * 1000

        successful = sum(1 for r in results if r.error is None)
        return BatchExtractionResult(
            results=list(results),
            total=len(results),
            successful=successful,
            failed=len(results) - successful,
            total_latency_ms=total_latency_ms,
        )

    def _build_extraction_prompt(self, doc_type: str, text: str) -> str:
        """Build a prompt asking Claude to extract fields and return field_confidence."""
        schema_cls = _SCHEMA_MAP.get(doc_type)
        if schema_cls is not None:
            schema_json = json.dumps(schema_cls.model_json_schema(), indent=2)
            schema_hint = f"\n\nReturn JSON matching this schema:\n{schema_json}"
        else:
            schema_hint = "\n\nReturn a JSON object with all fields you can extract."

        return (
            f"Extract all structured data from this {doc_type} document.\n"
            f"Include a 'field_confidence' dict rating each extracted field 0.0–1.0.{schema_hint}\n\n"
            f"Document text:\n{text[:8000]}"
        )

    async def _call_claude(
        self,
        client: AsyncAnthropic,
        prompt: str,
    ) -> tuple[str, str]:
        """Call Claude via the model router and return (raw_text, model_used)."""
        async def _call_fn(model: str) -> object:
            return await client.messages.create(
                model=model,
                max_tokens=4096,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

        response, model_used = await self._router.call_with_fallback(
            operation="structured_extract",
            chain=settings.extraction_models,
            call_fn=_call_fn,
        )
        raw_text: str = response.content[0].text
        return raw_text, model_used

    async def _fetch_doc(
        self,
        doc_id: str,
        doc_type: str | None,
        db: "AsyncSession | None",
    ) -> tuple[str | None, str | None]:
        """Fetch raw_text and doc_type from the extracted records table.

        Returns (text, doc_type) or (None, None) if not found.
        Falls back to doc_type argument if record doesn't override it.
        """
        if db is None:
            # No DB — callers in tests may inject text directly via subclassing,
            # but the default path just returns not-found.
            return None, doc_type

        from sqlalchemy import select
        from app.models.record import ExtractedRecord
        import uuid as _uuid

        try:
            doc_uuid = _uuid.UUID(doc_id)
        except ValueError:
            return None, doc_type

        stmt = (
            select(ExtractedRecord)
            .where(ExtractedRecord.document_id == doc_uuid)
            .limit(1)
        )
        result = await db.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            return None, doc_type

        text = record.raw_text or ""
        resolved_type = doc_type or record.document_type
        return text, resolved_type


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_json_from_text(text: str) -> dict:
    """Extract a JSON object from a Claude response string."""
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return {}


def _try_parse(
    schema_cls: type,
    raw_text: str,
) -> tuple[object | None, str | None]:
    """Parse raw Claude text into a Pydantic model instance.

    Returns (model_instance, None) on success or (None, error_message) on failure.
    """
    data = _parse_json_from_text(raw_text)
    if not data:
        return None, "Could not parse JSON from Claude response"
    try:
        return schema_cls.model_validate(data), None
    except ValidationError as exc:
        return None, f"Schema validation failed: {exc}"
