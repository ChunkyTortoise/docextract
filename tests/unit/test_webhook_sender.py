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
    DLQ_KEY,
    MAX_ATTEMPTS,
    _push_to_dlq,
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


def _make_mock_client(post_side_effect):
    """Helper to build a mock httpx.AsyncClient with given post behaviour."""
    mock_client = AsyncMock()
    if isinstance(post_side_effect, list):
        mock_client.post.side_effect = post_side_effect
    else:
        mock_client.post.return_value = post_side_effect
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _ok_response():
    r = MagicMock()
    r.is_success = True
    r.status_code = 200
    return r


def _fail_response(status: int = 500):
    r = MagicMock()
    r.is_success = False
    r.status_code = status
    return r


class TestSendWebhook:
    @pytest.mark.asyncio
    async def test_successful_delivery(self):
        """Test webhook delivered on first attempt -- no DLQ push."""
        mock_client = _make_mock_client(_ok_response())

        with (
            patch("app.services.webhook_sender.httpx.AsyncClient", return_value=mock_client),
            patch("app.services.webhook_sender._push_to_dlq", new_callable=AsyncMock) as mock_dlq,
        ):
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
        mock_dlq.assert_not_called()

    @pytest.mark.asyncio
    async def test_retry_on_failure_then_success(self):
        """Test retries on server error then succeeds on second attempt."""
        mock_client = _make_mock_client([_fail_response(), _ok_response()])

        with (
            patch("app.services.webhook_sender.httpx.AsyncClient", return_value=mock_client),
            patch("app.services.webhook_sender.asyncio.sleep", new_callable=AsyncMock),
            patch("app.services.webhook_sender._push_to_dlq", new_callable=AsyncMock) as mock_dlq,
        ):
            result = await send_webhook(
                "https://example.com/hook",
                {"event": "test"},
                "secret",
            )

        assert result is True
        assert mock_client.post.call_count == 2
        mock_dlq.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_retries_exhausted_pushes_to_dlq(self):
        """Test returns False after all retries fail and pushes to DLQ."""
        mock_client = _make_mock_client(_fail_response())

        with (
            patch("app.services.webhook_sender.httpx.AsyncClient", return_value=mock_client),
            patch("app.services.webhook_sender.asyncio.sleep", new_callable=AsyncMock),
            patch("app.services.webhook_sender._push_to_dlq", new_callable=AsyncMock) as mock_dlq,
        ):
            result = await send_webhook(
                "https://example.com/hook",
                {"event": "test"},
                "secret",
                webhook_id="wh-123",
            )

        assert result is False
        assert mock_client.post.call_count == MAX_ATTEMPTS
        mock_dlq.assert_called_once_with(
            "https://example.com/hook",
            {"event": "test"},
            "HTTP 500",
            "wh-123",
        )

    @pytest.mark.asyncio
    async def test_retry_on_network_error(self):
        """Test retries on httpx.HTTPError then succeeds."""
        mock_client = _make_mock_client([
            httpx.ConnectError("Connection refused"),
            _ok_response(),
        ])

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

    @pytest.mark.asyncio
    async def test_network_errors_exhaust_retries_push_dlq(self):
        """All attempts fail with network errors -- pushes to DLQ."""
        mock_client = _make_mock_client(
            [httpx.ConnectError("refused")] * MAX_ATTEMPTS
        )

        with (
            patch("app.services.webhook_sender.httpx.AsyncClient", return_value=mock_client),
            patch("app.services.webhook_sender.asyncio.sleep", new_callable=AsyncMock),
            patch("app.services.webhook_sender._push_to_dlq", new_callable=AsyncMock) as mock_dlq,
        ):
            result = await send_webhook(
                "https://example.com/hook",
                {"event": "test"},
                "secret",
                webhook_id="wh-456",
            )

        assert result is False
        assert mock_client.post.call_count == MAX_ATTEMPTS
        mock_dlq.assert_called_once()
        call_args = mock_dlq.call_args
        assert call_args[0][0] == "https://example.com/hook"
        assert "refused" in call_args[0][2]

    @pytest.mark.asyncio
    async def test_sleep_delays_match_retry_schedule(self):
        """Verify asyncio.sleep is called with the correct delay values."""
        mock_client = _make_mock_client(_fail_response())
        sleep_mock = AsyncMock()

        with (
            patch("app.services.webhook_sender.httpx.AsyncClient", return_value=mock_client),
            patch("app.services.webhook_sender.asyncio.sleep", sleep_mock),
            patch("app.services.webhook_sender._push_to_dlq", new_callable=AsyncMock),
        ):
            await send_webhook("https://example.com/hook", {"event": "test"}, "secret")

        # First attempt has delay=0 (skipped), remaining attempts sleep with 30, 300, 1800
        sleep_calls = [call.args[0] for call in sleep_mock.call_args_list]
        assert sleep_calls == [30, 300, 1800]


class TestPushToDlq:
    @pytest.mark.asyncio
    async def test_push_to_dlq_writes_correct_payload(self):
        """Verify DLQ entry structure and Redis RPUSH call."""
        mock_redis = AsyncMock()
        mock_redis.rpush = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with patch(
            "app.services.webhook_sender.aioredis.from_url",
            return_value=mock_redis,
        ):
            await _push_to_dlq(
                "https://example.com/hook",
                {"event": "job.completed", "job_id": "j-1"},
                "HTTP 500",
                "wh-789",
            )

        mock_redis.rpush.assert_called_once()
        key, value = mock_redis.rpush.call_args[0]
        assert key == DLQ_KEY

        entry = json.loads(value)
        assert entry["endpoint"] == "https://example.com/hook"
        assert entry["payload"] == {"event": "job.completed", "job_id": "j-1"}
        assert entry["error"] == "HTTP 500"
        assert entry["webhook_id"] == "wh-789"
        assert "timestamp" in entry

    @pytest.mark.asyncio
    async def test_push_to_dlq_with_none_webhook_id(self):
        """DLQ entry stores None when no webhook_id provided."""
        mock_redis = AsyncMock()
        mock_redis.rpush = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with patch(
            "app.services.webhook_sender.aioredis.from_url",
            return_value=mock_redis,
        ):
            await _push_to_dlq("https://x.com/h", {}, "timeout", None)

        entry = json.loads(mock_redis.rpush.call_args[0][1])
        assert entry["webhook_id"] is None

    @pytest.mark.asyncio
    async def test_push_to_dlq_redis_failure_does_not_raise(self):
        """If Redis itself fails, _push_to_dlq logs but does not raise."""
        with patch(
            "app.services.webhook_sender.aioredis.from_url",
            side_effect=Exception("Redis down"),
        ):
            # Should NOT raise
            await _push_to_dlq("https://x.com/h", {}, "err", None)

    @pytest.mark.asyncio
    async def test_push_to_dlq_closes_redis(self):
        """Redis connection is always closed, even on rpush failure."""
        mock_redis = AsyncMock()
        mock_redis.rpush = AsyncMock(side_effect=Exception("write error"))
        mock_redis.aclose = AsyncMock()

        with patch(
            "app.services.webhook_sender.aioredis.from_url",
            return_value=mock_redis,
        ):
            await _push_to_dlq("https://x.com/h", {}, "err", None)

        mock_redis.aclose.assert_called_once()
