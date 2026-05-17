from __future__ import annotations

from app.services.pii_sanitizer import sanitize_for_trace, sanitize_string


def test_sanitize_string_redacts_supported_pii_patterns() -> None:
    text = (
        "SSN 123-45-6789, card 4111-1111-1111-1111, "
        "phone (555) 867-5309, email user@example.com"
    )

    sanitized = sanitize_string(text)

    assert "123-45-6789" not in sanitized
    assert "4111-1111-1111-1111" not in sanitized
    assert "(555) 867-5309" not in sanitized
    assert "user@example.com" not in sanitized
    assert "[SSN]" in sanitized
    assert "[CC]" in sanitized
    assert "[PHONE]" in sanitized
    assert "[EMAIL]" in sanitized


def test_sanitize_for_trace_recurses_through_dicts_and_lists() -> None:
    payload = {
        "customer": {
            "email": "buyer@example.com",
            "contacts": ["clean", "555-867-5309"],
        },
        "notes": [{"ssn": "123-45-6789"}],
    }

    sanitized = sanitize_for_trace(payload)

    assert sanitized["customer"]["email"] == "[EMAIL]"
    assert sanitized["customer"]["contacts"] == ["clean", "[PHONE]"]
    assert sanitized["notes"][0]["ssn"] == "[SSN]"


def test_sanitize_for_trace_leaves_non_string_values_unchanged() -> None:
    payload = {"count": 3, "ok": True, "amount": 12.5}

    assert sanitize_for_trace(payload) == payload


def test_sanitize_for_trace_handles_none() -> None:
    assert sanitize_for_trace(None) is None
