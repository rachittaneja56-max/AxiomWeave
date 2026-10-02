from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import create_database_engine, create_session_factory, get_db_session
from app.main import app
from app.models import Base


@pytest.fixture
def auth_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Engine, sessionmaker[Session]]]:
    monkeypatch.setenv("SIH_ALLOW_REGISTRATION", "true")
    monkeypatch.setenv("SIH_ENVIRONMENT", "development")
    monkeypatch.setenv("SIH_PRIVATE_ASSET_DIR", str(tmp_path / "private-assets"))
    from app.settings import get_settings

    get_settings.cache_clear()
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'auth.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)

    def override_session() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_session
    client = TestClient(app)
    yield client, engine, factory
    client.close()
    app.dependency_overrides.clear()
    engine.dispose()
    get_settings.cache_clear()


def login(client: TestClient, subject: str = "subject-1") -> str:
    username = subject.replace("-", "_")
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "fictional test passphrase"},
    )
    assert response.status_code == 200
    return response.cookies["axiomweave_session"]


@pytest.fixture
def authorized_client(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> TestClient:
    client, _engine, _factory = auth_database
    login(client)
    return client
