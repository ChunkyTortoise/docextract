"""Document type classifier using Claude tool_use."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

import anthropic
from anthropic import AsyncAnthropic

from app.config import settings
from app.services.prompt_config import config as prompt_config

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DOCUMENT_TYPES = [
    "invoice",
    "purchase_order",
    "receipt",
    "bank_statement",
    "identity_document",
    "medical_record",
    "unknown",
]

CLASSIFY_TOOL = {
    "name": "classify_document",
    "description": "Classify a document into one of the supported types",
    "input_schema": {
        "type": "object",
        "properties": {
            "document_type": {
                "type": "string",
                "enum": DOCUMENT_TYPES,
                "description": "The type of document",
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Confidence score 0-1",
            },
            "reasoning": {
                "type": "string",
                "description": "Brief reasoning for the classification",
            },
        },
        "required": ["document_type", "confidence", "reasoning"],
    },
}

# Keep for backward compat
CLASSIFY_SCHEMA = CLASSIFY_TOOL["input_schema"]

CLASSIFY_PROMPT = """Analyze this document and classify it into one of these types:
- invoice: A bill from a vendor requesting payment
- purchase_order: A buyer's order requesting goods/services
- receipt: Proof of purchase/payment
- bank_statement: Bank account transaction history
- identity_document: Passport, driver's license, national ID
- medical_record: Patient health record, visit notes, prescriptions
- unknown: Cannot determine type

Document text (first 2000 chars):
{text}

Use the classify_document tool to return your classification."""


@dataclass
class ClassificationResult:
    doc_type: str
    confidence: float
    reasoning: str


async def classify(text: str, db: "AsyncSession | None" = None) -> ClassificationResult:
    """Classify document type using Claude tool_use.

    Returns ClassificationResult with doc_type='unknown' on low confidence or error.
    Falls back to legacy text parsing if tool_use block not found.
    """
    from app.services.llm_tracer import trace_llm_call

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    sample = text[: prompt_config.params.classify_text_limit]

    try:
        async with trace_llm_call(db, "claude-haiku-4-5-20251001", "classify") as trace_ctx:
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                messages=[
                    {"role": "user", "content": prompt_config.classify_prompt.format(text=sample)}
                ],
                tools=[CLASSIFY_TOOL],
                tool_choice={"type": "tool", "name": "classify_document"},
            )
            trace_ctx.record_response(response)

        # Find tool_use block
        result = None
        for block in response.content:
            if hasattr(block, "type") and block.type == "tool_use" and block.name == "classify_document":
                result = block.input
                break

        # Fallback to legacy text parsing if no tool_use block
        if result is None:
            result = _parse_legacy_response(response)

        if result is None:
            return ClassificationResult(doc_type="unknown", confidence=0.0, reasoning="No response")

        doc_type = result.get("document_type", "unknown")
        confidence = float(result.get("confidence", 0.0))
        reasoning = result.get("reasoning", "")

        if confidence < prompt_config.params.classification_confidence_threshold:
            doc_type = "unknown"

        return ClassificationResult(
            doc_type=doc_type,
            confidence=confidence,
            reasoning=reasoning,
        )

    except (anthropic.APIError, KeyError, IndexError) as e:
        logger.warning("Classification failed: %s", e)
        return ClassificationResult(doc_type="unknown", confidence=0.0, reasoning=str(e))


def _parse_legacy_response(response) -> dict | None:
    """Fallback: parse text JSON from response for backward compatibility."""
    import json
    try:
        for block in response.content:
            if hasattr(block, "text"):
                return json.loads(block.text)
    except (json.JSONDecodeError, AttributeError):
        pass
    return None
