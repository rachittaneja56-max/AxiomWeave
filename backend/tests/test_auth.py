from hashlib import sha256

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import AuthSession, LoginThrottle, User
from app.passwords import hash_password, normalize_username, validate_password, verify_password
from app.settings import get_settings


def test_registration_login_and_digest_only_session(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    first = client.post(
        "/api/auth/register", json={"username": " Rachit ", "password": "fictional test passphrase"}
    )
    assert first.status_code == 200
    assert first.json() == {"authenticated": True, "username": "rachit"}
    raw_cookie = first.cookies["axiomweave_session"]
    assert client.get("/api/auth/session").json() == {"authenticated": True, "username": "rachit"}
    set_cookie = first.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=lax" in set_cookie and "path=/" in set_cookie
    with factory() as session:
        user = session.scalar(select(User))
        stored = session.scalar(select(AuthSession))
        assert user is not None and user.password_hash.startswith("$argon2id$")
        assert "fictional test passphrase" not in user.password_hash
        assert (
            stored is not None
            and stored.session_token_digest == sha256(raw_cookie.encode()).hexdigest()
        )
        assert stored.session_token_digest != raw_cookie
    client.post("/api/auth/logout")
    assert client.get("/api/auth/session").status_code == 401
    logged_in = client.post(
        "/api/auth/login", json={"username": "RACHIT", "password": "fictional test passphrase"}
    )
    assert logged_in.status_code == 200
    assert logged_in.cookies["axiomweave_session"] != raw_cookie


def test_registration_validation_uniqueness_and_config(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, _factory = auth_database
    assert client.get("/api/auth/config").json() == {"registration_enabled": True}
    assert (
        client.post(
            "/api/auth/register", json={"username": "ab", "password": "fictional test passphrase"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/auth/register",
            json={"username": "bad name", "password": "fictional test passphrase"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/auth/register", json={"username": "valid_user", "password": "short"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/auth/register",
            json={"username": "valid_user", "password": "fictional test passphrase"},
        ).status_code
        == 200
    )
    duplicate = client.post(
        "/api/auth/register",
        json={"username": " VALID_USER ", "password": "fictional test passphrase"},
    )
    assert duplicate.status_code == 409


def test_password_primitives() -> None:
    assert normalize_username("  Rachit_01  ") == "rachit_01"
    first = hash_password("fictional test passphrase")
    second = hash_password("fictional test passphrase")
    assert first.startswith("$argon2id$") and first != second
    assert verify_password("fictional test passphrase", first)
    assert not verify_password("wrong fictional phrase", first)
    assert not verify_password("anything", "!disabled-legacy-google!")
    for value in ("short", "x" * 129, "Password123"):
        try:
            validate_password(value)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid password accepted")
    validate_password("123456789012345")
    validate_password("long passphrase with spaces and ?")


def test_generic_failure_dummy_path_and_persistent_throttle(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    register = client.post(
        "/api/auth/register",
        json={"username": "known_user", "password": "fictional test passphrase"},
    )
    assert register.status_code == 200
    client.cookies.clear()
    known = client.post(
        "/api/auth/login", json={"username": "known_user", "password": "wrong fictional phrase"}
    )
    unknown = client.post(
        "/api/auth/login", json={"username": "unknown_user", "password": "wrong fictional phrase"}
    )
    assert known.status_code == unknown.status_code == 401
    assert known.json() == unknown.json()
    for _ in range(7):
        client.post(
            "/api/auth/login",
            json={"username": "unknown_user", "password": "wrong fictional phrase"},
        )
    blocked = client.post(
        "/api/auth/login", json={"username": "unknown_user", "password": "wrong fictional phrase"}
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "too_many_login_attempts"
    with factory() as session:
        buckets = list(session.scalars(select(LoginThrottle)))
    assert any(len(bucket.login_key_digest) == 64 for bucket in buckets)
    assert all(bucket.login_key_digest != "unknown_user" for bucket in buckets)


def test_registration_is_safe_disabled_by_default(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]], monkeypatch: MonkeyPatch
) -> None:
    client, _engine, _factory = auth_database
    monkeypatch.setenv("SIH_ALLOW_REGISTRATION", "false")
    get_settings.cache_clear()
    assert client.get("/api/auth/config").json() == {"registration_enabled": False}
    response = client.post(
        "/api/auth/register",
        json={"username": "closed_user", "password": "fictional test passphrase"},
    )
    assert response.status_code == 403


def test_login_rejects_legacy_disabled_user_and_logout_is_idempotent(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    with factory() as session:
        session.add(User(username="legacy-migrated-7", password_hash="!disabled-legacy-google!"))
        session.commit()
    failed = client.post(
        "/api/auth/login",
        json={"username": "legacy-migrated-7", "password": "fictional test passphrase"},
    )
    assert failed.status_code == 401
    client.cookies.clear()
    assert client.post("/api/auth/logout").status_code == 204
    assert client.post("/api/auth/logout").status_code == 204


def test_cookie_is_secure_in_production(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]], monkeypatch: MonkeyPatch
) -> None:
    client, _engine, _factory = auth_database
    monkeypatch.setenv("SIH_ENVIRONMENT", "production")
    get_settings.cache_clear()
    response = client.post(
        "/api/auth/register",
        json={"username": "secure_user", "password": "fictional test passphrase"},
    )
    assert response.status_code == 200
    assert "secure" in response.headers["set-cookie"].lower()
