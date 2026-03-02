"""Two-pass Claude document extraction service."""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Type

import anthropic
from pydantic import BaseModel

from app.config import settings
from app.schemas.document_types import DOCUMENT_TYPE_MAP

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    data: dict[str, Any]
    confidence: float
    corrections_applied: bool = False
    raw_response: str = ""


EXTRACT_SYSTEM_PROMPT = """You are a document data extraction specialist.
Extract all structured data from the document according to the schema provided.
Be precise and extract exactly what's in the document — do not infer or hallucinate data.
For each field, extract the value exactly as it appears in the document.
If a field is not present, use null."""

EXTRACT_PROMPT = """Extract all data from this {doc_type} document into the provided JSON schema.

Document text:
{text}

Return a valid JSON object matching the schema. Include a "_confidence" field (0.0-1.0) indicating your overall confidence in the extraction."""


CORRECTION_TOOL = {
    "name": "apply_corrections",
    "description": "Apply corrections to extracted fields that need fixing",
    "input_schema": {
        "type": "object",
        "properties": {
            "corrections": {
                "type": "object",
                "description": "Dictionary of field_name -> corrected_value pairs",
                "additionalProperties": True,
            },
            "reasoning": {
                "type": "string",
                "description": "Brief explanation of what was corrected and why",
            },
        },
        "required": ["corrections"],
    },
}


def extract(
    text: str,
    doc_type: str,
    schema_class: Type[BaseModel] | None = None,
) -> ExtractionResult:
    """Two-pass Claude extraction.

    Pass 1: Extract structured data using JSON output format
    Pass 2: Tool-use correction if confidence < threshold
    """
    if schema_class is None:
        schema_class = DOCUMENT_TYPE_MAP.get(doc_type)

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    # Pass 1: Extract (with rate limit retry)
    for attempt in range(3):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                system=EXTRACT_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": EXTRACT_PROMPT.format(doc_type=doc_type, text=text[:8000]),
                    }
                ],
            )

            raw_text = response.content[0].text

            # Parse JSON from response
            extracted = _parse_json_response(raw_text)
            confidence = float(extracted.pop("_confidence", 0.5))

            # Pass 2: Correction if low confidence
            corrections_applied = False
            if confidence < settings.extraction_confidence_threshold:
                extracted, corrections_applied = _apply_corrections_pass(
                    client, text, doc_type, extracted, confidence
                )

            return ExtractionResult(
                data=extracted,
                confidence=confidence,
                corrections_applied=corrections_applied,
                raw_response=raw_text,
            )

        except anthropic.RateLimitError:
            if attempt == 2:
                raise
            wait_time = 60 * (2 ** attempt)
            logger.warning(
                "Rate limit hit, retrying in %ds (attempt %d/3)",
                wait_time, attempt + 1,
            )
            time.sleep(wait_time)

        except anthropic.APIStatusError as e:
            if e.status_code >= 400 and e.status_code < 500:
                raise
            raise

    # Unreachable, but satisfies type checker
    raise anthropic.RateLimitError(  # pragma: no cover
        message="Rate limit exceeded after 3 attempts",
        response=None,  # type: ignore[arg-type]
        body=None,
    )


def _parse_json_response(text: str) -> dict[str, Any]:
    """Extract JSON from Claude response text."""
    # Try direct parse first
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Try to find JSON block in response
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find any JSON object
    obj_match = re.search(r"\{.*\}", text, re.DOTALL)
    if obj_match:
        try:
            return json.loads(obj_match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning("Could not parse JSON from response: %s...", text[:100])
    return {}


def _apply_corrections_pass(
    client: anthropic.Anthropic,
    text: str,
    doc_type: str,
    original: dict[str, Any],
    confidence: float,
) -> tuple[dict[str, Any], bool]:
    """Pass 2: Use tool_use to correct low-confidence extractions."""
    correction_prompt = f"""Review this {doc_type} extraction (confidence: {confidence:.2f}) and correct any errors.

Original document text (first 3000 chars):
{text[:3000]}

Current extraction:
{json.dumps(original, indent=2)}

Use the apply_corrections tool to fix any incorrect or missing fields."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": correction_prompt}],
            tools=[CORRECTION_TOOL],
        )

        # Find tool_use block
        for block in response.content:
            if block.type == "tool_use" and block.name == "apply_corrections":
                corrections = block.input.get("corrections", {})
                if corrections:
                    merged = apply_corrections(original, corrections)
                    return merged, True

        return original, False

    except anthropic.APIError as e:
        logger.warning("Correction pass failed: %s", e)
        return original, False


def apply_corrections(original: dict[str, Any], corrections: dict[str, Any]) -> dict[str, Any]:
    """Merge corrections into original extraction data."""
    result = original.copy()
    result.update(corrections)
    return result
