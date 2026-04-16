"""HMAC-SHA256 signed webhook sender with retry logic, DLQ, and AES-GCM encryption."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import UTC, datetime

import httpx
import redis.asyncio as aioredis

from app.config import settings

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


async def send_webhook(url: str, payload: dict, secret: str, webhook_id: str | None = None) -> bool:
    """Send HMAC-signed webhook with retries and dead-letter queue.

    Args:
        url: Webhook destination URL
        payload: JSON-serializable payload dict
        secret: Raw (unencrypted) signing secret
        webhook_id: Optional identifier for DLQ tracking

    Returns:
        True on success, False after all retries exhausted (pushed to DLQ)
    """
    body = json.dumps(payload).encode()
    signature = _sign_payload(body, secret)

    headers = {
        "Content-Type": "application/json",
        "X-Signature-256": signature,
        "X-Timestamp": datetime.now(UTC).isoformat(),
    }

    last_error: str = ""

    for attempt, delay in enumerate(RETRY_DELAYS):
        if delay > 0:
            logger.info("Webhook retry %d/%d in %ds: %s", attempt + 1, MAX_ATTEMPTS, delay, url)
            await asyncio.sleep(delay)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, content=body, headers=headers)
                if resp.is_success:
                    logger.info("Webhook delivered to %s (attempt %d)", url, attempt + 1)
                    return True
                last_error = f"HTTP {resp.status_code}"
                logger.warning(
                    "Webhook attempt %d/%d failed: %s %s",
                    attempt + 1, MAX_ATTEMPTS, resp.status_code, url,
                )
        except httpx.HTTPError as e:
            last_error = str(e)
            logger.warning("Webhook attempt %d/%d error: %s (%s)", attempt + 1, MAX_ATTEMPTS, e, url)

    logger.error("Webhook permanently failed after %d attempts: %s", MAX_ATTEMPTS, url)
    await _push_to_dlq(url, payload, last_error, webhook_id)
    return False


async def _push_to_dlq(url: str, payload: dict, error: str, webhook_id: str | None) -> None:
    """Push failed webhook to the Redis dead-letter queue."""
    try:
        redis = aioredis.from_url(settings.redis_url, decode_responses=True)
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
        finally:
            await redis.aclose()
    except Exception as e:
        logger.error("Failed to push webhook to DLQ: %s", e)
