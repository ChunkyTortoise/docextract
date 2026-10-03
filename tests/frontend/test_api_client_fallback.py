"""get_client() must work without a secrets.toml.

Streamlit is not importable in the test venv, so ``streamlit`` is stubbed via
sys.modules. patch.dict restores sys.modules afterwards, so the freshly
imported frontend.api_client does not leak into other tests.
"""
from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest


class _FakeSessionState(dict):
    def __getattr__(self, key):
        return self.get(key)

    def __setattr__(self, key, val):
        self[key] = val


class _MissingSecrets:
    """Mimics st.secrets when no secrets.toml exists: every read raises."""

    def get(self, key, default=None):
        raise FileNotFoundError("No secrets found. Valid paths for a secrets.toml file are: /x/secrets.toml")


def _make_stub(secrets) -> MagicMock:
    stub = MagicMock(name="streamlit")
    stub.session_state = _FakeSessionState()
    stub.secrets = secrets
    return stub


@pytest.fixture
def load_api_client() -> Iterator:
    patchers: list = []

    def _load(secrets, session_state: dict | None = None):
        stub = _make_stub(secrets)
        stub.session_state.update(session_state or {})
        p = patch.dict(sys.modules, {"streamlit": stub})
        p.start()
        patchers.append(p)
        sys.modules.pop("frontend.api_client", None)
        return importlib.import_module("frontend.api_client")

    yield _load
    for p in reversed(patchers):
        p.stop()


def _base(client) -> str:
    return str(client.base_url).rstrip("/")


def test_no_secrets_no_env_uses_localhost(load_api_client, monkeypatch) -> None:
    monkeypatch.delenv("API_URL", raising=False)
    mod = load_api_client(_MissingSecrets())
    with mod.get_client() as client:
        assert _base(client) == "http://localhost:8000/api/v1"
        assert client.headers["X-API-Key"] == ""


def test_no_secrets_uses_api_url_env(load_api_client, monkeypatch) -> None:
    monkeypatch.setenv("API_URL", "http://api:8000")
    mod = load_api_client(_MissingSecrets())
    with mod.get_client() as client:
        assert _base(client) == "http://api:8000/api/v1"


def test_secrets_api_url_wins_over_env(load_api_client, monkeypatch) -> None:
    monkeypatch.setenv("API_URL", "http://api:8000")
    mod = load_api_client({"api_url": "http://secrets-host:9000"})
    with mod.get_client() as client:
        assert _base(client) == "http://secrets-host:9000/api/v1"


def test_secrets_without_api_url_falls_back_to_env(load_api_client, monkeypatch) -> None:
    monkeypatch.setenv("API_URL", "http://api:8000")
    mod = load_api_client({"api_key": "k"})
    with mod.get_client() as client:
        assert _base(client) == "http://api:8000/api/v1"


@pytest.mark.parametrize(
    ("secrets", "session_state", "expected"),
    [
        ({"api_key": "from-secrets"}, {"api_key": "from-session"}, "from-session"),
        ({"api_key": "from-secrets"}, {}, "from-secrets"),
        ({}, {}, ""),
        (_MissingSecrets(), {}, ""),
        (_MissingSecrets(), {"api_key": "from-session"}, "from-session"),
    ],
)
def test_api_key_resolution_order(load_api_client, monkeypatch, secrets, session_state, expected) -> None:
    monkeypatch.delenv("API_URL", raising=False)
    mod = load_api_client(secrets, session_state)
    with mod.get_client() as client:
        assert client.headers["X-API-Key"] == expected


def test_secret_helper_catches_streamlit_secret_error(load_api_client) -> None:
    mod = load_api_client({})

    class _Raises:
        def get(self, key, default=None):
            raise mod.StreamlitSecretNotFoundError("missing")

    mod.st.secrets = _Raises()
    assert mod._secret("api_url", "fallback") == "fallback"
