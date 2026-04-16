"""Unit tests for fine-tuning data export pipeline."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.finetune_exporter import FineTuneExporter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_correction(
    record_id: str = "rec-1",
    doc_type: str = "invoice",
    original_data: dict | None = None,
    corrected_data: dict | None = None,
    corrected_fields: list | None = None,
    created_at: datetime | None = None,
):
    """Build a mock Correction ORM object."""
    c = MagicMock()
    c.record_id = record_id
    c.doc_type = doc_type
    c.original_data = original_data if original_data is not None else {"total": "100.00", "vendor": "Acme"}
    c.corrected_data = corrected_data if corrected_data is not None else {"total": "150.00", "vendor": "Acme Corp"}
    c.corrected_fields = corrected_fields if corrected_fields is not None else ["total", "vendor"]
    c.created_at = created_at or datetime(2026, 3, 20, tzinfo=UTC)
    return c


def _mock_db_with_corrections(corrections):
    """Create a mock AsyncSession that returns given corrections from a query."""
    db = AsyncMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = corrections

    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock

    db.execute = AsyncMock(return_value=execute_result)
    return db


# ---------------------------------------------------------------------------
# Supervised JSONL format
# ---------------------------------------------------------------------------

class TestSupervisedFormat:
    @pytest.mark.asyncio
    async def test_supervised_jsonl_has_messages_array(self):
        corrections = [_make_correction()]
        db = _mock_db_with_corrections(corrections)
        exporter = FineTuneExporter(db)

        lines = []
        async for line in exporter.export_jsonl(format="supervised"):
            lines.append(json.loads(line))

        assert len(lines) == 1
        row = lines[0]
        assert "messages" in row
        assert len(row["messages"]) == 3
        assert row["messages"][0]["role"] == "system"
        assert row["messages"][1]["role"] == "user"
        assert row["messages"][2]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_supervised_assistant_content_is_corrected_data(self):
        corrected = {"total": "200.00", "vendor": "Fixed Inc"}
        corrections = [_make_correction(corrected_data=corrected)]
        db = _mock_db_with_corrections(corrections)
        exporter = FineTuneExporter(db)

        lines = []
        async for line in exporter.export_jsonl(format="supervised"):
            lines.append(json.loads(line))

        assistant_content = json.loads(lines[0]["messages"][2]["content"])
        assert assistant_content == corrected


# ---------------------------------------------------------------------------
# DPO format
# ---------------------------------------------------------------------------

class TestDPOFormat:
    @pytest.mark.asyncio
    async def test_dpo_has_chosen_and_rejected(self):
        corrections = [_make_correction()]
        db = _mock_db_with_corrections(corrections)
        exporter = FineTuneExporter(db)

        lines = []
        async for line in exporter.export_jsonl(format="dpo"):
            lines.append(json.loads(line))

        assert len(lines) == 1
        row = lines[0]
        assert "chosen" in row
        assert "rejected" in row
        assert "prompt" in row
        assert "doc_type" in row

    @pytest.mark.asyncio
    async def test_dpo_chosen_is_corrected_rejected_is_original(self):
        original = {"total": "100.00"}
        corrected = {"total": "150.00"}
        corrections = [_make_correction(
            original_data=original, corrected_data=corrected,
        )]
        db = _mock_db_with_corrections(corrections)
        exporter = FineTuneExporter(db)

        lines = []
        async for line in exporter.export_jsonl(format="dpo"):
            lines.append(json.loads(line))

        row = lines[0]
        assert json.loads(row["chosen"]) == corrected
        assert json.loads(row["rejected"]) == original


# ---------------------------------------------------------------------------
# Eval format
# ---------------------------------------------------------------------------

class TestEvalFormat:
    @pytest.mark.asyncio
    async def test_eval_includes_expected_output(self):
        corrections = [_make_correction()]
        db = _mock_db_with_corrections(corrections)
        exporter = FineTuneExporter(db)

        lines = []
        async for line in exporter.export_jsonl(format="eval"):
            lines.append(json.loads(line))

        row = lines[0]
        assert "input" in row
        assert "expected_output" in row
        assert "doc_type" in row
        assert "corrected_fields" in row


# ---------------------------------------------------------------------------
# Filtering and deduplication
# ---------------------------------------------------------------------------

class TestFiltering:
    @pytest.mark.asyncio
    async def test_empty_corrections_skipped(self):
        corrections = [_make_correction(corrected_fields=[])]
        db = _mock_db_with_corrections(corrections)
        exporter = FineTuneExporter(db)

        lines = []
        async for line in exporter.export_jsonl(format="supervised", min_field_count=1):
            lines.append(line)

        assert len(lines) == 0

    @pytest.mark.asyncio
    async def test_deduplication_keeps_latest_per_record(self):
        # Two corrections for same record_id -- only latest should be kept
        # Since ordered by desc(created_at), first row in list is latest
        c1 = _make_correction(
            record_id="rec-1",
            corrected_data={"total": "999.00"},
            created_at=datetime(2026, 3, 20, tzinfo=UTC),
        )
        c2 = _make_correction(
            record_id="rec-1",
            corrected_data={"total": "100.00"},
            created_at=datetime(2026, 3, 19, tzinfo=UTC),
        )
        corrections = [c1, c2]  # c1 is newer (ordered desc)
        db = _mock_db_with_corrections(corrections)
        exporter = FineTuneExporter(db)

        lines = []
        async for line in exporter.export_jsonl(format="dpo"):
            lines.append(json.loads(line))

        assert len(lines) == 1
        assert json.loads(lines[0]["chosen"]) == {"total": "999.00"}

    @pytest.mark.asyncio
    async def test_min_field_count_filter(self):
        c1 = _make_correction(corrected_fields=["total"])  # 1 field
        c2 = _make_correction(record_id="rec-2", corrected_fields=["total", "vendor", "date"])  # 3 fields
        corrections = [c1, c2]
        db = _mock_db_with_corrections(corrections)
        exporter = FineTuneExporter(db)

        lines = []
        async for line in exporter.export_jsonl(format="supervised", min_field_count=2):
            lines.append(line)

        assert len(lines) == 1


# ---------------------------------------------------------------------------
# Train/val split
# ---------------------------------------------------------------------------

class TestTrainValSplit:
    @pytest.mark.asyncio
    async def test_split_is_deterministic(self):
        corrections = [
            _make_correction(record_id=f"rec-{i}")
            for i in range(20)
        ]
        db = _mock_db_with_corrections(corrections)
        exporter = FineTuneExporter(db)

        # Run twice with same split
        train_lines_1 = []
        async for line in exporter.export_jsonl(format="supervised", split="train"):
            train_lines_1.append(line)

        db2 = _mock_db_with_corrections(corrections)
        exporter2 = FineTuneExporter(db2)
        train_lines_2 = []
        async for line in exporter2.export_jsonl(format="supervised", split="train"):
            train_lines_2.append(line)

        assert train_lines_1 == train_lines_2

    @pytest.mark.asyncio
    async def test_train_val_are_disjoint(self):
        corrections = [
            _make_correction(
                record_id=f"rec-{i}",
                original_data={"total": f"{i}.00"},
                corrected_data={"total": f"{i + 100}.00"},
            )
            for i in range(50)
        ]

        db_train = _mock_db_with_corrections(corrections)
        exporter_train = FineTuneExporter(db_train)
        train_lines = []
        async for line in exporter_train.export_jsonl(format="dpo", split="train"):
            train_lines.append(line)

        db_val = _mock_db_with_corrections(corrections)
        exporter_val = FineTuneExporter(db_val)
        val_lines = []
        async for line in exporter_val.export_jsonl(format="dpo", split="val"):
            val_lines.append(line)

        # Combined should equal total
        assert len(train_lines) + len(val_lines) == 50
        # No overlap (unique data per correction ensures unique strings)
        assert len(set(train_lines) & set(val_lines)) == 0

    @pytest.mark.asyncio
    async def test_split_all_returns_everything(self):
        corrections = [
            _make_correction(record_id=f"rec-{i}")
            for i in range(10)
        ]
        db = _mock_db_with_corrections(corrections)
        exporter = FineTuneExporter(db)

        lines = []
        async for line in exporter.export_jsonl(format="supervised", split="all"):
            lines.append(line)

        assert len(lines) == 10


# ---------------------------------------------------------------------------
# Multiple formats from same data
# ---------------------------------------------------------------------------

class TestMultiFormat:
    @pytest.mark.asyncio
    async def test_all_formats_produce_valid_json(self):
        corrections = [_make_correction()]

        for fmt in ("supervised", "dpo", "eval"):
            db = _mock_db_with_corrections(corrections)
            exporter = FineTuneExporter(db)
            async for line in exporter.export_jsonl(format=fmt):
                parsed = json.loads(line)
                assert isinstance(parsed, dict)
