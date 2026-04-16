"""Two-pass Claude document extraction service."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import anthropic
import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel

from app.config import settings
from app.schemas.document_types import DOCUMENT_TYPE_MAP
from app.services.prompt_config import config as prompt_config

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.model_router import ModelRouter

logger = structlog.get_logger(__name__)


@dataclass
class ExtractionResult:
    data: dict[str, Any]
    confidence: float
    corrections_applied: bool = False
    raw_response: str = ""
    schema_valid: bool = True
    validation_errors: list[str] = field(default_factory=list)
    model_used: str = ""


# Re-exported for backwards compatibility (tests may import these)
EXTRACT_SYSTEM_PROMPT = prompt_config.extract_system_prompt
EXTRACT_PROMPT = prompt_config.extract_prompt


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


async def extract(
    text: str,
    doc_type: str,
    schema_class: type[BaseModel] | None = None,
    db: AsyncSession | None = None,
) -> ExtractionResult:
    """Two-pass Claude extraction.

    Pass 1: Extract structured data using JSON output format
    Pass 2: Tool-use correction if confidence < threshold
    """
    from app.services.llm_tracer import trace_llm_call
    from app.services.response_validator import validate_extraction
    from app.services.validation_metrics import validation_stats

    if schema_class is None:
        schema_class = DOCUMENT_TYPE_MAP.get(doc_type)

    from app.services.model_router import ModelRouter

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    router = ModelRouter(
        failure_threshold=settings.circuit_breaker_failure_threshold,
        recovery_timeout=settings.circuit_breaker_recovery_seconds,
    )

    # Inject few-shot correction examples if active learning enabled
    few_shot_prefix = ""
    if settings.active_learning_enabled and db is not None:
        from app.services.correction_store import get_few_shot_examples
        examples = await get_few_shot_examples(db, doc_type, limit=2)
        if examples:
            examples_json = json.dumps(examples, indent=2)
            few_shot_prefix = (
                f"Previous corrections for {doc_type} documents:\n{examples_json}\n\n"
            )

    # Pass 1: Extract using model router with automatic fallback
    async def _extract_call(model: str) -> anthropic.types.Message:
        async with trace_llm_call(db, model, "extract") as trace_ctx:
            response = await client.messages.create(
                model=model,
                max_tokens=4096,
                system=prompt_config.extract_system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": few_shot_prefix + prompt_config.extract_prompt.format(
                            doc_type=doc_type,
                            text=text[: prompt_config.params.extract_text_limit],
                        ),
                    }
                ],
            )
            trace_ctx.record_response(response)
        return response

    response, model_used = await router.call_with_fallback(
        operation="extract",
        chain=settings.extraction_models,
        call_fn=_extract_call,
    )

    raw_text = response.content[0].text

    # Parse JSON from response
    extracted = _parse_json_response(raw_text)
    confidence = float(extracted.pop("_confidence", 0.5))

    # Validate against Pydantic schema
    outcome = validate_extraction(extracted, doc_type)
    validation_stats.record(outcome.schema_valid)
    if not outcome.schema_valid:
        logger.warning(
            "Schema validation failed for %s: %s",
            doc_type,
            outcome.validation_errors,
        )

    # Pass 2: Correction if low confidence
    corrections_applied = False
    threshold = settings.confidence_thresholds.get(
        doc_type, settings.extraction_confidence_threshold
    )
    if confidence < threshold:
        extracted, corrections_applied = await _apply_corrections_pass(
            client, text, doc_type, extracted, confidence, db=db,
            router=router,
        )

    return ExtractionResult(
        data=extracted,
        confidence=confidence,
        corrections_applied=corrections_applied,
        raw_response=raw_text,
        schema_valid=outcome.schema_valid,
        validation_errors=outcome.validation_errors,
        model_used=model_used,
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


async def _apply_corrections_pass(
    client: AsyncAnthropic,
    text: str,
    doc_type: str,
    original: dict[str, Any],
    confidence: float,
    db: AsyncSession | None = None,
    router: ModelRouter | None = None,
) -> tuple[dict[str, Any], bool]:
    """Pass 2: Use tool_use to correct low-confidence extractions."""
    from app.services.llm_tracer import trace_llm_call
    from app.services.model_router import ModelRouter

    if router is None:
        router = ModelRouter(
            failure_threshold=settings.circuit_breaker_failure_threshold,
            recovery_timeout=settings.circuit_breaker_recovery_seconds,
        )

    text_limit = prompt_config.params.correction_text_limit
    correction_prompt = prompt_config.correction_prompt.format(
        doc_type=doc_type,
        confidence=confidence,
        text_limit=text_limit,
        text=text[:text_limit],
        extraction_json=json.dumps(original, indent=2),
    )

    try:
        async def _correct_call(model: str) -> anthropic.types.Message:
            async with trace_llm_call(db, model, "correct") as trace_ctx:
                response = await client.messages.create(
                    model=model,
                    max_tokens=2048,
                    messages=[{"role": "user", "content": correction_prompt}],
                    tools=[CORRECTION_TOOL],
                )
                trace_ctx.record_response(response)
            return response

        response, _ = await router.call_with_fallback(
            operation="correct",
            chain=settings.extraction_models,
            call_fn=_correct_call,
        )

        # Find tool_use block
        for block in response.content:
            if block.type == "tool_use" and block.name == "apply_corrections":
                corrections = block.input.get("corrections", {})
                if corrections:
                    merged = apply_corrections(original, corrections)
                    return merged, True

        return original, False

    except Exception as e:
        logger.warning("Correction pass failed: %s", e)
        return original, False


def apply_corrections(original: dict[str, Any], corrections: dict[str, Any]) -> dict[str, Any]:
    """Merge corrections into original extraction data."""
    result = original.copy()
    result.update(corrections)
    return result
