"""Output guardrails: PII detection and hallucination boundary checking.

Runs on every extraction when GUARDRAILS_ENABLED=true. Uses regex for
PII detection (zero API cost, deterministic) and string containment for
hallucination boundary checking (validates extracted values appear in source).

See ADR-010 for why regex was chosen over LLM-based safety filters.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ── PII patterns ──────────────────────────────────────────────────────────────

_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CC_RE = re.compile(
    r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|"
    r"6(?:011|5[0-9]{2})[0-9]{12}|(?:2131|1800|35\d{3})\d{11})\b"
    r"|(?:\d{4}[\s\-]){3}\d{4}"
)
_PHONE_RE = re.compile(
    r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b"
)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


@dataclass
class PiiMatch:
    pattern_type: str  # "ssn" | "credit_card" | "phone" | "email"
    field_path: str  # dot-notation key where it was found
    redacted: str  # value with digits replaced by *


@dataclass
class GroundingResult:
    field: str
    status: str  # "grounded" | "ungrounded" | "partial" | "skipped"
    reason: str


@dataclass
class GuardrailResult:
    pii_detected: list[PiiMatch] = field(default_factory=list)
    grounding: list[GroundingResult] = field(default_factory=list)
    passed: bool = True

    def __post_init__(self) -> None:
        self.passed = len(self.pii_detected) == 0


class PiiDetector:
    """Regex-based PII scanner for extraction output."""

    _PATTERNS: list[tuple[str, re.Pattern[str]]] = [
        ("ssn", _SSN_RE),
        ("credit_card", _CC_RE),
        ("phone", _PHONE_RE),
        ("email", _EMAIL_RE),
    ]

    def scan(self, data: dict[str, Any], prefix: str = "") -> list[PiiMatch]:
        """Recursively scan a dict for PII patterns."""
        matches: list[PiiMatch] = []
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                matches.extend(self.scan(value, prefix=path))
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        matches.extend(self.scan(item, prefix=f"{path}[{i}]"))
                    elif isinstance(item, str):
                        matches.extend(self._check_string(item, f"{path}[{i}]"))
            elif isinstance(value, str):
                matches.extend(self._check_string(value, path))
        return matches

    def _check_string(self, value: str, path: str) -> list[PiiMatch]:
        matches: list[PiiMatch] = []
        for pattern_type, pattern in self._PATTERNS:
            if pattern.search(value):
                redacted = re.sub(r"\d", "*", value)
                matches.append(PiiMatch(pattern_type=pattern_type, field_path=path, redacted=redacted))
                break  # one PII type per field is enough
        return matches


class HallucinationChecker:
    """Validates that extracted field values appear in the source document text."""

    _MIN_VALUE_LENGTH = 3  # ignore single characters / very short values
    _SUBSTRING_THRESHOLD = 0.6  # fraction of value words that must appear in source

    def check(
        self, extracted: dict[str, Any], source_text: str
    ) -> list[GroundingResult]:
        """Check grounding for all top-level string fields."""
        results: list[GroundingResult] = []
        source_lower = source_text.lower()

        for key, value in extracted.items():
            if not isinstance(value, str) or len(value) < self._MIN_VALUE_LENGTH:
                results.append(GroundingResult(field=key, status="skipped", reason="non-string or too short"))
                continue

            value_lower = value.lower()

            # Full substring match (best case)
            if value_lower in source_lower:
                results.append(GroundingResult(field=key, status="grounded", reason="exact substring found"))
                continue

            # Partial word overlap
            value_words = set(value_lower.split())
            source_words = set(source_lower.split())
            overlap = len(value_words & source_words)
            fraction = overlap / len(value_words) if value_words else 0.0

            if fraction >= self._SUBSTRING_THRESHOLD:
                results.append(GroundingResult(
                    field=key, status="partial",
                    reason=f"{overlap}/{len(value_words)} words found in source"
                ))
            else:
                results.append(GroundingResult(
                    field=key, status="ungrounded",
                    reason=f"only {overlap}/{len(value_words)} words found in source"
                ))

        return results


def run_guardrails(
    extracted_data: dict[str, Any],
    source_text: str = "",
    *,
    check_pii: bool = True,
    check_grounding: bool = True,
) -> GuardrailResult:
    """Run all enabled guardrail checks and return a combined result."""
    pii_matches: list[PiiMatch] = []
    grounding: list[GroundingResult] = []

    if check_pii:
        pii_matches = PiiDetector().scan(extracted_data)

    if check_grounding and source_text:
        grounding = HallucinationChecker().check(extracted_data, source_text)

    return GuardrailResult(pii_detected=pii_matches, grounding=grounding)
