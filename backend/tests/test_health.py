import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.api import health as health_module
from app.main import app
from app.settings import Settings

client: TestClient = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_accepts_current_migration_head(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES ('a41f028bc9e2')")
        )

    settings = Settings(private_asset_backend="s3", s3_bucket="test-bucket")

    def no_profiles(_settings: Settings | None) -> list[dict[str, object]]:
        return []

    def available_command(_command: str) -> str:
        return "available"

    monkeypatch.setattr(health_module, "get_settings", lambda: settings)
    monkeypatch.setattr(health_module, "private_asset_store_is_configured", lambda: True)
    monkeypatch.setattr(health_module, "current_model_registry", no_profiles)
    monkeypatch.setattr(health_module.shutil, "which", available_command)

    with Session(engine) as session:
        response = health_module.readiness(session)

    engine.dispose()
    assert response.migration_revision == "a41f028bc9e2"
    assert response.migration_state == "current"
    assert response.status == "ready"


def test_unknown_route_uses_structured_error() -> None:
    response = client.get("/api/missing")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Not Found"}}
