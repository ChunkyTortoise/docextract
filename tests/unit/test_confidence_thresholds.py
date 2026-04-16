"""Tests for per-document-type confidence thresholds."""
from __future__ import annotations

import pytest


class TestConfidenceThresholds:
    def test_settings_has_per_type_thresholds(self):
        from app.config import settings
        assert hasattr(settings, "confidence_thresholds")
        assert isinstance(settings.confidence_thresholds, dict)

    def test_identity_document_threshold_higher(self):
        from app.config import settings
        assert settings.confidence_thresholds["identity_document"] > settings.confidence_thresholds["receipt"]

    def test_receipt_threshold_lower_than_default(self):
        from app.config import settings
        assert settings.confidence_thresholds["receipt"] < settings.extraction_confidence_threshold

    def test_all_required_doc_types_present(self):
        from app.config import settings
        required = {"invoice", "purchase_order", "receipt", "bank_statement",
                    "identity_document", "medical_record", "unknown"}
        assert required.issubset(set(settings.confidence_thresholds.keys()))

    def test_threshold_lookup_falls_back_to_global(self):
        """Unknown doc types fall back to extraction_confidence_threshold."""
        from app.config import Settings
        s = Settings(
            database_url="postgresql+asyncpg://u:p@h/d",
            redis_url="redis://localhost",
            api_key_secret="test-secret-key-32-chars-long-ok!",
            confidence_thresholds={"invoice": 0.80},
        )
        # 'receipt' not in thresholds — should use global default
        threshold = s.confidence_thresholds.get("receipt", s.extraction_confidence_threshold)
        assert threshold == s.extraction_confidence_threshold

    @pytest.mark.asyncio
    async def test_low_confidence_identity_triggers_correction(self):
        """Confidence 0.88 should trigger Pass 2 for identity_document (threshold 0.90)
        but NOT for receipt (threshold 0.75)."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.config import Settings

        # Identity doc at 0.88 — below 0.90 threshold
        settings_obj = Settings(
            database_url="postgresql+asyncpg://u:p@h/d",
            redis_url="redis://localhost",
            anthropic_api_key="sk-test",
            api_key_secret="test-secret-key-32-chars-long-ok!",
        )

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"name": "John", "_confidence": 0.88}')]

        mock_correction_response = MagicMock()
        mock_correction_response.content = []

        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(
            side_effect=[mock_response, mock_correction_response]
        )

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_ctx.record_response = MagicMock()

        with (
            patch("app.services.claude_extractor.AsyncAnthropic", return_value=mock_client),
            patch("app.services.claude_extractor.settings", settings_obj),
            patch("app.services.llm_tracer.trace_llm_call", return_value=mock_ctx),
            patch("app.services.response_validator.validate_extraction") as mock_validate,
            patch("app.services.validation_metrics.validation_stats"),
        ):
            mock_validate.return_value = MagicMock(schema_valid=True, validation_errors=[])

            from app.services import claude_extractor
            result = await claude_extractor.extract(  # noqa: F841
                "John Smith DOB 1990-01-01", "identity_document", db=None
            )
            # corrections_applied may or may not be True depending on correction pass response
            # but the key assertion is that Pass 2 was called (2 API calls)
            assert mock_client.messages.create.call_count == 2

    @pytest.mark.asyncio
    async def test_high_confidence_receipt_skips_correction(self):
        """Confidence 0.78 should NOT trigger Pass 2 for receipt (threshold 0.75)."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.config import Settings

        settings_obj = Settings(
            database_url="postgresql+asyncpg://u:p@h/d",
            redis_url="redis://localhost",
            anthropic_api_key="sk-test",
            api_key_secret="test-secret-key-32-chars-long-ok!",
        )

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"total": 12.50, "_confidence": 0.78}')]

        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        mock_ctx2 = AsyncMock()
        mock_ctx2.__aenter__ = AsyncMock(return_value=mock_ctx2)
        mock_ctx2.__aexit__ = AsyncMock(return_value=None)
        mock_ctx2.record_response = MagicMock()

        with (
            patch("app.services.claude_extractor.AsyncAnthropic", return_value=mock_client),
            patch("app.services.claude_extractor.settings", settings_obj),
            patch("app.services.llm_tracer.trace_llm_call", return_value=mock_ctx2),
            patch("app.services.response_validator.validate_extraction") as mock_validate,
            patch("app.services.validation_metrics.validation_stats"),
        ):
            mock_validate.return_value = MagicMock(schema_valid=True, validation_errors=[])

            from app.services import claude_extractor
            result = await claude_extractor.extract(
                "Receipt total $12.50", "receipt", db=None
            )
            # Only 1 API call — no correction pass
            assert mock_client.messages.create.call_count == 1
            assert result.corrections_applied is False
