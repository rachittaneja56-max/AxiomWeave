import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.database import create_database_engine, create_session_factory
from app.models import (
    ArtifactRun,
    ArtifactVersion,
    AuthSession,
    Source,
    SourceSegment,
    SourceVersion,
    TransformationRun,
    User,
    source_content_hash,
)

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


@pytest.fixture
def postgres_runtime_sessions(
    postgres_test_database_url: URL,
) -> Iterator[sessionmaker[Session]]:
    _upgrade(postgres_test_database_url, "head")
    engine = create_database_engine(
        postgres_test_database_url.render_as_string(hide_password=False)
    )
    try:
        yield create_session_factory(engine)
    finally:
        engine.dispose()


def _add_user(session: Session, username: str) -> User:
    user = User(username=username, password_hash="!disabled-test!")
    session.add(user)
    session.flush()
    return user


def _add_source_version(
    session: Session, owner: User, source_text: str = "PostgreSQL source text"
) -> tuple[Source, SourceVersion]:
    source = Source(owner_id=owner.id, title="PostgreSQL source")
    session.add(source)
    session.flush()
    source_version = SourceVersion(
        source_id=source.id,
        version_number=1,
        source_text=source_text,
        content_hash=source_content_hash(source_text),
    )
    session.add(source_version)
    session.flush()
    return source, source_version


def _add_transformation(
    session: Session, owner: User, source_version: SourceVersion
) -> TransformationRun:
    transformation = TransformationRun(
        owner_id=owner.id,
        source_version_id=source_version.id,
        supporting_context="Use the approved event date.",
        audience="Local residents",
        tone="Clear",
        language="English",
        detail_level="standard",
        objective="Inform",
        style="Plain language",
        selected_output_types=["executive_summary", "advisory"],
    )
    session.add(transformation)
    session.flush()
    return transformation


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


def test_postgres_runtime_engine_and_session_lifecycle(
    postgres_runtime_sessions: sessionmaker[Session],
) -> None:
    first_session = postgres_runtime_sessions()
    user = User(username="pg_lifecycle", password_hash="!disabled-test!")
    first_session.add(user)
    first_session.commit()
    user_id = user.id
    first_session.close()

    with postgres_runtime_sessions() as second_session:
        persisted_user = second_session.get(User, user_id)
        assert persisted_user is not None
        assert persisted_user.username == "pg_lifecycle"


def test_postgres_runtime_owner_foreign_key_and_username_constraints(
    postgres_runtime_sessions: sessionmaker[Session],
) -> None:
    with postgres_runtime_sessions() as session:
        owner = _add_user(session, "pg_owner")
        auth_session = AuthSession(
            user_id=owner.id,
            session_token_digest="a" * 64,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        source = Source(owner_id=owner.id, title="Owned source")
        session.add_all([auth_session, source])
        session.commit()

        persisted_auth_session = session.get(AuthSession, auth_session.id)
        persisted_source = session.get(Source, source.id)
        assert persisted_auth_session is not None
        assert persisted_source is not None
        assert persisted_auth_session.user_id == owner.id
        assert persisted_source.owner_id == owner.id

        session.add(User(username="pg_owner", password_hash="!disabled-test!"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        assert session.scalar(select(User.id).where(User.id == owner.id)) == owner.id

        session.add(
            AuthSession(
                user_id=999999,
                session_token_digest="b" * 64,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        assert session.scalar(select(Source.id).where(Source.id == source.id)) == source.id


def test_postgres_runtime_source_versions_and_segments(
    postgres_runtime_sessions: sessionmaker[Session],
) -> None:
    with postgres_runtime_sessions() as session:
        owner = _add_user(session, "pg_source_owner")
        source, version_one = _add_source_version(session, owner, "Persisted source text")
        version_two = SourceVersion(
            source_id=source.id,
            version_number=2,
            source_text="Second source version",
            content_hash=source_content_hash("Second source version"),
        )
        first_segment = SourceSegment(
            source_version_id=version_one.id,
            ordinal=1,
            locator="paragraph:1",
            segment_text="Persisted source text",
        )
        session.add_all([version_two, first_segment])
        session.commit()
        source_id = source.id
        version_one_id = version_one.id
        owner_id = owner.id

        session.add(
            SourceVersion(
                source_id=source_id,
                version_number=2,
                source_text="Duplicate version",
                content_hash=source_content_hash("Duplicate version"),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(
            SourceSegment(
                source_version_id=version_one_id,
                ordinal=1,
                locator="paragraph:2",
                segment_text="Duplicate ordinal",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    with postgres_runtime_sessions() as reader:
        source, version = reader.execute(
            select(Source, SourceVersion)
            .join(SourceVersion, SourceVersion.source_id == Source.id)
            .where(Source.id == source_id, SourceVersion.id == version_one_id)
        ).one()
        assert source.owner_id == owner_id
        assert version.source_id == source.id
        assert version.source_text == "Persisted source text"
        assert version.content_hash == source_content_hash(version.source_text)
        segment = reader.scalar(
            select(SourceSegment).where(
                SourceSegment.source_version_id == version.id,
                SourceSegment.ordinal == 1,
            )
        )
        assert segment is not None
        assert segment.locator == "paragraph:1"
        assert segment.segment_text == "Persisted source text"


def test_postgres_runtime_transformation_and_artifact_history(
    postgres_runtime_sessions: sessionmaker[Session],
) -> None:
    with postgres_runtime_sessions() as session:
        owner = _add_user(session, "pg_artifact_owner")
        _source, source_version = _add_source_version(session, owner)
        transformation = _add_transformation(session, owner, source_version)
        artifact_run = ArtifactRun(
            transformation_run_id=transformation.id,
            output_type="executive_summary",
            status="succeeded",
        )
        session.add(artifact_run)
        session.flush()
        artifact_version = ArtifactVersion(
            artifact_run_id=artifact_run.id,
            version_number=1,
            source_version_id=source_version.id,
            content="A saved summary.",
            provider="test-provider",
            model="test-model",
            prompt_version="prompt-v3",
            prompt_hash="c" * 64,
        )
        session.add(artifact_version)
        session.commit()
        transformation_id = transformation.id
        artifact_run_id = artifact_run.id
        artifact_version_id = artifact_version.id
        source_version_id = source_version.id

        session.add(
            ArtifactVersion(
                artifact_run_id=artifact_run_id,
                version_number=1,
                source_version_id=source_version_id,
                content="Duplicate artifact version.",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    with postgres_runtime_sessions() as reader:
        persisted_transformation = reader.get(TransformationRun, transformation_id)
        persisted_run = reader.get(ArtifactRun, artifact_run_id)
        persisted_version = reader.get(ArtifactVersion, artifact_version_id)
        assert persisted_transformation is not None
        assert persisted_run is not None
        assert persisted_version is not None
        assert persisted_transformation.selected_output_types == [
            "executive_summary",
            "advisory",
        ]
        assert persisted_run.transformation_run_id == persisted_transformation.id
        assert persisted_version.artifact_run_id == persisted_run.id
        assert persisted_version.source_version_id == persisted_transformation.source_version_id
        assert persisted_version.provider == "test-provider"
        assert persisted_version.model == "test-model"
        assert persisted_version.prompt_version == "prompt-v3"
        assert persisted_version.prompt_hash == "c" * 64


def test_postgres_runtime_timestamps_are_aware_and_preserve_instants(
    postgres_runtime_sessions: sessionmaker[Session],
) -> None:
    expected_created_at = datetime.now(UTC).replace(microsecond=456789)
    expected_expires_at = expected_created_at + timedelta(hours=1)
    with postgres_runtime_sessions() as session:
        user = User(
            username="pg_timestamp",
            password_hash="!disabled-test!",
            created_at=expected_created_at,
        )
        session.add(user)
        session.flush()
        auth_session = AuthSession(
            user_id=user.id,
            session_token_digest="d" * 64,
            expires_at=expected_expires_at,
            created_at=expected_created_at,
        )
        session.add(auth_session)
        session.commit()
        user_id = user.id
        auth_session_id = auth_session.id

    with postgres_runtime_sessions() as reader:
        persisted_user = reader.get(User, user_id)
        persisted_session = reader.get(AuthSession, auth_session_id)
        assert persisted_user is not None
        assert persisted_session is not None
        assert persisted_user.created_at.tzinfo is not None
        assert persisted_session.created_at.tzinfo is not None
        assert persisted_session.expires_at.tzinfo is not None
        assert persisted_user.created_at.astimezone(UTC) == expected_created_at
        assert persisted_session.created_at.astimezone(UTC) == expected_created_at
        assert persisted_session.expires_at.astimezone(UTC) == expected_expires_at
        assert persisted_session.expires_at > persisted_session.created_at


def test_postgres_runtime_rolled_back_write_does_not_persist_and_later_commit_succeeds(
    postgres_runtime_sessions: sessionmaker[Session],
) -> None:
    with postgres_runtime_sessions() as session:
        session.add(User(username="pg_rolled_back", password_hash="!disabled-test!"))
        session.rollback()

        with postgres_runtime_sessions() as reader:
            assert reader.scalar(select(User.id).where(User.username == "pg_rolled_back")) is None

        valid_user = User(username="pg_after_rollback", password_hash="!disabled-test!")
        session.add(valid_user)
        session.commit()

    with postgres_runtime_sessions() as reader:
        persisted_user_id = reader.scalar(
            select(User.id).where(User.username == "pg_after_rollback")
        )
        assert persisted_user_id is not None
