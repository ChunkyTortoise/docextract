"""Vision-native document extraction using Claude's image understanding."""
from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field

from app.config import settings

logger = logging.getLogger(__name__)

IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

VISION_EXTRACT_PROMPT = """You are a document extraction specialist. Analyze this document image and extract all structured data.

Return a JSON object with these fields:
- All visible text, numbers, dates, and data fields from the document
- A "_confidence" field (0.0-1.0) indicating your overall confidence in the extraction
- A "_raw_text" field with the full text you can read from the image

Be precise — extract exactly what you see. Use null for any fields not visible."""


@dataclass
class ExtractedContent:
    """Vision extraction result."""

    text: str
    metadata: dict = field(default_factory=dict)
    page_count: int = 1
    tables: list[dict] = field(default_factory=list)


async def extract_vision(
    image_bytes: bytes,
    mime_type: str,
    doc_type: str | None = None,
) -> ExtractedContent:
    """Extract document data by sending image directly to Claude vision API.

    Bypasses OCR entirely — Claude reads the image natively.
    Supports: image/jpeg, image/png, image/gif, image/webp

    Args:
        image_bytes: Raw image bytes
        mime_type: MIME type (must be an image type)
        doc_type: Optional document type hint for context

    Returns:
        ExtractedContent with extracted text and metadata

    Raises:
        ValueError: If mime_type is not a supported image type
    """
    if mime_type not in IMAGE_MIME_TYPES:
        raise ValueError(
            f"Vision extraction requires an image MIME type, got: {mime_type}"
        )

    from anthropic import AsyncAnthropic

    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

    prompt = VISION_EXTRACT_PROMPT
    if doc_type:
        prompt += f"\n\nThis document is a {doc_type}."

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }
        ],
    )

    raw_text = response.content[0].text
    extracted_text = _parse_raw_text(raw_text)

    logger.info(
        "Vision extraction complete: %d chars, mime=%s",
        len(extracted_text),
        mime_type,
    )

    return ExtractedContent(
        text=extracted_text,
        metadata={
            "extraction_method": "vision",
            "mime_type": mime_type,
            "doc_type_hint": doc_type,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
        page_count=1,
    )


def _parse_raw_text(response_text: str) -> str:
    """Extract the _raw_text field from JSON response, or fall back to full response."""
    # Try to parse JSON and get _raw_text
    try:
        data = json.loads(response_text.strip())
        return str(data.get("_raw_text") or response_text)
    except (json.JSONDecodeError, AttributeError):
        pass

    # Try markdown code block
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            return str(data.get("_raw_text") or response_text)
        except (json.JSONDecodeError, AttributeError):
            pass

    return response_text
