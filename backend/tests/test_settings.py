from typing import Any, cast

import pytest
from pydantic import ValidationError

from app.settings import Settings


def test_settings_use_safe_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SIH_ENVIRONMENT", "SIH_HOST", "SIH_PORT", "SIH_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)

    settings_class = cast(Any, Settings)
    settings = settings_class(_env_file=None)

    assert settings.environment == "development"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.database_url == "sqlite:///./axiomweave.db"


def test_settings_read_database_url_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIH_DATABASE_URL", "sqlite:///./test.db")

    settings_class = cast(Any, Settings)
    settings = settings_class(_env_file=None)

    assert settings.database_url == "sqlite:///./test.db"


def test_settings_reject_invalid_port() -> None:
    with pytest.raises(ValidationError, match="port"):
        cast(Any, Settings)(port=70000, _env_file=None)
