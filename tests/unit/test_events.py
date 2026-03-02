"""Tests for Redis pub/sub event publisher."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from worker.events import _channel_name, publish_event, subscribe_events


def test_channel_name():
    assert _channel_name("abc-123") == "job:abc-123:events"


@pytest.mark.asyncio
async def test_publish_event():
    mock_redis = AsyncMock()
    event_data = {"job_id": "j1", "status": "processing", "progress": 10}

    await publish_event(mock_redis, "j1", event_data)

    mock_redis.publish.assert_called_once_with(
        "job:j1:events", json.dumps(event_data)
    )


def _make_mock_redis(events):
    """Create a mock Redis with pubsub that yields given events."""
    mock_pubsub = MagicMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.close = AsyncMock()

    async def mock_listen():
        for e in events:
            yield e

    mock_pubsub.listen = mock_listen

    mock_redis = MagicMock()
    mock_redis.pubsub.return_value = mock_pubsub
    return mock_redis, mock_pubsub


@pytest.mark.asyncio
async def test_subscribe_events_yields_events():
    """Test that subscribe_events yields parsed events and stops on terminal status."""
    events = [
        {"type": "message", "data": json.dumps({"status": "processing", "progress": 10})},
        {"type": "message", "data": json.dumps({"status": "extracting", "progress": 50})},
        {"type": "message", "data": json.dumps({"status": "completed", "progress": 100})},
    ]
    mock_redis, mock_pubsub = _make_mock_redis(events)

    collected = []
    async for event in subscribe_events(mock_redis, "j1"):
        collected.append(event)

    assert len(collected) == 3
    assert collected[-1]["status"] == "completed"
    mock_pubsub.unsubscribe.assert_called_once_with("job:j1:events")
    mock_pubsub.close.assert_called_once()


@pytest.mark.asyncio
async def test_subscribe_events_stops_on_failed():
    """Test that subscribe stops after failed status."""
    events = [
        {"type": "message", "data": json.dumps({"status": "processing"})},
        {"type": "message", "data": json.dumps({"status": "failed", "error": "boom"})},
        {"type": "message", "data": json.dumps({"status": "should-not-reach"})},
    ]
    mock_redis, _ = _make_mock_redis(events)

    collected = []
    async for event in subscribe_events(mock_redis, "j1"):
        collected.append(event)

    assert len(collected) == 2
    assert collected[-1]["status"] == "failed"


@pytest.mark.asyncio
async def test_subscribe_events_skips_non_message_types():
    """Test that non-message types (subscribe confirmations) are ignored."""
    events = [
        {"type": "subscribe", "data": None},
        {"type": "message", "data": json.dumps({"status": "completed"})},
    ]
    mock_redis, _ = _make_mock_redis(events)

    collected = []
    async for event in subscribe_events(mock_redis, "j1"):
        collected.append(event)

    assert len(collected) == 1
    assert collected[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_subscribe_events_handles_bad_json():
    """Test that malformed JSON is skipped."""
    events = [
        {"type": "message", "data": "not-json{{{"},
        {"type": "message", "data": json.dumps({"status": "completed"})},
    ]
    mock_redis, _ = _make_mock_redis(events)

    collected = []
    async for event in subscribe_events(mock_redis, "j1"):
        collected.append(event)

    assert len(collected) == 1
    assert collected[0]["status"] == "completed"
