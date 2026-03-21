"""Pydantic validation for LLM extraction responses."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ValidationOutcome:
    validated_data: dict[str, Any]
    schema_valid: bool
    validation_errors: list[str] = field(default_factory=list)
    used_fallback: bool = False


def validate_extraction(extracted: dict[str, Any], doc_type: str) -> ValidationOutcome:
    """Validate and coerce extraction data against the Pydantic schema.

    On success: returns Pydantic-coerced data.
    On failure: returns raw data with used_fallback=True.
    """
    from app.schemas.document_types import DOCUMENT_TYPE_MAP

    schema_class = DOCUMENT_TYPE_MAP.get(doc_type)
    if schema_class is None:
        # Unknown doc type — pass through without validation
        return ValidationOutcome(
            validated_data=extracted,
            schema_valid=True,
        )

    try:
        validated = schema_class.model_validate(extracted)
        return ValidationOutcome(
            validated_data=validated.model_dump(exclude_none=False),
            schema_valid=True,
        )
    except Exception as e:
        errors = _extract_pydantic_errors(e)
        logger.warning("Schema validation failed for %s: %s", doc_type, errors)
        return ValidationOutcome(
            validated_data=extracted,
            schema_valid=False,
            validation_errors=errors,
            used_fallback=True,
        )


def _extract_pydantic_errors(e: Exception) -> list[str]:
    """Extract error messages from a Pydantic ValidationError."""
    try:
        return [str(err["msg"]) for err in e.errors()]
    except (AttributeError, KeyError, TypeError):
        return [str(e)]
