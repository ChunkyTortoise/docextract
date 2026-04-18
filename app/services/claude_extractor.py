"""Two-pass Claude document extraction service."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import anthropic
import instructor
import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel

from app.config import settings
from app.schemas.citations import CitationGrounding, ExtractionCitation
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
    grounding: CitationGrounding | None = None
    reflection_applied: bool = False


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
    citations: bool = False,
    reflection: bool = False,
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

    # instructor.from_anthropic wraps the client transparently and adds
    # automatic retry on schema validation failure (Pydantic-backed).
    client = instructor.from_anthropic(AsyncAnthropic(api_key=settings.anthropic_api_key))
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

    # Pass 1: Extract using model router with automatic fallback.
    # When schema_class is available, instructor handles Pydantic validation
    # and retries (max_retries=3) automatically before raising InstructorRetryError.
    extract_kwargs: dict[str, Any] = {}
    if schema_class is not None:
        extract_kwargs["response_model"] = schema_class
        extract_kwargs["max_retries"] = 3

    async def _extract_call(model: str) -> Any:
        async with trace_llm_call(db, model, "extract") as trace_ctx:
            # Cached system prompt — stable across doc_type calls.
            # claude-3-5+ caches blocks ≥1024 tokens; schema injection by
            # instructor adds ~300-800 tokens, bringing it over the threshold
            # on subsequent calls to the same model.
            system_blocks: list[dict[str, Any]] = [
                {
                    "type": "text",
                    "text": prompt_config.extract_system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
            # User content: cached few-shot prefix (stable per doc_type session)
            # followed by uncached document text (unique per request).
            doc_prompt = prompt_config.extract_prompt.format(
                doc_type=doc_type,
                text=text[: prompt_config.params.extract_text_limit],
            )
            if few_shot_prefix:
                user_content: list[dict[str, Any]] = [
                    {
                        "type": "text",
                        "text": few_shot_prefix,
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": doc_prompt},
                ]
            else:
                user_content = [{"type": "text", "text": doc_prompt}]

            response = await client.messages.create(
                model=model,
                max_tokens=4096,
                system=system_blocks,
                messages=[{"role": "user", "content": user_content}],
                **extract_kwargs,
            )
            trace_ctx.record_response(response)
        return response

    try:
        response, model_used = await router.call_with_fallback(
            operation="extract",
            chain=settings.extraction_models,
            call_fn=_extract_call,
        )
    except Exception as e:
        if type(e).__name__ == "InstructorRetryError":
            logger.warning("instructor retry exhausted for %s: %s", doc_type, e)
            return ExtractionResult(
                data={},
                confidence=0.0,
                schema_valid=False,
                validation_errors=[f"Instructor retry exhausted after 3 attempts: {e}"],
            )
        raise

    # Instructor returns a Pydantic model directly when response_model is set;
    # the raw API returns anthropic.types.Message (has .content).
    # In tests, _bypass_instructor makes from_anthropic a no-op so response is
    # always a mock Message — isinstance(BaseModel) is False, raw path is taken.
    if isinstance(response, BaseModel):
        extracted = response.model_dump()
        confidence = float(extracted.pop("_confidence", 0.85))
        raw_text = json.dumps(extracted)
        schema_valid, validation_errors = True, []
        validation_stats.record(True)
    else:
        raw_text = response.content[0].text

        # Parse JSON from response
        extracted = _parse_json_response(raw_text)
        confidence = float(extracted.pop("_confidence", 0.5))

        # Validate against Pydantic schema
        outcome = validate_extraction(extracted, doc_type)
        validation_stats.record(outcome.schema_valid)
        schema_valid = outcome.schema_valid
        validation_errors = outcome.validation_errors
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

    reflection_applied = False
    if reflection and confidence < 0.8:
        extracted, reflection_applied = await _reflect_and_revise(
            text=text,
            doc_type=doc_type,
            extracted=extracted,
            confidence=confidence,
            model=model_used or settings.extraction_models[0],
            db=db,
        )

    grounding: CitationGrounding | None = None
    if citations:
        grounding = await _ground_with_citations(
            text=text,
            doc_type=doc_type,
            extracted=extracted,
            model=model_used or settings.extraction_models[0],
            db=db,
        )

    return ExtractionResult(
        data=extracted,
        confidence=confidence,
        corrections_applied=corrections_applied,
        raw_response=raw_text,
        schema_valid=schema_valid,
        validation_errors=validation_errors,
        model_used=model_used,
        grounding=grounding,
        reflection_applied=reflection_applied,
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


CITATION_GROUNDING_PROMPT = """You are grounding extracted fields to their source locations in the document.

For each field in the extraction below, find the exact text span in the document that supports the extracted value.
Use the citation feature to quote the relevant text for each field.

Fields to ground:
{field_list}

Extraction:
{extraction_json}

Quote the source span for each field value."""


async def _ground_with_citations(
    text: str,
    doc_type: str,
    extracted: dict[str, Any],
    model: str,
    db: "AsyncSession | None" = None,
) -> CitationGrounding:
    """Run a citation-grounding pass using Anthropic's native Citations API.

    Passes the document as a "document" content block so the model can
    cite character offsets within the source text for each extracted field.
    """
    from app.services.llm_tracer import trace_llm_call

    # Only ground the top-level string/number fields (skip nested/complex)
    groundable = {k: v for k, v in extracted.items() if isinstance(v, (str, int, float)) and v}
    if not groundable:
        return CitationGrounding(citations=[], grounded_fields=[], ungrounded_fields=list(extracted.keys()))

    field_list = "\n".join(f"- {k}: {v}" for k, v in groundable.items())
    prompt_text = CITATION_GROUNDING_PROMPT.format(
        field_list=field_list,
        extraction_json=json.dumps(groundable, indent=2),
    )

    raw_client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    try:
        async with trace_llm_call(db, model, "citations_grounding") as trace_ctx:
            response = await raw_client.messages.create(
                model=model,
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {
                                    "type": "text",
                                    "media_type": "text/plain",
                                    "data": text[: 8000],  # same limit as extraction pass
                                },
                                "title": f"{doc_type} document",
                                "citations": {"enabled": True},
                            },
                            {"type": "text", "text": prompt_text},
                        ],
                    }
                ],
            )
            trace_ctx.record_response(response)
    except Exception as e:
        logger.warning("Citation grounding failed: %s", e)
        return CitationGrounding(
            citations=[],
            grounded_fields=[],
            ungrounded_fields=list(extracted.keys()),
        )

    # Parse citation blocks from response content
    parsed: list[ExtractionCitation] = []
    grounded_fields: set[str] = set()

    for block in response.content:
        if block.type != "text":
            continue
        block_citations = getattr(block, "citations", []) or []
        for cit in block_citations:
            if cit.type == "char_location":
                # Best-effort: match field by looking for its value in cited_text
                matched_field = _match_citation_to_field(cit.cited_text, groundable)
                if matched_field:
                    grounded_fields.add(matched_field)
                    parsed.append(
                        ExtractionCitation(
                            field_name=matched_field,
                            cited_text=cit.cited_text,
                            start_char_index=cit.start_char_index,
                            end_char_index=cit.end_char_index,
                            document_index=getattr(cit, "document_index", 0),
                        )
                    )

    ungrounded = [k for k in groundable if k not in grounded_fields]
    logger.info(
        "Citation grounding: %d/%d fields grounded for %s",
        len(grounded_fields),
        len(groundable),
        doc_type,
    )
    return CitationGrounding(
        citations=parsed,
        grounded_fields=list(grounded_fields),
        ungrounded_fields=ungrounded,
    )


def _match_citation_to_field(cited_text: str, fields: dict[str, Any]) -> str | None:
    """Return the field name whose value appears in the cited text."""
    cited_lower = cited_text.lower()
    for field_name, value in fields.items():
        if str(value).lower() in cited_lower or cited_lower in str(value).lower():
            return field_name
    return None


REFLECTION_PROMPT = """You previously extracted data from a {doc_type} document with low confidence ({confidence:.0%}).
Review your extraction and the source document, identify errors or missing fields, and provide a corrected extraction.

Source document:
{text}

Your previous extraction:
{extraction_json}

Issues to consider: low confidence score suggests uncertain or missing field values.
Provide a complete, corrected JSON extraction with a revised "_confidence" score."""


async def _reflect_and_revise(
    text: str,
    doc_type: str,
    extracted: dict[str, Any],
    confidence: float,
    model: str,
    db: "AsyncSession | None" = None,
) -> tuple[dict[str, Any], bool]:
    """Reflection pass: show the model its own low-confidence extraction and ask it to revise.

    Only called when confidence < 0.8 and reflection=True is requested.
    Returns (revised_extraction, reflection_applied).
    """
    from app.services.llm_tracer import trace_llm_call

    reflection_prompt = REFLECTION_PROMPT.format(
        doc_type=doc_type,
        confidence=confidence,
        text=text[:4000],
        extraction_json=json.dumps(extracted, indent=2),
    )

    raw_client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    try:
        async with trace_llm_call(db, model, "reflect") as trace_ctx:
            response = await raw_client.messages.create(
                model=model,
                max_tokens=2048,
                system=[
                    {
                        "type": "text",
                        "text": prompt_config.extract_system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": reflection_prompt}],
            )
            trace_ctx.record_response(response)

        revised_text = response.content[0].text
        revised = _parse_json_response(revised_text)
        if revised:
            new_confidence = float(revised.pop("_confidence", confidence))
            logger.info(
                "Reflection pass: confidence %.2f → %.2f for %s",
                confidence,
                new_confidence,
                doc_type,
            )
            return revised, True

    except Exception as e:
        logger.warning("Reflection pass failed: %s", e)

    return extracted, False
