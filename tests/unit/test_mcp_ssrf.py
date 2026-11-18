"""SSRF guard tests for mcp_server._validate_fetch_url (getaddrinfo mocked, no network)."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

import mcp_server


def _resolves_to(*addrs: str):
    def fake(host, port, *args, **kwargs):
        return [
            (socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port))
            for a in addrs
        ]

    return patch("mcp_server.socket.getaddrinfo", side_effect=fake)


BYPASSES = [
    "https://localhost/",
    "https://localhost./",
    "https://app.localhost/",
    "https://metadata.google.internal/",
    "https://svc.corp.internal/",
    "https://127.1/",
    "https://0x7f.1/",
    "https://2130706433/",
    "https://0177.0.0.1/",
    "https://127.0.0.1/",
    "https://[::1]/",
    "https://[::ffff:127.0.0.1]/",
    "https://169.254.169.254/latest/meta-data/",
    "https://10.0.0.5/",
    "https://0.0.0.0/",
    "https://100.64.0.1/",
    "https://224.0.0.1/",
    "https://LOCALHOST/",
    "https://user:pw@127.0.0.1:8443/",
    "https://example.com\\@127.0.0.1/",
    "https://[fe80::1%25en0]/",
    "https://[::127.0.0.1]/",  # IPv4-compatible
    "https://[::ffff:0:7f00:1]/",  # IPv4-translated
    "https://[64:ff9b::a9fe:a9fe]/",  # NAT64 -> 169.254.169.254
    "https://[64:ff9b:1::a00:5]/",  # NAT64 local-use -> 10.0.0.5
    "https://[2002:7f00:1::]/",  # 6to4 -> 127.0.0.1
    "https://[2001:0:4136:e378:8000:63bf:80ff:fffe]/",  # Teredo, client 127.0.0.1
]


@pytest.mark.parametrize("url", BYPASSES)
def test_blocked(url):
    with _resolves_to("93.184.216.34") as gai, pytest.raises(ValueError, match="not allowed"):
        mcp_server._validate_fetch_url(url)
    # IP literals and blocked names never need DNS
    gai.assert_not_called()


@pytest.mark.parametrize(
    "resolved",
    [
        ["127.0.0.1"],
        ["10.1.2.3"],
        ["169.254.169.254"],
        ["::1"],
        ["::ffff:10.0.0.1"],
        ["93.184.216.34", "192.168.1.1"],
        ["64:ff9b::a00:1"],
        ["::7f00:1"],
        ["2002:a9fe:a9fe::1"],
    ],
)
def test_hostname_resolving_to_internal_blocked(resolved):
    with _resolves_to(*resolved), pytest.raises(ValueError, match="not allowed"):
        mcp_server._validate_fetch_url("https://rebind.example.com/f.pdf")


def test_unresolvable_host_blocked():
    with (
        patch("mcp_server.socket.getaddrinfo", side_effect=socket.gaierror),
        pytest.raises(ValueError, match="resolve"),
    ):
        mcp_server._validate_fetch_url("https://nope.example.com/")


@pytest.mark.parametrize(
    "url", ["http://example.com/", "ftp://example.com/x", "file:///etc/passwd"]
)
def test_non_https_blocked(url):
    with pytest.raises(ValueError, match="https"):
        mcp_server._validate_fetch_url(url)


@pytest.mark.parametrize(
    ("url", "resolved"),
    [
        ("https://example.com/doc.pdf", ["93.184.216.34"]),
        (
            "https://example.com:8443/doc.pdf",
            ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"],
        ),
        ("https://8.8.8.8/doc.pdf", ["8.8.8.8"]),
        ("https://[64:ff9b::808:808]/doc.pdf", []),  # NAT64 of a public IPv4
        ("https://Example.COM./doc.pdf", ["93.184.216.34"]),
    ],
)
def test_public_allowed(url, resolved):
    with _resolves_to(*resolved):
        mcp_server._validate_fetch_url(url)
