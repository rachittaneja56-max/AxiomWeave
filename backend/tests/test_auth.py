from datetime import UTC, datetime, timedelta
from hashlib import sha256

from auth_support import login
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    ArtifactRun,
    ArtifactVersion,
    AuthSession,
    Source,
    SourceVersion,
    TransformationRun,
    User,
)
from app.settings import get_settings


def test_login_creates_and_reuses_user_and_persists_only_session_digest(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    first_response = client.post("/api/auth/google", json={"credential": "verified:rachit"})
    second_response = client.post("/api/auth/google", json={"credential": "verified:rachit"})

    assert first_response.status_code == second_response.status_code == 200
    assert first_response.json() == {"authenticated": True}
    assert client.get("/api/auth/session").json() == {"authenticated": True}
    cookie = first_response.cookies["axiomweave_session"]
    assert cookie
    set_cookie = first_response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=lax" in set_cookie and "path=/" in set_cookie
    assert "secure" not in set_cookie
    max_age = next(part for part in set_cookie.split(";") if "max-age=" in part)
    assert 0 < int(max_age.split("=", maxsplit=1)[1]) <= 8 * 60 * 60

    with factory() as session:
        users = session.scalars(select(User)).all()
        sessions = session.scalars(select(AuthSession)).all()
    assert len(users) == 1
    assert users[0].google_subject == "rachit"
    assert len(sessions) == 2
    assert all(item.session_token_digest != cookie for item in sessions)
    assert all(len(item.session_token_digest) == 64 for item in sessions)
    assert all(
        7.99
        <= (item.expires_at.replace(tzinfo=UTC) - datetime.now(UTC)).total_seconds() / 3600
        <= 8
        for item in sessions
    )


def test_invalid_credential_and_missing_configuration_fail_safely(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]], monkeypatch: MonkeyPatch
) -> None:
    client, _engine, _factory = auth_database
    invalid = client.post("/api/auth/google", json={"credential": "invalid-secret-value"})
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "invalid_google_credential"
    assert "invalid-secret-value" not in invalid.text

    monkeypatch.setenv("SIH_GOOGLE_CLIENT_ID", "")
    get_settings.cache_clear()
    unconfigured = client.post("/api/auth/google", json={"credential": "verified:anyone"})
    assert unconfigured.status_code == 503
    assert unconfigured.json()["error"]["code"] == "google_auth_not_configured"


def test_session_resolution_rejects_missing_unknown_expired_and_revoked_tokens(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    assert client.get("/api/auth/session").status_code == 401
    client.cookies.set("axiomweave_session", "not-in-database")
    assert client.get("/api/auth/session").status_code == 401

    with factory() as session:
        user = User(google_subject="session-tests")
        session.add(user)
        session.flush()
        expired_token = "expired-token"
        revoked_token = "revoked-token"
        session.add_all(
            [
                AuthSession(
                    user_id=user.id,
                    session_token_digest=sha256(expired_token.encode()).hexdigest(),
                    expires_at=datetime.now(UTC) - timedelta(seconds=1),
                ),
                AuthSession(
                    user_id=user.id,
                    session_token_digest=sha256(revoked_token.encode()).hexdigest(),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                    revoked_at=datetime.now(UTC),
                ),
            ]
        )
        session.commit()

    for token in (expired_token, revoked_token):
        client.cookies.set("axiomweave_session", token)
        response = client.get("/api/auth/session")
        assert response.status_code == 401
        assert response.json()["error"]["message"] == "Sign in to continue."


def test_logout_revokes_session_and_clears_cookie(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    raw_token = login(client, "logout-test")
    response = client.post("/api/auth/logout")
    assert response.status_code == 204
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert client.get("/api/auth/session").status_code == 401

    with factory() as session:
        stored = session.scalar(select(AuthSession))
    assert stored is not None
    assert stored.revoked_at is not None
    assert stored.session_token_digest != raw_token


def test_health_is_public_and_workspace_endpoints_require_session(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, _factory = auth_database
    client.cookies.clear()
    assert client.get("/api/health").status_code == 200
    assert (
        client.post("/api/sources/text-file", files={"file": ("a.txt", b"hello")}).status_code
        == 401
    )
    assert client.post("/api/transformations/prepare", json={}).status_code == 401


def test_cookie_is_secure_outside_development(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]], monkeypatch: MonkeyPatch
) -> None:
    client, _engine, _factory = auth_database
    monkeypatch.setenv("SIH_ENVIRONMENT", "production")
    get_settings.cache_clear()
    response = client.post("/api/auth/google", json={"credential": "verified:secure"})
    assert response.status_code == 200
    assert "secure" in response.headers["set-cookie"].lower()


def test_all_hierarchical_owner_lookups_enforce_owner_in_query(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    from app.ownership import (
        get_owned_artifact_run,
        get_owned_artifact_version,
        get_owned_source,
        get_owned_source_version,
        get_owned_transformation_run,
    )

    _client, _engine, factory = auth_database
    with factory() as session:
        owner = User(google_subject="owner")
        other = User(google_subject="other")
        session.add_all([owner, other])
        session.flush()
        source = Source(owner_id=owner.id)
        source_other = Source(owner_id=other.id)
        session.add_all([source, source_other])
        session.flush()
        version = SourceVersion(
            source_id=source.id,
            version_number=1,
            source_text="trusted source",
            content_hash="a" * 64,
        )
        version_other = SourceVersion(
            source_id=source_other.id,
            version_number=1,
            source_text="another source",
            content_hash="b" * 64,
        )
        session.add_all([version, version_other])
        session.flush()
        run = TransformationRun(
            owner_id=owner.id,
            source_version_id=version.id,
            audience="Public",
            tone="Clear",
            language="English",
            detail_level="standard",
            objective="Inform",
            style="Plain",
            selected_output_types=["executive_summary"],
        )
        run_other = TransformationRun(
            owner_id=other.id,
            source_version_id=version_other.id,
            audience="Public",
            tone="Clear",
            language="English",
            detail_level="standard",
            objective="Inform",
            style="Plain",
            selected_output_types=["executive_summary"],
        )
        session.add_all([run, run_other])
        session.flush()
        artifact_run = ArtifactRun(transformation_run_id=run.id, output_type="executive_summary")
        artifact_run_other = ArtifactRun(
            transformation_run_id=run_other.id, output_type="executive_summary"
        )
        session.add_all([artifact_run, artifact_run_other])
        session.flush()
        artifact_version = ArtifactVersion(
            artifact_run_id=artifact_run.id,
            version_number=1,
            source_version_id=version.id,
            content="Draft",
        )
        artifact_version_other = ArtifactVersion(
            artifact_run_id=artifact_run_other.id,
            version_number=1,
            source_version_id=version_other.id,
            content="Other draft",
        )
        session.add_all([artifact_version, artifact_version_other])
        session.flush()

        assert get_owned_source(session, owner.id, source.id) is not None
        assert get_owned_source(session, owner.id, source_other.id) is None
        assert get_owned_source_version(session, owner.id, version.id) is not None
        assert get_owned_source_version(session, owner.id, version_other.id) is None
        assert get_owned_transformation_run(session, owner.id, run.id) is not None
        assert get_owned_transformation_run(session, owner.id, run_other.id) is None
        assert get_owned_artifact_run(session, owner.id, artifact_run.id) is not None
        assert get_owned_artifact_run(session, owner.id, artifact_run_other.id) is None
        assert get_owned_artifact_version(session, owner.id, artifact_version.id) is not None
        assert get_owned_artifact_version(session, owner.id, artifact_version_other.id) is None
