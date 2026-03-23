"""Unit tests for the feedback collection endpoint and data models."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import ValidationError

_MOCK_API_KEY = MagicMock()  # stand-in for an authenticated APIKey instance

from app.api.feedback import (
    FeedbackRequest,
    FeedbackResponse,
    FeedbackSummary,
    submit_feedback,
    get_feedback_summary,
    router,
)


# ---------------------------------------------------------------------------
# FeedbackRequest validation
# ---------------------------------------------------------------------------


class TestFeedbackRequestValidation:
    def test_valid_positive_rating(self):
        req = FeedbackRequest(record_id="rec-123", rating="positive")
        assert req.record_id == "rec-123"
        assert req.rating == "positive"

    def test_valid_negative_rating(self):
        req = FeedbackRequest(record_id="rec-456", rating="negative")
        assert req.rating == "negative"

    def test_invalid_rating_rejected(self):
        with pytest.raises(ValidationError):
            FeedbackRequest(record_id="rec-123", rating="neutral")

    def test_empty_record_id_rejected(self):
        with pytest.raises(ValidationError):
            FeedbackRequest(record_id="", rating="positive")

    def test_missing_record_id_rejected(self):
        with pytest.raises(ValidationError):
            FeedbackRequest(rating="positive")

    def test_missing_rating_rejected(self):
        with pytest.raises(ValidationError):
            FeedbackRequest(record_id="rec-123")

    def test_optional_comment_defaults_none(self):
        req = FeedbackRequest(record_id="rec-123", rating="positive")
        assert req.comment is None

    def test_optional_doc_type_defaults_none(self):
        req = FeedbackRequest(record_id="rec-123", rating="positive")
        assert req.doc_type is None

    def test_comment_accepted(self):
        req = FeedbackRequest(record_id="rec-123", rating="negative", comment="Wrong total")
        assert req.comment == "Wrong total"

    def test_doc_type_accepted(self):
        req = FeedbackRequest(record_id="rec-123", rating="positive", doc_type="invoice")
        assert req.doc_type == "invoice"

    def test_all_fields_populated(self):
        req = FeedbackRequest(
            record_id="rec-999",
            rating="negative",
            comment="Bad date format",
            doc_type="receipt",
        )
        assert req.record_id == "rec-999"
        assert req.rating == "negative"
        assert req.comment == "Bad date format"
        assert req.doc_type == "receipt"


# ---------------------------------------------------------------------------
# FeedbackSummary calculation
# ---------------------------------------------------------------------------


class TestFeedbackSummaryCalculation:
    def test_empty_results_zero_totals(self):
        summary = FeedbackSummary(
            total=0,
            positive=0,
            negative=0,
            positive_rate=0.0,
            by_doc_type={},
        )
        assert summary.total == 0
        assert summary.positive_rate == 0.0
        assert summary.by_doc_type == {}

    def test_all_positive(self):
        summary = FeedbackSummary(
            total=5,
            positive=5,
            negative=0,
            positive_rate=1.0,
            by_doc_type={},
        )
        assert summary.positive_rate == 1.0

    def test_all_negative(self):
        summary = FeedbackSummary(
            total=3,
            positive=0,
            negative=3,
            positive_rate=0.0,
            by_doc_type={},
        )
        assert summary.positive_rate == 0.0

    def test_mixed_positive_rate(self):
        summary = FeedbackSummary(
            total=4,
            positive=1,
            negative=3,
            positive_rate=0.25,
            by_doc_type={},
        )
        assert summary.positive_rate == 0.25

    def test_by_doc_type_grouping(self):
        summary = FeedbackSummary(
            total=4,
            positive=2,
            negative=2,
            positive_rate=0.5,
            by_doc_type={
                "invoice": {"positive": 2, "negative": 1},
                "receipt": {"positive": 0, "negative": 1},
            },
        )
        assert summary.by_doc_type["invoice"]["positive"] == 2
        assert summary.by_doc_type["receipt"]["negative"] == 1


# ---------------------------------------------------------------------------
# submit_feedback endpoint
# ---------------------------------------------------------------------------


class TestSubmitFeedbackEndpoint:
    @pytest.mark.asyncio
    async def test_insert_executed_with_correct_params(self):
        db = AsyncMock()
        request = FeedbackRequest(
            record_id="rec-abc",
            rating="positive",
            comment="Looks good",
            doc_type="invoice",
        )

        result = await submit_feedback(request, db, api_key=_MOCK_API_KEY)

        db.execute.assert_awaited_once()
        call_kwargs = db.execute.call_args
        params = call_kwargs[0][1]
        assert params["record_id"] == "rec-abc"
        assert params["rating"] == "positive"
        assert params["comment"] == "Looks good"
        assert params["doc_type"] == "invoice"

    @pytest.mark.asyncio
    async def test_commit_called_after_insert(self):
        db = AsyncMock()
        request = FeedbackRequest(record_id="rec-xyz", rating="negative")

        await submit_feedback(request, db, api_key=_MOCK_API_KEY)

        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_response_format(self):
        db = AsyncMock()
        request = FeedbackRequest(record_id="rec-123", rating="positive")

        result = await submit_feedback(request, db, api_key=_MOCK_API_KEY)

        assert isinstance(result, FeedbackResponse)
        assert result.status == "recorded"
        assert result.record_id == "rec-123"
        assert result.rating == "positive"

    @pytest.mark.asyncio
    async def test_null_comment_and_doc_type_passed(self):
        db = AsyncMock()
        request = FeedbackRequest(record_id="rec-000", rating="negative")

        await submit_feedback(request, db, api_key=_MOCK_API_KEY)

        params = db.execute.call_args[0][1]
        assert params["comment"] is None
        assert params["doc_type"] is None


# ---------------------------------------------------------------------------
# get_feedback_summary endpoint
# ---------------------------------------------------------------------------


class TestGetFeedbackSummaryEndpoint:
    def _make_row(self, rating: str, doc_type: str | None, cnt: int) -> MagicMock:
        row = MagicMock()
        row.rating = rating
        row.doc_type = doc_type
        row.cnt = cnt
        return row

    @pytest.mark.asyncio
    async def test_empty_db_returns_zero_summary(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        db.execute.return_value = mock_result

        result = await get_feedback_summary(db, api_key=_MOCK_API_KEY)

        assert result.total == 0
        assert result.positive == 0
        assert result.negative == 0
        assert result.positive_rate == 0.0
        assert result.by_doc_type == {}

    @pytest.mark.asyncio
    async def test_all_positive_rows(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            self._make_row("positive", "invoice", 3),
        ]
        db.execute.return_value = mock_result

        result = await get_feedback_summary(db, api_key=_MOCK_API_KEY)

        assert result.total == 3
        assert result.positive == 3
        assert result.negative == 0
        assert result.positive_rate == 1.0

    @pytest.mark.asyncio
    async def test_mixed_ratings_aggregation(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            self._make_row("positive", "invoice", 6),
            self._make_row("negative", "invoice", 2),
            self._make_row("negative", "receipt", 2),
        ]
        db.execute.return_value = mock_result

        result = await get_feedback_summary(db, api_key=_MOCK_API_KEY)

        assert result.total == 10
        assert result.positive == 6
        assert result.negative == 4
        assert result.positive_rate == 0.6

    @pytest.mark.asyncio
    async def test_by_doc_type_populated(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            self._make_row("positive", "invoice", 4),
            self._make_row("negative", "invoice", 1),
            self._make_row("positive", "receipt", 2),
        ]
        db.execute.return_value = mock_result

        result = await get_feedback_summary(db, api_key=_MOCK_API_KEY)

        assert result.by_doc_type["invoice"]["positive"] == 4
        assert result.by_doc_type["invoice"]["negative"] == 1
        assert result.by_doc_type["receipt"]["positive"] == 2

    @pytest.mark.asyncio
    async def test_null_doc_type_excluded_from_by_doc_type(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            self._make_row("positive", None, 5),
        ]
        db.execute.return_value = mock_result

        result = await get_feedback_summary(db, api_key=_MOCK_API_KEY)

        assert result.total == 5
        assert result.by_doc_type == {}

    @pytest.mark.asyncio
    async def test_positive_rate_rounded_to_4_places(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            self._make_row("positive", None, 1),
            self._make_row("negative", None, 2),
        ]
        db.execute.return_value = mock_result

        result = await get_feedback_summary(db, api_key=_MOCK_API_KEY)

        # 1/3 = 0.3333...
        assert result.positive_rate == round(1 / 3, 4)


# ---------------------------------------------------------------------------
# Router registration
# ---------------------------------------------------------------------------


class TestRouterRegistration:
    def test_feedback_router_has_no_prefix(self):
        # prefix is empty — parent api_router provides /api/v1
        assert router.prefix == ""

    def test_feedback_router_has_feedback_tag(self):
        assert "feedback" in router.tags

    def test_submit_feedback_route_exists(self):
        routes = {r.path for r in router.routes}
        assert "/feedback" in routes

    def test_get_summary_route_exists(self):
        routes = {r.path for r in router.routes}
        assert "/feedback/summary" in routes

    def test_feedback_module_importable(self):
        from app.api import feedback  # noqa: F401

        assert hasattr(feedback, "router")
