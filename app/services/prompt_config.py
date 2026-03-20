"""Prompt configuration loader for the autoresearch optimization loop.

Loads prompts and tunable params from autoresearch/prompts.yaml.
Falls back to hardcoded defaults if the file is missing or unreadable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_YAML_PATH = Path(__file__).parent.parent.parent / "autoresearch" / "prompts.yaml"

# --- Defaults (verbatim from existing code) ---

_DEFAULT_EXTRACT_SYSTEM = """You are a document data extraction specialist.
Extract all structured data from the document according to the schema provided.
Be precise and extract exactly what's in the document — do not infer or hallucinate data.
For each field, extract the value exactly as it appears in the document.
If a field is not present, use null."""

_DEFAULT_EXTRACT_PROMPT = """Extract all data from this {doc_type} document into the provided JSON schema.

Document text:
{text}

Return a valid JSON object matching the schema. Include a "_confidence" field (0.0-1.0) indicating your overall confidence in the extraction."""

_DEFAULT_CORRECTION_PROMPT = """Review this {doc_type} extraction (confidence: {confidence:.2f}) and correct any errors.

Original document text (first {text_limit} chars):
{text}

Current extraction:
{extraction_json}

Use the apply_corrections tool to fix any incorrect or missing fields."""

_DEFAULT_CLASSIFY_PROMPT = """Analyze this document and classify it into one of these types:
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
class PromptParams:
    max_chunk_tokens: int = 4000
    overlap_chars: int = 200
    extract_text_limit: int = 8000
    correction_text_limit: int = 3000
    classify_text_limit: int = 2000
    extraction_confidence_threshold: float = 0.8
    classification_confidence_threshold: float = 0.6


@dataclass
class PromptConfig:
    extract_system_prompt: str = field(default_factory=lambda: _DEFAULT_EXTRACT_SYSTEM)
    extract_prompt: str = field(default_factory=lambda: _DEFAULT_EXTRACT_PROMPT)
    correction_prompt: str = field(default_factory=lambda: _DEFAULT_CORRECTION_PROMPT)
    classify_prompt: str = field(default_factory=lambda: _DEFAULT_CLASSIFY_PROMPT)
    params: PromptParams = field(default_factory=PromptParams)


def load_prompt_config(path: Optional[Path] = None) -> PromptConfig:
    """Load prompt config from YAML, falling back to hardcoded defaults."""
    yaml_path = path or _YAML_PATH
    if not yaml_path.exists():
        return PromptConfig()

    try:
        import yaml  # lazy import — only needed for autoresearch

        with open(yaml_path) as f:
            data = yaml.safe_load(f) or {}

        raw_params = data.get("params", {})
        params = PromptParams(
            max_chunk_tokens=raw_params.get("max_chunk_tokens", 4000),
            overlap_chars=raw_params.get("overlap_chars", 200),
            extract_text_limit=raw_params.get("extract_text_limit", 8000),
            correction_text_limit=raw_params.get("correction_text_limit", 3000),
            classify_text_limit=raw_params.get("classify_text_limit", 2000),
            extraction_confidence_threshold=raw_params.get(
                "extraction_confidence_threshold", 0.8
            ),
            classification_confidence_threshold=raw_params.get(
                "classification_confidence_threshold", 0.6
            ),
        )
        return PromptConfig(
            extract_system_prompt=data.get(
                "extract_system_prompt", _DEFAULT_EXTRACT_SYSTEM
            ),
            extract_prompt=data.get("extract_prompt", _DEFAULT_EXTRACT_PROMPT),
            correction_prompt=data.get(
                "correction_prompt", _DEFAULT_CORRECTION_PROMPT
            ),
            classify_prompt=data.get("classify_prompt", _DEFAULT_CLASSIFY_PROMPT),
            params=params,
        )
    except Exception:
        return PromptConfig()


# Module-level singleton — freshly loaded each process start
config = load_prompt_config()
