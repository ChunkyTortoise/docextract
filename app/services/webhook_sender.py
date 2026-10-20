"""HMAC-SHA256 signed webhook sender with deferred retries, DLQ, and AES-GCM encryption."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import UTC, datetime

import httpx
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

RETRY_DELAYS = [0, 30, 300, 1800]  # immediate, 30s, 5min, 30min
MAX_ATTEMPTS = len(RETRY_DELAYS)  # 4 total (1 initial + 3 retries)
DLQ_KEY = "dlq:webhooks"


def encrypt_secret(secret: str, aes_key_b64: str) -> str:
    """Encrypt webhook secret using AES-GCM."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = base64.b64decode(aes_key_b64)
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, secret.encode(), None)
    # Format: base64(nonce + ciphertext)
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt_secret(encrypted: str, aes_key_b64: str) -> str:
    """Decrypt AES-GCM encrypted webhook secret."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = base64.b64decode(aes_key_b64)
    raw = base64.b64decode(encrypted)
    nonce, ciphertext = raw[:12], raw[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None).decode()


def _sign_payload(payload: bytes, secret: str) -> str:
    """Create HMAC-SHA256 signature."""
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


async def attempt_webhook(
    url: str, payload: dict, secret: str, attempt: int = 1
) -> tuple[bool, str]:
    """Make exactly one signed delivery attempt: no retries, no sleeps, no DLQ.

    Retries are scheduled as deferred ARQ jobs by worker.webhook_tasks so each
    attempt runs inside its own job timeout instead of sleeping inline.

    Returns (delivered, error) with error empty on success.
    """
    body = json.dumps(payload).encode()
    signature = _sign_payload(body, secret)

    headers = {
        "Content-Type": "application/json",
        "X-Signature-256": signature,
        "X-Timestamp": datetime.now(UTC).isoformat(),
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, content=body, headers=headers)
            if resp.is_success:
                logger.info("Webhook delivered to %s (attempt %d)", url, attempt)
                return True, ""
            logger.warning(
                "Webhook attempt %d/%d failed: %s %s",
                attempt, MAX_ATTEMPTS, resp.status_code, url,
            )
            return False, f"HTTP {resp.status_code}"
    except httpx.HTTPError as e:
        logger.warning(
            "Webhook attempt %d/%d error: %s (%s)",
            attempt, MAX_ATTEMPTS, e, url,
        )
        return False, str(e)


async def send_webhook(url: str, payload: dict, secret: str) -> bool:
    """Send a single signed webhook attempt (used by POST /webhooks/test).

    Delivery retries and DLQ handling belong to the deferred delivery job.
    """
    delivered, _error = await attempt_webhook(url, payload, secret)
    return delivered


async def _push_to_dlq(
    redis: aioredis.Redis, url: str, payload: dict, error: str, webhook_id: str | None
) -> None:
    """Push failed webhook to the Redis dead-letter queue on the caller's client."""
    try:
        dlq_entry = json.dumps({
            "endpoint": url,
            "payload": payload,
            "error": error,
            "timestamp": datetime.now(UTC).isoformat(),
            "webhook_id": webhook_id,
        })
        await redis.rpush(DLQ_KEY, dlq_entry)
        logger.info("Webhook pushed to DLQ (%s): %s", DLQ_KEY, url)
    except Exception as e:
        logger.error("Failed to push webhook to DLQ: %s", e)
