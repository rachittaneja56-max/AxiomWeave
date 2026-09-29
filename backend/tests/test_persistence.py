from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.database import create_database_engine, create_session_factory
from app.models import (
    ArtifactRun,
    ArtifactVersion,
    AuthSession,
    Base,
    Source,
    SourceSegment,
    SourceVersion,
    TransformationRun,
    User,
    source_content_hash,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TABLES = {
    "users",
    "auth_sessions",
    "sources",
    "source_versions",
    "source_segments",
    "transformation_runs",
    "artifact_runs",
    "artifact_versions",
    "evidence_links",
    "discrepancy_findings",
    "login_throttles",
}


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Engine]:
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'test.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _session(engine: Engine) -> Session:
    return create_session_factory(engine)()


def _make_source(
    session: Session, owner: User, source_text: str = "Source V1"
) -> tuple[Source, SourceVersion]:
    source = Source(owner_id=owner.id, title="Briefing")
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


def _make_transformation(
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


def test_migration_from_empty_database_and_repeated_upgrade(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.sqlite3"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    engine = create_database_engine(database_url)
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == EXPECTED_TABLES | {"alembic_version"}
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == "c2a7e18f4d91"
    finally:
        engine.dispose()


def test_auth_migration_preserves_legacy_user_and_owned_rows(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'legacy.sqlite3').as_posix()}"
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "f0ba32d0f7a1")
    engine = create_database_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, google_subject, created_at) "
                    "VALUES (41, 'legacy-subject', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO auth_sessions "
                    "(user_id, session_token_digest, expires_at, created_at) "
                    "VALUES (41, :digest, :expiry, CURRENT_TIMESTAMP)"
                ),
                {"digest": "d" * 64, "expiry": "2099-01-01"},
            )
            connection.execute(
                text(
                    "INSERT INTO sources (owner_id, title, created_at) "
                    "VALUES (41, 'saved source', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO source_versions "
                    "(source_id, version_number, source_text, content_hash, created_at) "
                    "VALUES (1, 1, 'saved text', :hash, CURRENT_TIMESTAMP)"
                ),
                {"hash": "e" * 64},
            )
            connection.execute(
                text(
                    "INSERT INTO transformation_runs "
                    "(owner_id, source_version_id, supporting_context, audience, tone, language, "
                    "detail_level, objective, style, selected_output_types, created_at) "
                    "VALUES (41, 1, '', 'Public', 'Clear', 'English', 'standard', 'Inform', "
                    "'Plain', '[]', CURRENT_TIMESTAMP)"
                )
            )
        command.upgrade(config, "head")
        inspector = inspect(engine)
        assert "google_subject" not in {column["name"] for column in inspector.get_columns("users")}
        with engine.connect() as connection:
            user = connection.execute(
                text("SELECT id, username, password_hash FROM users WHERE id = 41")
            ).one()
            assert user.id == 41
            assert user.username == "legacy-migrated-41"
            assert user.password_hash == "!disabled-legacy-google!"
            assert connection.scalar(text("SELECT owner_id FROM sources WHERE id = 1")) == 41
            assert (
                connection.scalar(text("SELECT owner_id FROM transformation_runs WHERE id = 1"))
                == 41
            )
            assert connection.scalar(text("SELECT user_id FROM auth_sessions WHERE id = 1")) == 41
            assert (
                connection.scalar(text("SELECT revoked_at FROM auth_sessions WHERE id = 1"))
                is not None
            )
    finally:
        engine.dispose()


def test_password_cutover_revokes_existing_sessions_without_deleting_owned_data(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'cutover.sqlite3').as_posix()}"
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "b745f01c6d52")
    engine = create_database_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, username, password_hash, created_at) "
                    "VALUES (52, 'legacy-migrated-52', '!disabled-legacy-google!', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO auth_sessions "
                    "(id, user_id, session_token_digest, expires_at, revoked_at, created_at) "
                    "VALUES "
                    "(1, 52, :active_digest, :expiry, NULL, CURRENT_TIMESTAMP), "
                    "(2, 52, :revoked_digest, :expiry, :revoked_at, CURRENT_TIMESTAMP)"
                ),
                {
                    "active_digest": "a" * 64,
                    "revoked_digest": "b" * 64,
                    "expiry": "2099-01-01",
                    "revoked_at": "2026-01-01 00:00:00",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO sources (id, owner_id, title, created_at) "
                    "VALUES (7, 52, 'preserved source', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO source_versions "
                    "(id, source_id, version_number, source_text, content_hash, created_at) "
                    "VALUES (9, 7, 1, 'preserved text', :hash, CURRENT_TIMESTAMP)"
                ),
                {"hash": "c" * 64},
            )
            connection.execute(
                text(
                    "INSERT INTO transformation_runs "
                    "(id, owner_id, source_version_id, supporting_context, audience, tone, "
                    "language, detail_level, objective, style, selected_output_types, created_at) "
                    "VALUES (11, 52, 9, '', 'Public', 'Clear', 'English', 'standard', "
                    "'Inform', 'Plain', '[]', CURRENT_TIMESTAMP)"
                )
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            sessions = connection.execute(
                text("SELECT id, revoked_at FROM auth_sessions ORDER BY id")
            ).all()
            assert sessions[0].revoked_at is not None
            assert str(sessions[1].revoked_at).startswith("2026-01-01")
            assert connection.scalar(text("SELECT id FROM users WHERE id = 52")) == 52
            assert connection.scalar(text("SELECT owner_id FROM sources WHERE id = 7")) == 52
            assert (
                connection.scalar(text("SELECT owner_id FROM transformation_runs WHERE id = 11"))
                == 52
            )
            assert connection.scalar(text("SELECT source_text FROM source_versions WHERE id = 9")) == (
                "preserved text"
            )
    finally:
        engine.dispose()


def test_owner_session_and_foreign_key_invariants(database: Engine) -> None:
    session = _session(database)
    user = User(username="test_user1", password_hash="!disabled-test!")
    session.add(user)
    session.commit()

    with database.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
    session.add(
        AuthSession(
            user_id=user.id,
            session_token_digest="a" * 64,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    session.commit()
    source, source_version = _make_source(session, user)
    session.commit()
    assert source.owner_id == user.id
    assert source_version.source_id == source.id
    assert "session_token_digest" in AuthSession.__table__.columns
    assert "token" not in AuthSession.__table__.columns
    assert "raw_token" not in AuthSession.__table__.columns

    session.add(User(username="test_user1", password_hash="!disabled-test!"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    session.add(
        AuthSession(
            user_id=9999,
            session_token_digest="b" * 64,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.close()


def test_source_versions_and_segments_preserve_history_and_locators(database: Engine) -> None:
    session = _session(database)
    user = User(username="test_user3", password_hash="!disabled-test!")
    session.add(user)
    session.flush()
    source, version_one = _make_source(session, user, "Same content")
    version_two = SourceVersion(
        source_id=source.id,
        version_number=2,
        source_text="Source V2",
        content_hash=source_content_hash("Source V2"),
    )
    other_source = Source(owner_id=user.id)
    session.add_all([version_two, other_source])
    session.flush()
    # Identical content hashes across different source records are permitted.
    session.add(
        SourceVersion(
            source_id=other_source.id,
            version_number=1,
            source_text=version_one.source_text,
            content_hash=version_one.content_hash,
        )
    )
    session.add(
        SourceSegment(
            source_version_id=version_one.id,
            ordinal=1,
            locator="paragraph:1",
            segment_text="Same content",
        )
    )
    session.commit()

    session.add(
        SourceVersion(
            source_id=source.id,
            version_number=2,
            source_text="Duplicate version number",
            content_hash=source_content_hash("Duplicate version number"),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    session.add(
        SourceSegment(
            source_version_id=version_one.id,
            ordinal=1,
            locator="paragraph:2",
            segment_text="Duplicate ordinal",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.close()


def test_transformation_and_artifact_history_keep_context_and_provenance(database: Engine) -> None:
    session = _session(database)
    user = User(username="test_user4", password_hash="!disabled-test!")
    session.add(user)
    session.flush()
    _source, source_version = _make_source(session, user, "Authoritative source text")
    transformation = _make_transformation(session, user, source_version)
    first_run = ArtifactRun(
        transformation_run_id=transformation.id,
        output_type="executive_summary",
        status="succeeded",
    )
    second_run = ArtifactRun(
        transformation_run_id=transformation.id,
        output_type="advisory",
        status="pending",
    )
    session.add_all([first_run, second_run])
    session.flush()
    first_version = ArtifactVersion(
        artifact_run_id=first_run.id,
        version_number=1,
        source_version_id=source_version.id,
        content="Draft one",
        provider="test-provider",
        model="test-model",
        prompt_version="v1",
        prompt_hash="c" * 64,
    )
    second_version = ArtifactVersion(
        artifact_run_id=first_run.id,
        version_number=2,
        source_version_id=source_version.id,
        content="Edited draft",
    )
    session.add_all([first_version, second_version])
    session.commit()

    assert transformation.source_version_id == source_version.id
    assert transformation.supporting_context != source_version.source_text
    assert transformation.selected_output_types == ["executive_summary", "advisory"]
    assert first_run.transformation_run_id == second_run.transformation_run_id
    assert first_version.provider == "test-provider"
    assert first_version.model == "test-model"
    assert first_version.prompt_version == "v1"
    assert second_version.provider is None

    session.add(
        ArtifactVersion(
            artifact_run_id=first_run.id,
            version_number=2,
            source_version_id=source_version.id,
            content="Duplicate artifact version number",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.close()
