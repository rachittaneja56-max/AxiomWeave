from typing import Any, cast

import pytest
from pydantic import ValidationError

from app.settings import Settings


def test_settings_use_safe_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "SIH_ENVIRONMENT",
        "SIH_HOST",
        "SIH_PORT",
        "SIH_DATABASE_URL",
        "SIH_ALLOW_REGISTRATION",
        "SIH_OPENAI_MODEL",
        "SIH_OPENAI_UTILITY_MODEL",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    settings_class = cast(Any, Settings)
    settings = settings_class(_env_file=None)

    assert settings.environment == "development"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.database_url == "sqlite:///./axiomweave.db"
    assert settings.allow_registration is False
    assert settings.openai_api_key is None
    assert settings.openai_model == "gpt-6-luna"
    assert settings.openai_utility_model == "gpt-5-nano"


def test_settings_read_database_url_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIH_DATABASE_URL", "sqlite:///./test.db")

    settings_class = cast(Any, Settings)
    settings = settings_class(_env_file=None)

    assert settings.database_url == "sqlite:///./test.db"


def test_settings_read_registration_flag_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIH_ALLOW_REGISTRATION", "true")

    settings_class = cast(Any, Settings)
    settings = settings_class(_env_file=None)

    assert settings.allow_registration is True


def test_settings_read_openai_configuration_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    monkeypatch.setenv("SIH_OPENAI_MODEL", "gpt-6-luna")
    monkeypatch.setenv("SIH_OPENAI_UTILITY_MODEL", "gpt-5-nano")

    settings_class = cast(Any, Settings)
    settings = settings_class(_env_file=None)

    assert settings.openai_api_key == "test-secret"
    assert settings.openai_model == "gpt-6-luna"
    assert settings.openai_utility_model == "gpt-5-nano"
    assert "test-secret" not in repr(settings)


def test_settings_reject_invalid_port() -> None:
    with pytest.raises(ValidationError, match="port"):
        cast(Any, Settings)(port=70000, _env_file=None)
