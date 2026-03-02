"""HMAC-SHA256 signed webhook sender with retry logic and AES-GCM encryption."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

RETRY_DELAYS = [0, 30, 300, 1800]  # immediate, 30s, 5min, 30min


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


async def send_webhook(url: str, payload: dict, secret: str) -> bool:
    """Send HMAC-signed webhook with retries.

    Args:
        url: Webhook destination URL
        payload: JSON-serializable payload dict
        secret: Raw (unencrypted) signing secret

    Returns:
        True on success, False after all retries exhausted
    """
    body = json.dumps(payload).encode()
    signature = _sign_payload(body, secret)

    headers = {
        "Content-Type": "application/json",
        "X-Signature-256": signature,
        "X-Timestamp": datetime.now(timezone.utc).isoformat(),
    }

    for attempt, delay in enumerate(RETRY_DELAYS):
        if delay > 0:
            await asyncio.sleep(delay)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, content=body, headers=headers)
                if resp.is_success:
                    logger.info("Webhook delivered to %s (attempt %d)", url, attempt + 1)
                    return True
                logger.warning(
                    "Webhook attempt %d failed: %s %s",
                    attempt + 1, resp.status_code, url,
                )
        except httpx.HTTPError as e:
            logger.warning("Webhook attempt %d error: %s (%s)", attempt + 1, e, url)

    logger.error("Webhook permanently failed after %d attempts: %s", len(RETRY_DELAYS), url)
    return False
