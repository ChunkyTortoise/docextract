"""Tests for Claude extractor service."""
import json
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import anthropic
import pytest

from app.services.claude_extractor import (
    ExtractionResult,
    _parse_json_response,
    apply_corrections,
    extract,
)


@pytest.fixture(autouse=True)
def _bypass_instructor(monkeypatch):
    """Patch instructor.from_anthropic to be an identity function.

    All tests in this module mock AsyncAnthropic() and expect the returned
    mock to be used directly as the client.  instructor.from_anthropic would
    normally wrap that mock in its own object, breaking the mock setup.
    This fixture makes from_anthropic a no-op so mock clients pass through.
    """
    import instructor as _instructor
    monkeypatch.setattr(_instructor, "from_anthropic", lambda client, **kw: client)


def _make_text_block(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _make_tool_use_block(name: str, input_data: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = input_data
    return block


def _make_response(content_blocks: list) -> MagicMock:
    response = MagicMock()
    response.content = content_blocks
    return response


class TestExtractPass1:
    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_successful_extraction(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client

        extracted_json = {
            "invoice_number": "INV-001",
            "total_amount": 500.0,
            "_confidence": 0.95,
        }
        client.messages.create = AsyncMock(return_value=_make_response(
            [_make_text_block(json.dumps(extracted_json))]
        ))

        result = await extract("Invoice #INV-001\nTotal: $500", "invoice")

        assert isinstance(result, ExtractionResult)
        assert result.data["invoice_number"] == "INV-001"
        assert result.confidence == 0.95
        assert not result.corrections_applied
        assert "_confidence" not in result.data

    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_uses_content_0_text(self, mock_cls):
        """Verify response.content[0].text is used (not response.content.text)."""
        client = MagicMock()
        mock_cls.return_value = client

        text_block = _make_text_block(json.dumps({"_confidence": 0.9}))
        # Use a MagicMock for content so .text raises AttributeError
        response = MagicMock()
        response.content = MagicMock()
        response.content.__getitem__ = MagicMock(return_value=text_block)
        # Make response.content.text raise AttributeError
        type(response.content).text = PropertyMock(side_effect=AttributeError("use content[0].text"))
        client.messages.create = AsyncMock(return_value=response)

        result = await extract("test", "invoice")
        assert result.confidence == 0.9

    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_default_confidence_when_missing(self, mock_cls):
        client = MagicMock()
        mock_cls.return_value = client
        client.messages.create = AsyncMock(return_value=_make_response(
            [_make_text_block(json.dumps({"invoice_number": "X"}))]
        ))

        result = await extract("test", "invoice")
        assert result.confidence == 0.5


class TestExtractPass2Corrections:
    @patch("app.services.claude_extractor.settings")
    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_corrections_applied_on_low_confidence(self, mock_cls, mock_settings):
        mock_settings.anthropic_api_key = "test-key"
        mock_settings.extraction_confidence_threshold = 0.8
        mock_settings.confidence_thresholds = {}
        mock_settings.active_learning_enabled = False
        mock_settings.extraction_models = ["claude-sonnet-4-6"]
        mock_settings.circuit_breaker_failure_threshold = 5
        mock_settings.circuit_breaker_recovery_seconds = 60.0

        client = MagicMock()
        mock_cls.return_value = client

        # Pass 1: low confidence extraction
        pass1_data = {"invoice_number": "INV-001", "_confidence": 0.6}
        pass1_response = _make_response([_make_text_block(json.dumps(pass1_data))])

        # Pass 2: correction via tool_use
        correction_block = _make_tool_use_block(
            "apply_corrections",
            {"corrections": {"invoice_number": "INV-001-A"}, "reasoning": "Fixed typo"},
        )
        pass2_response = _make_response([correction_block])

        client.messages.create = AsyncMock(side_effect=[pass1_response, pass2_response])

        result = await extract("test doc", "invoice")
        assert result.corrections_applied is True
        assert result.data["invoice_number"] == "INV-001-A"

    @patch("app.services.claude_extractor.settings")
    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_no_corrections_when_high_confidence(self, mock_cls, mock_settings):
        mock_settings.anthropic_api_key = "test-key"
        mock_settings.extraction_confidence_threshold = 0.8
        mock_settings.confidence_thresholds = {}
        mock_settings.active_learning_enabled = False
        mock_settings.extraction_models = ["claude-sonnet-4-6"]
        mock_settings.circuit_breaker_failure_threshold = 5
        mock_settings.circuit_breaker_recovery_seconds = 60.0

        client = MagicMock()
        mock_cls.return_value = client

        pass1_data = {"invoice_number": "INV-001", "_confidence": 0.95}
        client.messages.create = AsyncMock(return_value=_make_response(
            [_make_text_block(json.dumps(pass1_data))]
        ))

        result = await extract("test doc", "invoice")
        assert result.corrections_applied is False
        # Only one API call (no correction pass)
        assert client.messages.create.call_count == 1


class TestApplyCorrections:
    def test_merge_corrections(self):
        original = {"a": 1, "b": 2, "c": 3}
        corrections = {"b": 20, "d": 4}
        result = apply_corrections(original, corrections)
        assert result == {"a": 1, "b": 20, "c": 3, "d": 4}

    def test_empty_corrections(self):
        original = {"a": 1}
        result = apply_corrections(original, {})
        assert result == {"a": 1}

    def test_does_not_mutate_original(self):
        original = {"a": 1}
        apply_corrections(original, {"a": 2})
        assert original == {"a": 1}


class TestParseJsonResponse:
    def test_direct_json(self):
        result = _parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_in_code_block(self):
        text = 'Some text\n```json\n{"key": "value"}\n```\nMore text'
        result = _parse_json_response(text)
        assert result == {"key": "value"}

    def test_json_in_generic_code_block(self):
        text = 'Text\n```\n{"key": "value"}\n```'
        result = _parse_json_response(text)
        assert result == {"key": "value"}

    def test_embedded_json_object(self):
        text = 'Here is the result: {"key": "value"} end.'
        result = _parse_json_response(text)
        assert result == {"key": "value"}

    def test_unparseable_returns_empty(self):
        result = _parse_json_response("no json here at all")
        assert result == {}


class TestExtractionResultSchemaValid:
    """Tests for schema_valid field on ExtractionResult."""

    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_schema_valid_field_exists(self, mock_anthropic_cls):
        """ExtractionResult should have schema_valid field."""
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"invoice_number": "INV-001", "_confidence": 0.9}')]
        client.messages.create = AsyncMock(return_value=mock_response)

        result = await extract("Invoice text", "invoice")
        assert hasattr(result, "schema_valid")

    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_schema_valid_true_for_valid_extraction(self, mock_anthropic_cls):
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"invoice_number": "INV-001", "_confidence": 0.9, "total_amount": 100.0}')]
        client.messages.create = AsyncMock(return_value=mock_response)

        result = await extract("Invoice text", "invoice")
        assert result.schema_valid is True

    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_validation_errors_field_exists(self, mock_anthropic_cls):
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"_confidence": 0.9}')]
        client.messages.create = AsyncMock(return_value=mock_response)

        result = await extract("text", "invoice")
        assert hasattr(result, "validation_errors")
        assert isinstance(result.validation_errors, list)

    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_extract_with_db_none(self, mock_anthropic_cls):
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"_confidence": 0.9}')]
        client.messages.create = AsyncMock(return_value=mock_response)

        result = await extract("text", "invoice", db=None)
        assert isinstance(result, ExtractionResult)

    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_extract_records_trace_in_memory(self, mock_anthropic_cls):
        from app.services.llm_tracer import clear_in_memory_traces, get_in_memory_traces
        clear_in_memory_traces()
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"_confidence": 0.9}')]
        client.messages.create = AsyncMock(return_value=mock_response)

        await extract("text", "invoice", db=None)
        traces = get_in_memory_traces()
        assert any(t["operation"] == "extract" for t in traces)
        clear_in_memory_traces()


class TestExtractErrorHandling:
    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_rate_limit_falls_back_to_secondary_model(self, mock_cls):
        """Rate limit on primary model triggers fallback to secondary."""
        client = MagicMock()
        mock_cls.return_value = client

        rate_limit_error = anthropic.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        success_response = _make_response(
            [_make_text_block(json.dumps({"_confidence": 0.9}))]
        )
        # Primary fails, secondary succeeds
        client.messages.create = AsyncMock(side_effect=[rate_limit_error, success_response])

        result = await extract("test", "invoice")
        assert result.confidence == 0.9
        assert client.messages.create.call_count == 2

    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_rate_limit_raises_when_all_models_fail(self, mock_cls):
        """AllModelsUnavailableError raised when every model in chain fails."""
        from app.services.model_router import AllModelsUnavailableError

        client = MagicMock()
        mock_cls.return_value = client

        rate_limit_error = anthropic.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        client.messages.create = AsyncMock(side_effect=rate_limit_error)

        with pytest.raises(AllModelsUnavailableError):
            await extract("test", "invoice")

    @patch("app.services.claude_extractor.AsyncAnthropic")
    @pytest.mark.asyncio
    async def test_4xx_error_re_raises(self, mock_cls):
        """Client errors (4xx) are not transient — they propagate immediately."""
        client = MagicMock()
        mock_cls.return_value = client

        error = anthropic.BadRequestError(
            message="bad request",
            response=MagicMock(status_code=400, headers={}),
            body=None,
        )
        client.messages.create = AsyncMock(side_effect=error)

        with pytest.raises(anthropic.BadRequestError):
            await extract("test", "invoice")


class TestInstructorIntegration:
    """Tests for instructor typed extraction behaviour.

    These tests patch the ``instructor`` module directly (rather than relying
    on the autouse _bypass_instructor fixture) so they can control whether
    instructor is active and what it returns.
    """

    @patch("app.services.claude_extractor.settings")
    @patch("app.services.claude_extractor.AsyncAnthropic")
    @patch("app.services.claude_extractor.instructor")
    @pytest.mark.asyncio
    async def test_response_model_kwarg_passed_when_schema_class_known(
        self, mock_instructor, mock_cls, mock_settings
    ):
        """When a known doc_type has a schema, response_model is passed to create()."""
        mock_settings.anthropic_api_key = "test-key"
        mock_settings.extraction_confidence_threshold = 0.8
        mock_settings.confidence_thresholds = {}
        mock_settings.active_learning_enabled = False
        mock_settings.extraction_models = ["claude-sonnet-4-6"]
        mock_settings.circuit_breaker_failure_threshold = 5
        mock_settings.circuit_breaker_recovery_seconds = 60.0

        raw_client = MagicMock()
        mock_cls.return_value = raw_client

        # instructor.from_anthropic returns the same mock (transparent wrap)
        mock_instructor.from_anthropic.return_value = raw_client

        extracted_json = {"invoice_number": "INV-001", "_confidence": 0.95}
        raw_client.messages.create = AsyncMock(return_value=_make_response(
            [_make_text_block(json.dumps(extracted_json))]
        ))

        await extract("Invoice test", "invoice")

        call_kwargs = raw_client.messages.create.call_args.kwargs
        assert "response_model" in call_kwargs
        assert call_kwargs["max_retries"] == 3

    @patch("app.services.claude_extractor.settings")
    @patch("app.services.claude_extractor.AsyncAnthropic")
    @patch("app.services.claude_extractor.instructor")
    @pytest.mark.asyncio
    async def test_instructor_retry_exhausted_returns_schema_invalid(
        self, mock_instructor, mock_cls, mock_settings
    ):
        """When instructor raises InstructorRetryError, schema_valid=False is returned."""
        mock_settings.anthropic_api_key = "test-key"
        mock_settings.extraction_confidence_threshold = 0.8
        mock_settings.confidence_thresholds = {}
        mock_settings.active_learning_enabled = False
        mock_settings.extraction_models = ["claude-sonnet-4-6"]
        mock_settings.circuit_breaker_failure_threshold = 5
        mock_settings.circuit_breaker_recovery_seconds = 60.0

        raw_client = MagicMock()
        mock_cls.return_value = raw_client
        mock_instructor.from_anthropic.return_value = raw_client

        # Simulate instructor retry exhaustion
        class InstructorRetryError(Exception):
            pass

        mock_instructor.exceptions.InstructorRetryError = InstructorRetryError
        raw_client.messages.create = AsyncMock(side_effect=InstructorRetryError("3 retries"))

        result = await extract("bad doc", "invoice")

        assert result.schema_valid is False
        assert result.confidence == 0.0
        assert "retry exhausted" in result.validation_errors[0].lower()


class TestCitationsGrounding:
    """Tests for _ground_with_citations and citations=True path."""

    def _make_char_citation(self, cited_text: str, start: int, end: int) -> MagicMock:
        cit = MagicMock()
        cit.type = "char_location"
        cit.cited_text = cited_text
        cit.start_char_index = start
        cit.end_char_index = end
        cit.document_index = 0
        return cit

    def _make_text_block_with_citations(self, text: str, citations: list) -> MagicMock:
        block = MagicMock()
        block.type = "text"
        block.text = text
        block.citations = citations
        return block

    @pytest.mark.asyncio
    async def test_extract_with_citations_calls_grounding(self):
        """extract(citations=True) calls the grounding pass and attaches it."""
        from app.schemas.citations import CitationGrounding

        extraction_json = json.dumps({"vendor_name": "Acme Corp", "_confidence": 0.9})
        text_block = _make_text_block(extraction_json)
        mock_response = _make_response([text_block])
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        # Grounding response mock
        cited_block = self._make_text_block_with_citations(
            "Acme Corp",
            [self._make_char_citation("Acme Corp", 10, 19)],
        )
        grounding_response = MagicMock()
        grounding_response.content = [cited_block]
        grounding_response.usage = MagicMock(
            input_tokens=200,
            output_tokens=30,
            cache_creation_input_tokens=None,
            cache_read_input_tokens=None,
        )

        with patch("app.services.claude_extractor.AsyncAnthropic") as MockAnthropicCls:
            # Two clients: one from instructor bypass (extract pass), one raw (grounding)
            raw_client = AsyncMock()
            raw_client.messages.create = AsyncMock(side_effect=[mock_response, grounding_response])
            MockAnthropicCls.return_value = raw_client

            result = await extract(
                text="Acme Corp invoice total $500",
                doc_type="invoice",
                citations=True,
            )

        assert result.grounding is not None
        assert isinstance(result.grounding, CitationGrounding)

    @pytest.mark.asyncio
    async def test_citations_disabled_by_default(self):
        """extract() without citations=True returns grounding=None."""
        extraction_json = json.dumps({"vendor_name": "Test", "_confidence": 0.9})
        mock_response = _make_response([_make_text_block(extraction_json)])
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        with patch("app.services.claude_extractor.AsyncAnthropic") as MockAnthropicCls:
            client = AsyncMock()
            client.messages.create = AsyncMock(return_value=mock_response)
            MockAnthropicCls.return_value = client

            result = await extract(
                text="Test invoice",
                doc_type="invoice",
            )

        assert result.grounding is None

    def test_match_citation_to_field_exact(self):
        from app.services.claude_extractor import _match_citation_to_field

        fields = {"vendor_name": "Acme Corp", "total_amount": "500.00"}
        assert _match_citation_to_field("Acme Corp", fields) == "vendor_name"
        assert _match_citation_to_field("500.00", fields) == "total_amount"

    def test_match_citation_no_match(self):
        from app.services.claude_extractor import _match_citation_to_field

        fields = {"vendor_name": "Acme Corp"}
        assert _match_citation_to_field("completely unrelated text", fields) is None
