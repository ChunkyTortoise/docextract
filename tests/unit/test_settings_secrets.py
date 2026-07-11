"""M7: Settings must never leak secret values via repr/str/traceback."""
from __future__ import annotations

import traceback

import pytest

from app.config import Settings

DUMMY_SECRETS = {
    "anthropic_api_key": "sk-ant-dummy-11111111111111111111",
    "gemini_api_key": "AIzaSy-dummy-22222222222222222222",
    "api_key_secret": "dummy-api-key-secret-32-chars-min!",
    "r2_access_key_id": "dummy-r2-access-key-33333333",
    "r2_secret_access_key": "dummy-r2-secret-key-44444444",
    "aes_key": "ZHVtbXktYWVzLWtleS1kdW1teS1hZXMta2V5ISE=",
    "demo_api_key": "dummy-demo-key-55555555",
    "langsmith_api_key": "ls-dummy-66666666666666666666",
    "langfuse_public_key": "pk-lf-dummy-7777777777777777",
    "langfuse_secret_key": "sk-lf-dummy-8888888888888888",
}


def _build_settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://u:p@h/d",
        redis_url="redis://localhost",
        **DUMMY_SECRETS,
    )


def test_repr_does_not_contain_secret_values():
    settings_instance = _build_settings()
    rendered = repr(settings_instance)
    for name, value in DUMMY_SECRETS.items():
        assert value not in rendered, f"{name} value leaked into repr()"


def test_str_does_not_contain_secret_values():
    settings_instance = _build_settings()
    rendered = str(settings_instance)
    for name, value in DUMMY_SECRETS.items():
        assert value not in rendered, f"{name} value leaked into str()"


def test_traceback_does_not_contain_secret_values():
    settings_instance = _build_settings()

    try:
        settings_instance.this_attribute_does_not_exist  # noqa: B018
        raise AssertionError("expected AttributeError was not raised")
    except AttributeError as exc:
        formatted = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )

    for name, value in DUMMY_SECRETS.items():
        assert value not in formatted, f"{name} value leaked into traceback"


@pytest.mark.parametrize(
    "field_name",
    [
        "api_key_secret",
        "gemini_api_key",
        "demo_api_key",
        "langsmith_api_key",
        "langfuse_public_key",
        "langfuse_secret_key",
    ],
)
def test_secretstr_fields_expose_real_value_via_get_secret_value(field_name):
    """SecretStr-wrapped fields must still yield the real value on demand."""
    settings_instance = _build_settings()
    field_value = getattr(settings_instance, field_name)
    assert field_value.get_secret_value() == DUMMY_SECRETS[field_name]


@pytest.mark.parametrize(
    "field_name", ["anthropic_api_key", "aes_key", "r2_access_key_id", "r2_secret_access_key"]
)
def test_repr_excluded_fields_still_behave_as_plain_strings(field_name):
    """These fields stay plain str (Field(repr=False)) because out-of-scope
    call sites (app/services/claude_extractor.py, app/api/documents.py,
    tests/unit/test_storage.py) consume/mock them directly as strings, but
    they must not appear in repr()/str() output."""
    settings_instance = _build_settings()
    field_value = getattr(settings_instance, field_name)
    assert field_value == DUMMY_SECRETS[field_name]
    assert isinstance(field_value, str)
