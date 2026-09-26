"""Vision-native document extraction using Claude's image understanding."""
from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field

from app.config import settings
from app.services import injection_guard

logger = logging.getLogger(__name__)

IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# The image itself is untrusted (a document photo can embed attacker-chosen
# pixels and rendered text), and the doc_type hint is caller-supplied. The
# fenced document text plus a defense system clause give the vision model the
# same instruction hierarchy the text path gets (ADR-0020).
_DEFENSE_SYSTEM_CLAUSE = injection_guard.DEFENSE_SYSTEM_CLAUSE

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

    # Prompt-injection defense (ADR-0020): the defense system clause rides in
    # the system block (same as the text path), and the caller-supplied
    # doc_type hint is fenced as untrusted so a malicious hint cannot steer
    # the model. The image itself is untrusted data by nature; the model
    # reads it inside the same instruction hierarchy the text path uses.
    prompt = VISION_EXTRACT_PROMPT
    if doc_type:
        prompt += "\n\n" + injection_guard.wrap_untrusted(
            f"This document is a {doc_type}."
        )

    scan_hits = injection_guard.scan(prompt)

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=_DEFENSE_SYSTEM_CLAUSE,
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

    # Output sanitization: strip exfiltration keys regardless of whether scan
    # fired, so a successful injection still cannot leak secrets downstream.
    parsed = _sanitize_extracted(extracted_text, raw_text)
    all_scan_keys = parsed.get("exfil_keys", [])
    output_scan_hits = [k for k in all_scan_keys if k.startswith("output_scan:")]
    exfil_keys = [k for k in all_scan_keys if not k.startswith("output_scan:")]
    if exfil_keys:
        logger.warning(
            "Vision extraction stripped exfiltration keys: %s", exfil_keys
        )
    if output_scan_hits:
        logger.warning(
            "Vision extraction output scan hits: %s", output_scan_hits
        )

    logger.info(
        "Vision extraction complete: %d chars, mime=%s",
        len(parsed["text"]),
        mime_type,
    )

    return ExtractedContent(
        text=parsed["text"],
        metadata={
            "extraction_method": "vision",
            "mime_type": mime_type,
            "doc_type_hint": doc_type,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "_injection_defended": True,
            "injection_scan_hits": [*scan_hits, *output_scan_hits],
            **({"injection_exfil_keys_removed": exfil_keys} if exfil_keys else {}),
        },
        page_count=1,
        tables=parsed["tables"],
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


def _sanitize_extracted(extracted_text: str, raw_response: str) -> dict:
    """Sanitize the parsed extraction result through the injection guard.

    Runs the vision-extracted text through ``sanitize_output`` (strips
    exfiltration keys) and ``scan`` (observability on the model's own output,
    since a model that obeyed an injected instruction may announce it).
    """
    parsed: dict = {"text": extracted_text, "tables": []}

    # Try to recover the full structured object so sanitize_output can strip
    # forbidden keys from nested fields, not just the text blob.
    structured: dict = {}
    try:
        candidate = json.loads(raw_response.strip())
        if isinstance(candidate, dict):
            structured = candidate
    except json.JSONDecodeError:
        pass
    if not structured:
        match = re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```", raw_response, re.DOTALL
        )
        if match:
            try:
                candidate = json.loads(match.group(1))
                if isinstance(candidate, dict):
                    structured = candidate
            except json.JSONDecodeError:
                pass

    if structured:
        cleaned, removed = injection_guard.sanitize_output(structured)
        if cleaned.get("_raw_text"):
            parsed["text"] = str(cleaned["_raw_text"])
        else:
            # No _raw_text in the model's JSON: serialize the sanitized object.
            # Falling back to the raw response here would put stripped forbidden
            # keys back into the text while metadata claims they were removed.
            parsed["text"] = json.dumps(cleaned)
        parsed["exfil_keys"] = removed
        if isinstance(cleaned.get("tables"), list):
            parsed["tables"] = cleaned["tables"]

    # Scan the model output itself for injection markers (observability).
    output_hits = injection_guard.scan(extracted_text)
    if output_hits:
        parsed.setdefault("exfil_keys", []).extend(
            f"output_scan:{h}" for h in output_hits
        )

    parsed["exfil_keys"] = parsed.get("exfil_keys", [])
    return parsed
