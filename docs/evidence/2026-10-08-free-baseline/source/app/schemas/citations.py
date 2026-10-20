"""Citation models for grounded document extraction."""
from __future__ import annotations

from pydantic import BaseModel


class ExtractionCitation(BaseModel):
    """A character-level citation linking an extracted field to its source span."""

    field_name: str
    cited_text: str
    start_char_index: int
    end_char_index: int
    document_index: int = 0


class CitationGrounding(BaseModel):
    """Full citation grounding result for an extraction."""

    citations: list[ExtractionCitation]
    grounded_fields: list[str]
    ungrounded_fields: list[str]
