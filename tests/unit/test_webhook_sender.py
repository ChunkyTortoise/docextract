"""Tests for webhook sender service."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.webhook_sender import (
    _sign_payload,
    decrypt_secret,
    encrypt_secret,
    send_webhook,
)


class TestHMACSignature:
    def test_sign_payload_format(self):
        sig = _sign_payload(b'{"test": true}', "my-secret")
        assert sig.startswith("sha256=")

    def test_sign_payload_deterministic(self):
        payload = b'{"job": "123"}'
        sig1 = _sign_payload(payload, "secret")
        sig2 = _sign_payload(payload, "secret")
        assert sig1 == sig2

    def test_sign_payload_different_secrets(self):
        payload = b'{"job": "123"}'
        sig1 = _sign_payload(payload, "secret1")
        sig2 = _sign_payload(payload, "secret2")
        assert sig1 != sig2

    def test_sign_payload_verifiable(self):
        payload = b'{"data": "value"}'
        secret = "test-secret"
        sig = _sign_payload(payload, secret)
        # Verify manually
        expected = "sha256=" + hmac.new(
            secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        assert sig == expected


class TestAESEncryption:
    @pytest.fixture
    def aes_key_b64(self):
        """Generate a valid base64-encoded 32-byte AES key."""
        import os
        return base64.b64encode(os.urandom(32)).decode()

    def test_encrypt_decrypt_roundtrip(self, aes_key_b64):
        original = "webhook-secret-value"
        encrypted = encrypt_secret(original, aes_key_b64)
        decrypted = decrypt_secret(encrypted, aes_key_b64)
        assert decrypted == original

    def test_encrypted_differs_from_plaintext(self, aes_key_b64):
        original = "webhook-secret-value"
        encrypted = encrypt_secret(original, aes_key_b64)
        assert encrypted != original

    def test_different_encryptions_are_unique(self, aes_key_b64):
        """Each encryption uses a random nonce, so outputs differ."""
        original = "same-secret"
        enc1 = encrypt_secret(original, aes_key_b64)
        enc2 = encrypt_secret(original, aes_key_b64)
        assert enc1 != enc2
        # But both decrypt to the same value
        assert decrypt_secret(enc1, aes_key_b64) == original
        assert decrypt_secret(enc2, aes_key_b64) == original

    def test_wrong_key_fails(self, aes_key_b64):
        import os
        wrong_key = base64.b64encode(os.urandom(32)).decode()
        encrypted = encrypt_secret("secret", aes_key_b64)
        with pytest.raises(Exception):  # InvalidTag from cryptography
            decrypt_secret(encrypted, wrong_key)


class TestSendWebhook:
    @pytest.mark.asyncio
    async def test_successful_delivery(self):
        """Test webhook delivered on first attempt."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.webhook_sender.httpx.AsyncClient", return_value=mock_client):
            result = await send_webhook(
                "https://example.com/hook",
                {"event": "job.completed"},
                "my-secret",
            )

        assert result is True
        mock_client.post.assert_called_once()
        # Verify signature header was included
        call_kwargs = mock_client.post.call_args
        assert "X-Signature-256" in call_kwargs.kwargs["headers"]

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Test retries on server error then succeeds."""
        fail_response = MagicMock()
        fail_response.is_success = False
        fail_response.status_code = 500

        success_response = MagicMock()
        success_response.is_success = True

        mock_client = AsyncMock()
        mock_client.post.side_effect = [fail_response, success_response]
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.webhook_sender.httpx.AsyncClient", return_value=mock_client),
            patch("app.services.webhook_sender.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await send_webhook(
                "https://example.com/hook",
                {"event": "test"},
                "secret",
            )

        assert result is True
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self):
        """Test returns False after all retries fail."""
        fail_response = MagicMock()
        fail_response.is_success = False
        fail_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.post.return_value = fail_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.webhook_sender.httpx.AsyncClient", return_value=mock_client),
            patch("app.services.webhook_sender.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await send_webhook(
                "https://example.com/hook",
                {"event": "test"},
                "secret",
            )

        assert result is False
        assert mock_client.post.call_count == 4  # len(RETRY_DELAYS)

    @pytest.mark.asyncio
    async def test_retry_on_network_error(self):
        """Test retries on httpx.HTTPError."""
        success_response = MagicMock()
        success_response.is_success = True

        mock_client = AsyncMock()
        mock_client.post.side_effect = [
            httpx.ConnectError("Connection refused"),
            success_response,
        ]
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.webhook_sender.httpx.AsyncClient", return_value=mock_client),
            patch("app.services.webhook_sender.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await send_webhook(
                "https://example.com/hook",
                {"event": "test"},
                "secret",
            )

        assert result is True
