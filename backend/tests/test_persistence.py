from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import inspect, select, text
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
    ContextManifest,
    ContextManifestEntry,
    Job,
    JobAttempt,
    Source,
    SourceAsset,
    SourcePack,
    SourcePackMembership,
    SourcePackVersion,
    SourceRegion,
    SourceSegment,
    SourceVersion,
    TransformationRun,
    User,
    source_content_hash,
    utc_now,
)
from app.source_versions import create_source_version

BACKEND_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TABLES = {
    "users",
    "auth_sessions",
    "sources",
    "source_versions",
    "source_segments",
    "source_packs",
    "source_pack_versions",
    "source_pack_memberships",
    "source_assets",
    "source_regions",
    "transformation_runs",
    "artifact_runs",
    "artifact_versions",
    "jobs",
    "job_dependencies",
    "job_attempts",
    "evidence_links",
    "discrepancy_findings",
    "login_throttles",
    "knowledge_assertions",
    "knowledge_relations",
    "claim_scans",
    "claim_batches",
    "material_claims",
    "context_manifests",
    "context_manifest_entries",
    "text_embedding_profiles",
    "region_embeddings",
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
    source_version = create_source_version(session, source, source_text)
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
        assert revision == "f2c6a19b5d40"
        asset_columns = {
            column["name"]: column for column in inspector.get_columns("source_assets")
        }
        assert asset_columns["extraction_profile"]["nullable"] is False
        assert asset_columns["extraction_profile_version"]["nullable"] is False
        assert asset_columns["extraction_coverage"]["nullable"] is False
        region_columns = {
            column["name"]: column for column in inspector.get_columns("source_regions")
        }
        assert region_columns["source_segment_id"]["nullable"] is True
        assert region_columns["text"]["nullable"] is True
    finally:
        engine.dispose()


def test_durable_jobs_migration_preserves_populated_current_sqlite_data(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'populated-current.sqlite3').as_posix()}"
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "a17c0f5e2d91")

    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        owner = User(username="durable_migration_owner", password_hash="!disabled!")
        session.add(owner)
        session.flush()
        source = Source(owner_id=owner.id, title="Existing source")
        session.add(source)
        session.flush()
        source_version = create_source_version(session, source, "Existing source text")
        source_pack = session.scalar(select(SourcePack).where(SourcePack.source_id == source.id))
        assert source_pack is not None
        transformation = _make_transformation(session, owner, source_version)
        artifact_run = ArtifactRun(
            transformation_run_id=transformation.id,
            output_type="advisory",
            status="succeeded",
        )
        session.add(artifact_run)
        session.flush()
        artifact_version_id = session.scalar(
            text(
                "INSERT INTO artifact_versions "
                "(artifact_run_id, version_number, source_version_id, content, "
                "review_status, created_at) "
                "VALUES (:run_id, 1, :source_id, 'Existing immutable artifact.', "
                "'draft', CURRENT_TIMESTAMP) RETURNING id"
            ),
            {"run_id": artifact_run.id, "source_id": source_version.id},
        )
        assert artifact_version_id is not None
        session.commit()
        source_version_id = source_version.id
        source_pack_id = source_pack.id
        artifact_run_id = artifact_run.id
    engine.dispose()

    command.upgrade(config, "head")
    upgraded_engine = create_database_engine(database_url)
    upgraded_factory = create_session_factory(upgraded_engine)
    try:
        with upgraded_factory() as session:
            assert session.get(SourceVersion, source_version_id) is not None
            assert session.get(SourcePack, source_pack_id) is not None
            assert session.get(ArtifactRun, artifact_run_id) is not None
            preserved_version = session.get(ArtifactVersion, artifact_version_id)
            assert preserved_version is not None
            assert preserved_version.content == "Existing immutable artifact."
            assert list(session.scalars(select(Job))) == []
            assert list(session.scalars(select(JobAttempt))) == []
    finally:
        upgraded_engine.dispose()


def test_phase_two_sqlite_migration_enforces_context_manifest_immutability(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'phase-two-immutable.sqlite3').as_posix()}"
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    try:
        with factory() as session:
            owner = User(username="sqlite_manifest_owner", password_hash="!disabled!")
            session.add(owner)
            session.flush()
            source = Source(owner_id=owner.id, title="Immutable source")
            session.add(source)
            session.flush()
            source_version = create_source_version(session, source, "Immutable source text.")
            pack_version = session.scalar(
                select(SourcePackVersion).where(
                    SourcePackVersion.source_version_id == source_version.id
                )
            )
            assert pack_version is not None
            pack = session.get(SourcePack, pack_version.source_pack_id)
            membership = session.scalar(
                select(SourcePackMembership).where(
                    SourcePackMembership.source_pack_version_id == pack_version.id
                )
            )
            assert pack is not None and membership is not None
            asset = session.get(SourceAsset, membership.source_asset_id)
            region = session.scalar(
                select(SourceRegion).where(
                    SourceRegion.source_asset_id == membership.source_asset_id
                )
            )
            assert asset is not None and region is not None and region.text is not None
            manifest = ContextManifest(
                owner_id=owner.id,
                source_pack_id=pack.id,
                source_pack_version_id=pack_version.id,
                source_version_id=source_version.id,
                task_class="artifact_generation",
                artifact_family="advisory",
                route="R0_FULL_CONTEXT",
                context_profile="r0_full_context",
                context_profile_version=1,
                query_construction_version=1,
                budget_policy_version="context-chars-v1",
                estimation_method="unicode-codepoint-count-v1",
                context_budget_units=20_000,
                available_input_budget=25_000,
                estimated_context_units=len(region.text),
                reserved_margin=5_000,
                extraction_coverage="complete",
                state="ready",
                warnings=[],
                created_at=utc_now(),
            )
            session.add(manifest)
            session.flush()
            entry = ContextManifestEntry(
                context_manifest_id=manifest.id,
                source_region_id=region.id,
                source_asset_id=asset.id,
                membership_id=membership.id,
                role="PRIMARY",
                selected=True,
                locator=region.locator,
                content_hash=sha256(region.text.encode("utf-8")).hexdigest(),
                estimated_context_units=len(region.text),
                reason="r0_all_eligible_factual_regions",
                profile_metadata={"profile": "r0_full_context", "version": 1},
            )
            session.add(entry)
            session.commit()

            with pytest.raises(IntegrityError, match="Context manifests are immutable"):
                session.execute(
                    text("UPDATE context_manifests SET route = 'R1' WHERE id = :id"),
                    {"id": manifest.id},
                )
                session.commit()
            session.rollback()
            with pytest.raises(IntegrityError, match="Context manifests are immutable"):
                session.execute(
                    text("UPDATE context_manifest_entries SET locator = 'changed' WHERE id = :id"),
                    {"id": entry.id},
                )
                session.commit()
            session.rollback()
    finally:
        engine.dispose()


def test_extraction_contract_backfill_marks_only_known_methods_complete(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'extraction-contract.sqlite3').as_posix()}"
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "e8a62c0916df")
    engine = create_database_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, username, password_hash, created_at) "
                    "VALUES (17, 'extraction_backfill', '!disabled-test!', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO sources (id, owner_id, title, created_at) "
                    "VALUES (18, 17, 'Extraction backfill', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO source_versions "
                    "(id, source_id, version_number, source_text, content_hash, created_at) "
                    "VALUES (19, 18, 1, 'Known text.', :content_hash, CURRENT_TIMESTAMP)"
                ),
                {"content_hash": source_content_hash("Known text.")},
            )
            connection.execute(
                text(
                    "INSERT INTO source_packs (id, source_id, owner_id, title, created_at) "
                    "VALUES (20, 18, 17, 'Extraction backfill', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO source_pack_versions "
                    "(id, source_pack_id, source_version_id, version_number, content_hash, "
                    "created_at) VALUES (21, 20, 19, 1, :content_hash, CURRENT_TIMESTAMP)"
                ),
                {"content_hash": source_content_hash("Known text.")},
            )
            connection.execute(
                text(
                    "INSERT INTO source_assets "
                    "(id, source_pack_version_id, authority_role, source_kind, media_type, "
                    "byte_size, content_hash, extraction_method, created_at) VALUES "
                    "(22, 21, 'authoritative', 'text', 'text/plain', 11, :content_hash, "
                    "'pasted_text', CURRENT_TIMESTAMP), "
                    "(23, 21, 'authoritative', 'text', 'text/plain', 11, :content_hash, "
                    "'unknown_test_method', CURRENT_TIMESTAMP)"
                ),
                {"content_hash": source_content_hash("Known text.")},
            )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            assets = (
                connection.execute(
                    text(
                        "SELECT extraction_method, extraction_profile, "
                        "extraction_profile_version, extraction_coverage "
                        "FROM source_assets ORDER BY id"
                    )
                )
                .mappings()
                .all()
            )

        assert [(asset["extraction_method"], asset["extraction_coverage"]) for asset in assets] == [
            ("pasted_text", "complete"),
            ("unknown_test_method", "partial"),
        ]
        assert [
            (asset["extraction_profile"], asset["extraction_profile_version"]) for asset in assets
        ] == [
            ("text", 1),
            ("text", 1),
        ]
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
            assert (
                connection.scalar(text("SELECT owner_id FROM source_packs WHERE source_id = 1"))
                == 41
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT authority_role FROM source_assets WHERE source_pack_version_id = 1"
                    )
                )
                == "authoritative"
            )
            assert (
                connection.scalar(
                    text("SELECT storage_key FROM source_assets WHERE source_pack_version_id = 1")
                )
                is None
            )
    finally:
        engine.dispose()


def test_phase_one_a_source_pack_backfill_preserves_versions_segments_and_run(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'phase1a.sqlite3').as_posix()}"
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "c2a7e18f4d91")
    engine = create_database_engine(database_url)
    v1_text = "# Start\n\nFirst body."
    v2_text = "# Start\n\nRevised body."
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, username, password_hash, created_at) "
                    "VALUES (7, 'phase1a_user', '!disabled-test!', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO sources (id, owner_id, title, created_at) "
                    "VALUES (12, 7, 'Field report', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO source_versions "
                    "(id, source_id, version_number, source_text, content_hash, created_at) "
                    "VALUES (21, 12, 1, :source_text, :content_hash, CURRENT_TIMESTAMP)"
                ),
                {"source_text": v1_text, "content_hash": source_content_hash(v1_text)},
            )
            connection.execute(
                text(
                    "INSERT INTO source_versions "
                    "(id, source_id, parent_source_version_id, version_number, source_text, "
                    "content_hash, created_at) "
                    "VALUES (22, 12, 21, 2, :source_text, :content_hash, CURRENT_TIMESTAMP)"
                ),
                {"source_text": v2_text, "content_hash": source_content_hash(v2_text)},
            )
            connection.execute(
                text(
                    "INSERT INTO source_segments "
                    "(id, source_version_id, ordinal, locator, segment_text) VALUES "
                    "(31, 21, 1, 'heading:1', '# Start'), "
                    "(32, 21, 2, 'paragraph:1', 'First body.'), "
                    "(33, 22, 1, 'heading:1', '# Start'), "
                    "(34, 22, 2, 'paragraph:1', 'Revised body.')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO transformation_runs "
                    "(id, owner_id, source_version_id, supporting_context, audience, tone, "
                    "language, detail_level, objective, style, selected_output_types, created_at) "
                    "VALUES (41, 7, 22, '', 'Public', 'Clear', 'English', 'standard', 'Inform', "
                    "'Plain', '[\"executive_summary\"]', CURRENT_TIMESTAMP)"
                )
            )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            pack = (
                connection.execute(text("SELECT id, source_id, owner_id, title FROM source_packs"))
                .mappings()
                .one()
            )
            pack_versions = (
                connection.execute(
                    text(
                        "SELECT id, source_version_id, parent_source_pack_version_id, "
                        "version_number, content_hash FROM source_pack_versions "
                        "ORDER BY version_number"
                    )
                )
                .mappings()
                .all()
            )
            assets = (
                connection.execute(
                    text(
                        "SELECT id, source_pack_version_id, authority_role, source_kind, "
                        "content_hash, "
                        "storage_key, extraction_method, extraction_profile, "
                        "extraction_profile_version, extraction_coverage "
                        "FROM source_assets ORDER BY id"
                    )
                )
                .mappings()
                .all()
            )
            memberships = (
                connection.execute(
                    text(
                        "SELECT source_pack_version_id, source_version_id, source_asset_id, "
                        "ordinal, role FROM source_pack_memberships ORDER BY source_pack_version_id"
                    )
                )
                .mappings()
                .all()
            )
            regions = (
                connection.execute(
                    text(
                        "SELECT source_segment_id, ordinal, locator, region_type, text "
                        "FROM source_regions ORDER BY source_segment_id"
                    )
                )
                .mappings()
                .all()
            )
            references = connection.execute(
                text(
                    "SELECT transformation_runs.source_version_id, source_versions.id "
                    "FROM transformation_runs JOIN source_versions "
                    "ON source_versions.id = transformation_runs.source_version_id WHERE "
                    "transformation_runs.id = 41"
                )
            ).one()

        assert (pack["source_id"], pack["owner_id"], pack["title"]) == (12, 7, "Field report")
        assert [item["source_version_id"] for item in pack_versions] == [21, 22]
        assert pack_versions[0]["parent_source_pack_version_id"] is None
        assert pack_versions[1]["parent_source_pack_version_id"] == pack_versions[0]["id"]
        assert [item["content_hash"] for item in pack_versions] == [
            source_content_hash(v1_text),
            source_content_hash(v2_text),
        ]
        assert [item["authority_role"] for item in assets] == ["authoritative", "authoritative"]
        assert [
            (
                item["source_version_id"],
                item["source_asset_id"],
                item["ordinal"],
                item["role"],
            )
            for item in memberships
        ] == [(21, assets[0]["id"], 1, "PRIMARY"), (22, assets[1]["id"], 1, "PRIMARY")]
        assert [item["source_kind"] for item in assets] == ["text", "text"]
        assert [item["extraction_profile"] for item in assets] == ["text", "text"]
        assert [item["extraction_profile_version"] for item in assets] == [1, 1]
        assert [item["extraction_coverage"] for item in assets] == ["complete", "complete"]
        assert [item["storage_key"] for item in assets] == [None, None]
        assert [item["content_hash"] for item in assets] == [
            source_content_hash(v1_text),
            source_content_hash(v2_text),
        ]
        assert [item["source_segment_id"] for item in regions] == [31, 32, 33, 34]
        assert [item["locator"] for item in regions] == [
            "heading:1",
            "paragraph:1",
            "heading:1",
            "paragraph:1",
        ]
        assert [item["text"] for item in regions] == [
            "# Start",
            "First body.",
            "# Start",
            "Revised body.",
        ]
        assert references == (22, 22)
    finally:
        engine.dispose()


def test_source_pack_migration_rejects_cross_source_parent_before_schema_changes(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'invalid-lineage.sqlite3').as_posix()}"
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "c2a7e18f4d91")
    engine = create_database_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, username, password_hash, created_at) "
                    "VALUES (17, 'lineage_user', '!disabled-test!', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO sources (id, owner_id, created_at) VALUES "
                    "(18, 17, CURRENT_TIMESTAMP), (19, 17, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO source_versions "
                    "(id, source_id, version_number, source_text, content_hash, created_at) "
                    "VALUES (20, 18, 1, 'First', :hash, CURRENT_TIMESTAMP)"
                ),
                {"hash": source_content_hash("First")},
            )
            connection.execute(
                text(
                    "INSERT INTO source_versions "
                    "(id, source_id, parent_source_version_id, version_number, source_text, "
                    "content_hash, created_at) "
                    "VALUES (21, 19, 20, 1, 'Other source', :hash, CURRENT_TIMESTAMP)"
                ),
                {"hash": source_content_hash("Other source")},
            )

        with pytest.raises(RuntimeError, match="parent lineage"):
            command.upgrade(config, "head")
        assert "source_packs" not in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "c2a7e18f4d91"
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
                    "VALUES (52, 'legacy-migrated-52', "
                    "'!disabled-legacy-google!', CURRENT_TIMESTAMP)"
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
            source_text = connection.scalar(
                text("SELECT source_text FROM source_versions WHERE id = 9")
            )
            assert source_text == "preserved text"
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
