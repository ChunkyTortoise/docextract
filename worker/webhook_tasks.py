"""ARQ task: webhook delivery retries scheduled as deferred jobs."""
from __future__ import annotations

from typing import Any

from app.config import settings
from app.services.webhook_sender import (
    MAX_ATTEMPTS,
    RETRY_DELAYS,
    _push_to_dlq,
    attempt_webhook,
    decrypt_secret,
)


async def deliver_webhook(
    ctx: dict[str, Any],
    url: str,
    payload: dict,
    secret_encrypted: str,
    webhook_id: str | None = None,
    attempt: int = 1,
) -> dict[str, Any]:
    """Run one delivery attempt, then schedule the next attempt deferred.

    Every attempt is its own ARQ job, so retries outlive the 300s
    process_document timeout and an exhausted chain still reaches the DLQ.
    """
    # The secret is AES-GCM ciphertext on the queue; decrypt only here, at the
    # attempt that signs with it. A value that cannot decrypt is permanent.
    try:
        secret = (
            decrypt_secret(secret_encrypted, settings.aes_key)
            if secret_encrypted
            else ""
        )
    except Exception:
        await _push_to_dlq(
            ctx["redis"], url, payload, "secret decryption failed", webhook_id
        )
        return {"status": "dead_lettered", "attempt": attempt}

    ok, error = await attempt_webhook(url, payload, secret, attempt=attempt)
    if ok:
        return {"status": "delivered", "attempt": attempt}

    if attempt < MAX_ATTEMPTS:
        delay = RETRY_DELAYS[attempt]
        await ctx["redis"].enqueue_job(
            "deliver_webhook",
            url,
            payload,
            secret_encrypted,
            webhook_id,
            attempt + 1,
            _defer_by=delay,
            _queue_name=settings.worker_queue,
        )
        return {"status": "retry_scheduled", "attempt": attempt + 1, "defer_after_s": delay}

    await _push_to_dlq(ctx["redis"], url, payload, error, webhook_id)
    return {"status": "dead_lettered", "attempt": attempt}
