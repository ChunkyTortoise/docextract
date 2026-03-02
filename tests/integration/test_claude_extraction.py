"""Integration tests for Claude extraction with mocked API."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_extract_invoice_two_pass():
    """Two-pass extraction runs correctly with high confidence (no Pass 2)."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = (
        '{"invoice_number": "INV-001", "total_amount": 100.0, "_confidence": 0.9}'
    )

    with patch("anthropic.Anthropic") as MockAnthropic:
        mock_client = MockAnthropic.return_value
        mock_client.messages.create.return_value = mock_response

        from app.services.claude_extractor import extract

        result = extract("Invoice INV-001 total $100", "invoice")

        assert result.data.get("invoice_number") == "INV-001"
        assert result.confidence == 0.9
        assert not result.corrections_applied


def test_extract_low_confidence_triggers_pass2():
    """Low confidence triggers correction pass."""
    pass1_response = MagicMock()
    pass1_response.content = [MagicMock()]
    pass1_response.content[0].text = (
        '{"invoice_number": "INV-001", "total_amount": 100.0, "_confidence": 0.5}'
    )

    # Pass 2 response with tool_use
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "apply_corrections"
    tool_block.input = {"corrections": {"total_amount": 150.0}}

    pass2_response = MagicMock()
    pass2_response.content = [tool_block]

    with patch("anthropic.Anthropic") as MockAnthropic:
        mock_client = MockAnthropic.return_value
        mock_client.messages.create.side_effect = [pass1_response, pass2_response]

        from app.services.claude_extractor import extract

        result = extract("Invoice INV-001 total $150", "invoice")

        assert result.corrections_applied
        assert result.data["total_amount"] == 150.0
        assert mock_client.messages.create.call_count == 2


def test_apply_corrections_merges():
    """apply_corrections correctly merges fields."""
    from app.services.claude_extractor import apply_corrections

    original = {"invoice_number": "INV-001", "total": 100.0, "vendor": None}
    corrections = {"vendor": "ACME Corp", "total": 105.0}
    result = apply_corrections(original, corrections)

    assert result["vendor"] == "ACME Corp"
    assert result["total"] == 105.0
    assert result["invoice_number"] == "INV-001"


def test_apply_corrections_empty():
    """Empty corrections returns original."""
    from app.services.claude_extractor import apply_corrections

    original = {"a": 1, "b": 2}
    result = apply_corrections(original, {})
    assert result == original


def test_parse_json_response_direct():
    """Direct JSON parsing works."""
    from app.services.claude_extractor import _parse_json_response

    result = _parse_json_response('{"key": "value"}')
    assert result == {"key": "value"}


def test_parse_json_response_code_block():
    """JSON inside code block is extracted."""
    from app.services.claude_extractor import _parse_json_response

    text = 'Here is the data:\n```json\n{"key": "value"}\n```\nDone.'
    result = _parse_json_response(text)
    assert result == {"key": "value"}
