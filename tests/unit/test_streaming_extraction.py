"""Tests for streaming page-by-page extraction events."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestJobStatusEnum:
    def test_extracting_page_in_enum(self):
        from app.schemas.events import JobStatus
        assert hasattr(JobStatus, "EXTRACTING_PAGE")
        assert JobStatus.EXTRACTING_PAGE.value == "extracting_page"

    def test_extracting_page_in_progress_map(self):
        from app.schemas.events import JOB_STATUS_PROGRESS, JobStatus
        assert JobStatus.EXTRACTING_PAGE in JOB_STATUS_PROGRESS
        assert JOB_STATUS_PROGRESS[JobStatus.EXTRACTING_PAGE] == 40


class TestEmitPageEvents:
    @pytest.mark.asyncio
    async def test_emits_one_event_per_page(self):
        from app.schemas.events import JobStatus
        mock_redis = AsyncMock()
        published = []

        async def capture_publish(redis, job_id, event_data):
            published.append(event_data)

        with patch("worker.events.publish_event", side_effect=capture_publish):
            from worker.tasks import _emit_page_events
            # 3-page text with markers
            text = "page one content\n---PAGE 2---\npage two content\n---PAGE 3---\npage three content"
            await _emit_page_events(mock_redis, "job-123", text, total_pages=3)

        assert len(published) == 3

    @pytest.mark.asyncio
    async def test_events_have_correct_status(self):
        mock_redis = AsyncMock()
        published = []

        async def capture_publish(redis, job_id, event_data):
            published.append(event_data)

        with patch("worker.events.publish_event", side_effect=capture_publish):
            from worker.tasks import _emit_page_events
            text = "page 1\n---PAGE 2---\npage 2"
            await _emit_page_events(mock_redis, "job-456", text, total_pages=2)

        for event in published:
            assert event["status"] == "extracting_page"
            assert event["job_id"] == "job-456"

    @pytest.mark.asyncio
    async def test_events_contain_page_details(self):
        mock_redis = AsyncMock()
        published = []

        async def capture_publish(redis, job_id, event_data):
            published.append(event_data)

        with patch("worker.events.publish_event", side_effect=capture_publish):
            from worker.tasks import _emit_page_events
            text = "first\n---PAGE 2---\nsecond\n---PAGE 3---\nthird"
            await _emit_page_events(mock_redis, "j1", text, total_pages=3)

        assert published[0]["details"]["page"] == 1
        assert published[0]["details"]["total_pages"] == 3
        assert published[1]["details"]["page"] == 2
        assert published[2]["details"]["page"] == 3

    @pytest.mark.asyncio
    async def test_single_page_text_emits_one_event(self):
        mock_redis = AsyncMock()
        published = []

        async def capture_publish(redis, job_id, event_data):
            published.append(event_data)

        with patch("worker.events.publish_event", side_effect=capture_publish):
            from worker.tasks import _emit_page_events
            # No page markers — treated as single page
            text = "only page content here"
            await _emit_page_events(mock_redis, "j1", text, total_pages=1)

        assert len(published) == 1

    @pytest.mark.asyncio
    async def test_progress_is_40_for_all_events(self):
        mock_redis = AsyncMock()
        published = []

        async def capture_publish(redis, job_id, event_data):
            published.append(event_data)

        with patch("worker.events.publish_event", side_effect=capture_publish):
            from worker.tasks import _emit_page_events
            text = "p1\n---PAGE 2---\np2"
            await _emit_page_events(mock_redis, "j1", text, total_pages=2)

        for event in published:
            assert event["progress"] == 40
