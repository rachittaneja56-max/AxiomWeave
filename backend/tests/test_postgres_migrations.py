import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, make_url

from alembic import command

BACKEND_ROOT = Path(__file__).resolve().parents[1]
POSTGRES_TEST_URL_ENV = "AXIOMWEAVE_TEST_POSTGRES_URL"


@pytest.fixture
def postgres_test_database_url() -> Iterator[URL]:
    configured_url = os.getenv(POSTGRES_TEST_URL_ENV)
    if not configured_url:
        pytest.skip(f"Set {POSTGRES_TEST_URL_ENV} to run PostgreSQL migration integration tests")

    base_url = make_url(configured_url).set(drivername="postgresql+psycopg")
    admin_engine = create_engine(base_url, isolation_level="AUTOCOMMIT")
    database_name = f"axiomweave_test_{uuid4().hex}"
    database_created = False
    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        database_created = True

        database_url = base_url.set(database=database_name)
        empty_engine = create_engine(database_url)
        try:
            assert inspect(empty_engine).get_table_names() == []
        finally:
            empty_engine.dispose()

        yield database_url
    finally:
        if database_created:
            with admin_engine.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
        admin_engine.dispose()


def _upgrade(database_url: URL, revision: str) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    rendered_url = database_url.render_as_string(hide_password=False).replace("%", "%%")
    config.set_main_option("sqlalchemy.url", rendered_url)
    command.upgrade(config, revision)


def test_postgres_populated_legacy_auth_upgrade_preserves_data(
    postgres_test_database_url: URL,
) -> None:
    _upgrade(postgres_test_database_url, "f0ba32d0f7a1")
    engine = create_engine(postgres_test_database_url)
    session_digest = "s" * 64
    try:
        user_columns = {column["name"] for column in inspect(engine).get_columns("users")}
        assert "google_subject" in user_columns
        assert "username" not in user_columns

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, google_subject, created_at) "
                    "VALUES (42, 'legacy-google-42', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO auth_sessions "
                    "(user_id, session_token_digest, expires_at, created_at) "
                    "VALUES (42, :digest, CURRENT_TIMESTAMP + INTERVAL '1 day', CURRENT_TIMESTAMP)"
                ),
                {"digest": session_digest},
            )
            connection.execute(
                text(
                    "INSERT INTO sources (owner_id, title, created_at) "
                    "VALUES (42, 'Legacy source', CURRENT_TIMESTAMP)"
                )
            )
            assert (
                connection.scalar(
                    text("SELECT id FROM users WHERE google_subject = 'legacy-google-42'")
                )
                == 42
            )
            assert (
                connection.scalar(
                    text("SELECT user_id FROM auth_sessions WHERE session_token_digest = :digest"),
                    {"digest": session_digest},
                )
                == 42
            )
            assert (
                connection.scalar(
                    text("SELECT owner_id FROM sources WHERE title = 'Legacy source'")
                )
                == 42
            )

        _upgrade(postgres_test_database_url, "head")

        inspector = inspect(engine)
        user_columns = {column["name"]: column for column in inspector.get_columns("users")}
        assert "google_subject" not in user_columns
        assert user_columns["username"]["nullable"] is False
        assert user_columns["password_hash"]["nullable"] is False
        assert any(
            constraint.get("column_names") == ["username"]
            for constraint in inspector.get_unique_constraints("users")
        )

        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            user = (
                connection.execute(
                    text("SELECT id, username, password_hash FROM users WHERE id = 42")
                )
                .mappings()
                .one()
            )
            auth_session = (
                connection.execute(
                    text(
                        "SELECT user_id, revoked_at FROM auth_sessions "
                        "WHERE session_token_digest = :digest"
                    ),
                    {"digest": session_digest},
                )
                .mappings()
                .one()
            )
            source_owner_id = connection.scalar(
                text("SELECT owner_id FROM sources WHERE title = 'Legacy source'")
            )

        assert revision == "c2a7e18f4d91"
        assert user["id"] == 42
        assert user["username"] == "legacy-migrated-42"
        assert user["password_hash"] == "!disabled-legacy-google!"
        assert auth_session["user_id"] == 42
        assert auth_session["revoked_at"] is not None
        assert source_owner_id == 42

        for table, column in (("auth_sessions", "user_id"), ("sources", "owner_id")):
            assert any(
                foreign_key.get("constrained_columns") == [column]
                and foreign_key.get("referred_table") == "users"
                and foreign_key.get("referred_columns") == ["id"]
                for foreign_key in inspector.get_foreign_keys(table)
            )
    finally:
        engine.dispose()


def test_postgres_migrations_reach_head_from_an_empty_database(
    postgres_test_database_url: URL,
) -> None:
    _upgrade(postgres_test_database_url, "head")
    engine = create_engine(postgres_test_database_url)
    try:
        inspector = inspect(engine)
        assert {
            "users",
            "auth_sessions",
            "sources",
            "source_versions",
            "source_segments",
            "artifact_runs",
            "artifact_versions",
            "evidence_links",
            "discrepancy_findings",
            "login_throttles",
            "alembic_version",
        } <= set(inspector.get_table_names())
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == "c2a7e18f4d91"

        unique_constraints = inspector.get_unique_constraints("artifact_runs")
        assert "uq_artifact_runs_transformation_output" in {
            constraint.get("name") for constraint in unique_constraints
        }
        check_constraints = inspector.get_check_constraints("artifact_runs")
        assert "ck_artifact_runs_status" in {
            constraint.get("name") for constraint in check_constraints
        }
        auth_foreign_keys = inspector.get_foreign_keys("auth_sessions")
        assert any(
            foreign_key.get("referred_table") == "users"
            and foreign_key.get("options", {}).get("ondelete") == "RESTRICT"
            for foreign_key in auth_foreign_keys
        )
    finally:
        engine.dispose()
