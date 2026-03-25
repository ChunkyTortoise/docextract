"""PII sanitization for observability traces.

Strips sensitive data (SSN, credit card, phone, email) before sending
to external tracing services (Langfuse, LangSmith). Reuses the same
regex patterns as app.services.guardrails.PiiDetector.

Usage:
    from app.services.pii_sanitizer import sanitize_for_trace
    clean_data = sanitize_for_trace(raw_data)
"""
from __future__ import annotations

import re
from typing import Any

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

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("[SSN]", _SSN_RE),
    ("[CC]", _CC_RE),
    ("[PHONE]", _PHONE_RE),
    ("[EMAIL]", _EMAIL_RE),
]


def sanitize_string(text: str) -> str:
    """Replace PII patterns in a string with redaction tokens."""
    for token, pattern in _PATTERNS:
        text = pattern.sub(token, text)
    return text


def sanitize_for_trace(data: Any) -> Any:
    """Recursively sanitize PII from data before sending to trace services.

    Handles str, dict, list, and passes through other types unchanged.
    """
    if data is None:
        return None
    if isinstance(data, str):
        return sanitize_string(data)
    if isinstance(data, dict):
        return {k: sanitize_for_trace(v) for k, v in data.items()}
    if isinstance(data, list):
        return [sanitize_for_trace(item) for item in data]
    return data
