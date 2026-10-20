"""Tests for webhook destination validation."""
from __future__ import annotations

import socket

import pytest

from app.api.webhooks import validate_webhook_url


def _addrinfo(ip: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


def test_rejects_http_scheme():
    with pytest.raises(ValueError, match="https"):
        validate_webhook_url("http://example.com/hook")


def test_rejects_literal_loopback():
    with pytest.raises(ValueError, match="private"):
        validate_webhook_url("https://127.0.0.1/hook")


def test_rejects_literal_private_range():
    with pytest.raises(ValueError, match="private"):
        validate_webhook_url("https://10.0.0.5/hook")


def test_rejects_hostname_resolving_private(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo("10.0.0.8"))
    with pytest.raises(ValueError, match="private"):
        validate_webhook_url("https://internal.example.com/hook")


def test_rejects_unresolvable_hostname(monkeypatch):
    def boom(*args, **kwargs):
        raise socket.gaierror(-2, "name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    with pytest.raises(ValueError, match="resolve"):
        validate_webhook_url("https://nope.invalid/hook")


def test_accepts_public_hostname(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo("93.184.216.34"))
    validate_webhook_url("https://hooks.example.com/hook")
