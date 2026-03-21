"""Tests for active learning correction store."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestStoreCorrction:
    @pytest.mark.asyncio
    async def test_store_correction_computes_field_diff(self):
        from app.services.correction_store import store_correction
        from app.models.correction import Correction

        mock_db = AsyncMock()
        added_correction = None

        def capture_add(obj):
            nonlocal added_correction
            added_correction = obj

        mock_db.add = capture_add
        mock_db.flush = AsyncMock()

        await store_correction(
            db=mock_db,
            record_id="rec-123",
            doc_type="invoice",
            original_data={"invoice_number": "INV-001", "total": "100"},
            corrected_data={"invoice_number": "INV-002", "total": "100"},
            reviewer_id="reviewer-1",
        )

        assert added_correction is not None
        assert isinstance(added_correction, Correction)
        assert added_correction.record_id == "rec-123"
        assert added_correction.doc_type == "invoice"
        # Only invoice_number changed
        assert "invoice_number" in added_correction.corrected_fields
        assert "total" not in added_correction.corrected_fields

    @pytest.mark.asyncio
    async def test_store_correction_empty_diff(self):
        from app.services.correction_store import store_correction

        mock_db = AsyncMock()
        added = None

        def capture_add(obj):
            nonlocal added
            added = obj

        mock_db.add = capture_add
        mock_db.flush = AsyncMock()

        await store_correction(
            db=mock_db,
            record_id="rec-456",
            doc_type="receipt",
            original_data={"total": "50.00"},
            corrected_data={"total": "50.00"},
        )

        assert added.corrected_fields == []


class TestGetFewShotExamples:
    @pytest.mark.asyncio
    async def test_returns_formatted_examples(self):
        from app.services.correction_store import get_few_shot_examples
        from app.models.correction import Correction

        correction = Correction(
            id="c1",
            record_id="r1",
            doc_type="invoice",
            original_data={"invoice_number": "INV-001"},
            corrected_data={"invoice_number": "INV-002"},
            corrected_fields=["invoice_number"],
        )

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [correction]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        examples = await get_few_shot_examples(mock_db, "invoice", limit=2)

        assert len(examples) == 1
        assert examples[0]["original_extraction"] == {"invoice_number": "INV-001"}
        assert examples[0]["corrected_extraction"] == {"invoice_number": "INV-002"}
        assert examples[0]["corrected_fields"] == ["invoice_number"]

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_corrections(self):
        from app.services.correction_store import get_few_shot_examples

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        examples = await get_few_shot_examples(mock_db, "receipt")
        assert examples == []


class TestCorrectionModel:
    def test_correction_model_has_required_fields(self):
        from app.models.correction import Correction
        c = Correction(
            record_id="r1",
            doc_type="invoice",
            original_data={"a": 1},
            corrected_data={"a": 2},
        )
        assert c.record_id == "r1"
        assert c.doc_type == "invoice"
        assert c.original_data == {"a": 1}
        assert c.corrected_data == {"a": 2}


class TestFewShotInjection:
    @pytest.mark.asyncio
    async def test_few_shot_examples_injected_when_enabled(self):
        """When ACTIVE_LEARNING_ENABLED=true, correction examples prefix the prompt."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"total": "100", "_confidence": 0.90}')]

        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        mock_examples = [
            {
                "original_extraction": {"total": "99"},
                "corrected_extraction": {"total": "100"},
                "corrected_fields": ["total"],
            }
        ]

        from app.config import Settings
        settings_obj = Settings(
            database_url="postgresql+asyncpg://u:p@h/d",
            redis_url="redis://localhost",
            anthropic_api_key="sk-test",
            api_key_secret="test-secret-key-32-chars-long-ok!",
            active_learning_enabled=True,
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
            patch(
                "app.services.correction_store.get_few_shot_examples",
                AsyncMock(return_value=mock_examples),
            ),
        ):
            mock_validate.return_value = MagicMock(schema_valid=True, validation_errors=[])

            mock_db = AsyncMock()

            from app.services import claude_extractor
            await claude_extractor.extract("receipt text", "receipt", db=mock_db)

        # Verify prompt contained few-shot prefix
        call_args = mock_client.messages.create.call_args
        messages = call_args.kwargs["messages"]
        user_content = messages[0]["content"]
        assert "Previous corrections" in user_content
