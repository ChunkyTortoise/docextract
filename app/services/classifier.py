"""Document type classifier using Claude."""
from dataclasses import dataclass
import json
import logging

import anthropic
from anthropic import AsyncAnthropic

from app.config import settings

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

CLASSIFY_SCHEMA = {
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
}

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

Respond with JSON matching the schema."""


@dataclass
class ClassificationResult:
    doc_type: str
    confidence: float
    reasoning: str


async def classify(text: str) -> ClassificationResult:
    """Classify document type using Claude.

    Returns ClassificationResult with doc_type='unknown' on low confidence or error.
    """
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Use first 2000 chars for classification (fast + cheap)
    sample = text[:2000]

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": CLASSIFY_PROMPT.format(text=sample)}],
        )

        raw = response.content[0].text
        result = json.loads(raw)

        doc_type = result.get("document_type", "unknown")
        confidence = float(result.get("confidence", 0.0))
        reasoning = result.get("reasoning", "")

        # Fall back to unknown on low confidence
        if confidence < 0.6:
            doc_type = "unknown"

        return ClassificationResult(
            doc_type=doc_type,
            confidence=confidence,
            reasoning=reasoning,
        )

    except (anthropic.APIError, json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning("Classification failed: %s", e)
        return ClassificationResult(doc_type="unknown", confidence=0.0, reasoning=str(e))
