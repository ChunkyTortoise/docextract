"""Redis pub/sub event publisher for SSE streaming."""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


def _channel_name(job_id: str) -> str:
    return f"job:{job_id}:events"


async def publish_event(redis: aioredis.Redis, job_id: str, event_data: dict) -> None:
    """Publish a job event to Redis pub/sub channel."""
    channel = _channel_name(job_id)
    payload = json.dumps(event_data)
    await redis.publish(channel, payload)
    logger.debug("Published event to %s: %s", channel, payload[:100])


async def subscribe_events(
    redis: aioredis.Redis, job_id: str
) -> AsyncGenerator[dict, None]:
    """Subscribe to job events and yield parsed event dicts.

    Yields events until COMPLETED or FAILED status received.
    """
    channel = _channel_name(job_id)
    terminal_statuses = {"completed", "failed", "cancelled"}

    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    event = json.loads(message["data"])
                    yield event
                    # Stop after terminal status
                    if event.get("status", "").lower() in terminal_statuses:
                        break
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("Bad event payload: %s", e)
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
