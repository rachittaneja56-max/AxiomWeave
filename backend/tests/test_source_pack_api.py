import os
import stat
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from auth_support import login
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.main import app
from app.models import (
    Source,
    SourceAsset,
    SourcePack,
    SourcePackMembership,
    SourcePackVersion,
    SourceRegion,
    SourceVersion,
    User,
)
from app.private_asset_storage import (
    MAX_PRIVATE_ASSET_BYTES,
    AssetStorageError,
    LocalPrivateAssetStore,
    StoredPrivateAsset,
)
from app.source_roles import source_role_policy, validate_source_role
from app.source_versions import (
    SourcePackMembershipInput,
    create_source_pack_version,
    safe_original_filename,
    segment_source_text,
)
from app.url_import import URLImportResult


def _transformation_request(
    source_text: str, source_version_id: int | None = None
) -> dict[str, object]:
    request: dict[str, object] = {
        "source_text": source_text,
        "output_types": ["executive_summary"],
        "audience": "General public",
        "tone": "Clear",
        "language": "English",
        "detail_level": "standard",
        "objective": "Inform the audience",
        "style": "Plain language",
        "supporting_context": "",
    }
    if source_version_id is not None:
        request["source_version_id"] = source_version_id
    return request


def test_pasted_transformation_creates_inspectable_pack_and_regions(
    authorized_client: TestClient,
) -> None:
    source_text = "# Update\n\nThe program opens on Friday."
    saved = authorized_client.post(
        "/api/transformations", json=_transformation_request(source_text)
    )
    assert saved.status_code == 200
    pack = authorized_client.get(
        f"/api/transformations/{saved.json()['transformation_run_id']}/source-pack"
    )

    assert pack.status_code == 200
    version = pack.json()["versions"][0]
    asset = version["assets"][0]
    assert version["version_number"] == 1
    assert version["source_version_id"] == saved.json()["source_version"]["id"]
    assert version["content_hash"] == saved.json()["source_version"]["content_hash"]
    assert version["memberships"][0]["role"] == "PRIMARY"
    assert version["memberships"][0]["source_version_id"] == version["source_version_id"]
    assert asset["source_kind"] == "text"
    assert asset["original_filename"] is None
    assert asset["content_hash"] == sha256(source_text.encode("utf-8")).hexdigest()
    assert [region["locator"] for region in asset["regions"]] == [
        "heading:1",
        "paragraph:1",
    ]
    assert [region["text"] for region in asset["regions"]] == [
        "# Update",
        "The program opens on Friday.",
    ]
    assert all(region["source_segment_id"] is not None for region in asset["regions"])
    assert asset["extraction_profile"] == "text"
    assert asset["extraction_profile_version"] == 1
    assert asset["extraction_coverage"] == "complete"
    assert "storage_key" not in asset


def test_source_pack_inspects_partial_coverage_and_region_without_legacy_segment(
    authorized_client: TestClient,
    auth_database: tuple[TestClient, object, sessionmaker[Session]],
) -> None:
    _client, _engine, factory = auth_database
    saved = authorized_client.post(
        "/api/transformations", json=_transformation_request("Text with partial coverage.")
    )
    assert saved.status_code == 200

    with factory() as session:
        asset = session.scalar(select(SourceAsset))
        assert asset is not None
        asset.extraction_coverage = "partial"
        session.add(
            SourceRegion(
                source_asset_id=asset.id,
                source_segment_id=None,
                ordinal=2,
                locator="region:2",
                region_type="attachment",
                page_number=None,
                text=None,
            )
        )
        session.commit()

    response = authorized_client.get(
        f"/api/transformations/{saved.json()['transformation_run_id']}/source-pack"
    )
    assert response.status_code == 200
    asset_view = response.json()["versions"][0]["assets"][0]
    assert asset_view["extraction_coverage"] == "partial"
    assert asset_view["extraction_profile"] == "text"
    unprojected_region = next(
        region for region in asset_view["regions"] if region["source_segment_id"] is None
    )
    assert unprojected_region["locator"] == "region:2"
    assert unprojected_region["text"] is None


def test_file_upload_retains_private_bytes_and_reuses_legacy_projection(
    authorized_client: TestClient,
    auth_database: tuple[TestClient, object, sessionmaker[Session]],
) -> None:
    _client, _engine, factory = auth_database
    content = b"# Confidential\n\nThe public meeting is on Tuesday."
    uploaded = authorized_client.post(
        "/api/sources/file",
        files={"file": ("../../private.txt", content, "text/plain")},
    )
    assert uploaded.status_code == 200
    upload_body = uploaded.json()
    assert upload_body["source_version_id"] > 0
    saved = authorized_client.post(
        "/api/transformations",
        json=_transformation_request(upload_body["source_text"], upload_body["source_version_id"]),
    )
    assert saved.status_code == 200
    assert saved.json()["source_version"]["id"] == upload_body["source_version_id"]

    with factory() as session:
        version = session.scalar(
            select(SourceVersion).where(SourceVersion.id == upload_body["source_version_id"])
        )
        assert version is not None
        pack_version = session.scalar(
            select(SourcePackVersion).where(SourcePackVersion.source_version_id == version.id)
        )
        assert pack_version is not None
        asset = session.scalar(
            select(SourceAsset).where(SourceAsset.source_pack_version_id == pack_version.id)
        )
        assert asset is not None
        assert asset.storage_key is not None
        assert asset.content_hash == sha256(content).hexdigest()
        assert asset.byte_size == len(content)
        assert asset.original_filename == "private.txt"
        store = LocalPrivateAssetStore(Path(os.environ["SIH_PRIVATE_ASSET_DIR"]))
        assert store.read(asset.storage_key) == content

    pack = authorized_client.get(
        f"/api/transformations/{saved.json()['transformation_run_id']}/source-pack"
    )
    returned_asset = pack.json()["versions"][0]["memberships"][0]["asset"]
    assert returned_asset["content_hash"] == sha256(content).hexdigest()
    assert "storage_key" not in returned_asset


def test_editing_uploaded_text_appends_pack_version_and_preserves_file_version(
    authorized_client: TestClient,
    auth_database: tuple[TestClient, object, sessionmaker[Session]],
) -> None:
    _client, _engine, factory = auth_database
    content = b"Original upload text."
    upload = authorized_client.post(
        "/api/sources/file", files={"file": ("source.txt", content, "text/plain")}
    )
    assert upload.status_code == 200
    edited_text = "Original upload text, corrected."
    saved = authorized_client.post(
        "/api/transformations",
        json=_transformation_request(edited_text, upload.json()["source_version_id"]),
    )
    assert saved.status_code == 200
    assert saved.json()["source_version"]["version_number"] == 2

    with factory() as session:
        versions = list(
            session.scalars(select(SourceVersion).order_by(SourceVersion.version_number)).all()
        )
        assert len(versions) == 2
        assert versions[0].source_text == "Original upload text."
        assert versions[1].source_text == edited_text
        assert versions[1].parent_source_version_id == versions[0].id
        pack_id = session.scalar(
            select(SourcePack.id).where(SourcePack.source_id == upload.json()["source_id"])
        )
        assert pack_id is not None
        pack_versions = list(
            session.scalars(
                select(SourcePackVersion)
                .where(SourcePackVersion.source_pack_id == pack_id)
                .order_by(SourcePackVersion.version_number)
            ).all()
        )
        assert [version.version_number for version in pack_versions] == [1, 2]
        assert pack_versions[1].parent_source_pack_version_id == pack_versions[0].id
        first_asset = session.scalar(
            select(SourceAsset).where(SourceAsset.source_pack_version_id == pack_versions[0].id)
        )
        second_asset = session.scalar(
            select(SourceAsset).where(SourceAsset.source_pack_version_id == pack_versions[1].id)
        )
        assert first_asset is not None and first_asset.source_kind == "file"
        assert first_asset.content_hash == sha256(content).hexdigest()
        assert second_asset is not None and second_asset.source_kind == "text"
        assert second_asset.extraction_method == "manual_revision"


def test_pdf_regions_keep_page_locators_and_page_numbers(authorized_client: TestClient) -> None:
    import pymupdf

    pdf: Any = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "A report paragraph with enough readable text for extraction.")
    content = pdf.tobytes()
    pdf.close()
    uploaded = authorized_client.post(
        "/api/sources/file", files={"file": ("report.pdf", content, "application/pdf")}
    )
    assert uploaded.status_code == 200
    saved = authorized_client.post(
        "/api/transformations",
        json=_transformation_request(
            uploaded.json()["source_text"], uploaded.json()["source_version_id"]
        ),
    )
    pack = authorized_client.get(
        f"/api/transformations/{saved.json()['transformation_run_id']}/source-pack"
    )
    regions = pack.json()["versions"][0]["memberships"][0]["asset"]["regions"]
    assert regions[0]["locator"] == "page:1"
    assert regions[0]["region_type"] == "page"
    assert regions[0]["page_number"] == 1
    assert regions[1]["locator"] == "page:1:paragraph:1"
    assert regions[1]["page_number"] == 1


def test_url_import_persists_validated_provenance_without_fake_file(
    authorized_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def imported(_url: str) -> URLImportResult:
        return URLImportResult(
            source_url="https://example.com/article",
            final_url="https://example.com/final-article",
            title="News",
            character_count=len("Article text."),
            source_text="Article text.",
            media_type="text/plain",
        )

    monkeypatch.setattr("app.api.sources.import_public_url", imported)
    response = authorized_client.post(
        "/api/sources/url", json={"url": "https://example.com/article"}
    )
    assert response.status_code == 200
    imported_body = response.json()
    assert imported_body["source_version_id"] > 0
    saved = authorized_client.post(
        "/api/transformations",
        json=_transformation_request(
            imported_body["source_text"], imported_body["source_version_id"]
        ),
    )
    pack = authorized_client.get(
        f"/api/transformations/{saved.json()['transformation_run_id']}/source-pack"
    )
    asset = pack.json()["versions"][0]["memberships"][0]["asset"]
    assert asset["source_kind"] == "url"
    assert asset["provenance_url"] == "https://example.com/final-article"
    assert asset["original_filename"] is None
    assert "storage_key" not in asset


def test_source_pack_api_hides_other_owners_and_missing_transformations_equally(
    authorized_client: TestClient,
) -> None:
    saved = authorized_client.post(
        "/api/transformations", json=_transformation_request("An owner-scoped source.")
    )
    transformation_id = saved.json()["transformation_run_id"]
    other_client = TestClient(app)
    login(other_client, "second-owner")
    try:
        hidden = other_client.get(f"/api/transformations/{transformation_id}/source-pack")
        missing = other_client.get(f"/api/transformations/{transformation_id + 10000}/source-pack")
    finally:
        other_client.close()

    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()


def test_file_upload_storage_failure_leaves_no_database_rows(
    authorized_client: TestClient,
    auth_database: tuple[TestClient, object, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client, _engine, factory = auth_database

    class BrokenStore:
        def store(self, content: bytes) -> StoredPrivateAsset:
            raise AssetStorageError()

        def read(self, storage_key: str) -> bytes:
            raise AssetStorageError()

        def delete(self, storage_key: str) -> None:
            raise AssetStorageError()

    monkeypatch.setattr("app.api.sources.get_private_asset_store", lambda: BrokenStore())
    response = authorized_client.post(
        "/api/sources/file", files={"file": ("report.txt", b"Private text.", "text/plain")}
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "source_save_failed"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Source)) == 0
        assert session.scalar(select(func.count()).select_from(SourcePack)) == 0
        assert session.scalar(select(func.count()).select_from(SourceVersion)) == 0


def test_database_commit_failure_removes_prepared_private_file(
    authorized_client: TestClient,
    auth_database: tuple[TestClient, object, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client, _engine, factory = auth_database
    storage_root = Path(os.environ["SIH_PRIVATE_ASSET_DIR"])

    def fail_commit(_session: Session) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = authorized_client.post(
        "/api/sources/file",
        files={"file": ("report.txt", b"Private text.", "text/plain")},
    )

    assert response.status_code == 500
    assert [path for path in storage_root.rglob("*") if path.is_file()] == []
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(SourcePack)) == 0
        assert session.scalar(select(func.count()).select_from(SourceAsset)) == 0


def test_storage_keys_are_opaque_and_filename_is_only_metadata(tmp_path: Path) -> None:
    store = LocalPrivateAssetStore(tmp_path / "private")
    content = b"private bytes"
    stored = store.store(content)

    assert stored.content_hash == sha256(content).hexdigest()
    assert stored.byte_size == len(content)
    assert len(stored.storage_key) == 32
    assert store.read(stored.storage_key) == content
    assert (tmp_path / "private" / stored.storage_key[:2] / stored.storage_key).is_file()
    if os.name != "nt":
        assert (
            stat.S_IMODE(
                (tmp_path / "private" / stored.storage_key[:2] / stored.storage_key).stat().st_mode
            )
            == 0o600
        )
    assert safe_original_filename("..\\..\\private.pdf") == "private.pdf"
    with pytest.raises(AssetStorageError):
        store.read("../private.pdf")
    with pytest.raises(AssetStorageError):
        store.read("a" * 32)
    with pytest.raises(AssetStorageError):
        store.store(b"x" * (MAX_PRIVATE_ASSET_BYTES + 1))
    with pytest.raises(AssetStorageError):
        store.read("f" * 32)


def test_source_roles_are_validated_and_have_explicit_policy() -> None:
    roles = ("PRIMARY", "SUPPORTING", "STYLE", "REFERENCE", "OPERATOR_CONTEXT")
    assert [validate_source_role(role) for role in roles] == list(roles)
    with pytest.raises(ValueError, match="membership role"):
        validate_source_role("model_decides")

    primary = source_role_policy("PRIMARY")
    assert primary.may_ground_facts and primary.factual_by_default
    supporting = source_role_policy("SUPPORTING")
    assert supporting.may_ground_facts and supporting.may_contextualize
    assert supporting.conflict_requires_review
    style = source_role_policy("STYLE")
    assert style.controls_presentation and not style.may_ground_facts
    reference = source_role_policy("REFERENCE")
    assert not reference.factual_by_default and not reference.may_ground_facts
    operator_context = source_role_policy("OPERATOR_CONTEXT")
    assert operator_context.controls_task and not operator_context.may_ground_facts


def test_pack_version_contains_multiple_exact_role_memberships_and_revisions_inherit_them(
    authorized_client: TestClient,
    auth_database: tuple[TestClient, object, sessionmaker[Session]],
) -> None:
    _client, _engine, factory = auth_database
    with factory() as session:
        owner = session.scalar(select(User).order_by(User.id))
        assert owner is not None
        primary = create_source_pack_version(session, owner.id, "Primary source.")
        members = [
            create_source_pack_version(session, owner.id, f"{role} source.")
            for role in ("SUPPORTING", "STYLE", "REFERENCE", "OPERATOR_CONTEXT")
        ]
        additional_memberships = [
            SourcePackMembershipInput(
                source_version_id=write.source_version.id,
                source_asset_id=write.asset.id,
                role=role,
            )
            for role, write in zip(
                ("SUPPORTING", "STYLE", "REFERENCE", "OPERATOR_CONTEXT"), members, strict=True
            )
        ]
        snapshot = create_source_pack_version(
            session,
            owner.id,
            "Primary source, revision one.",
            source=primary.source,
            parent_source_version_id=primary.source_version.id,
            memberships=additional_memberships,
        )
        session.commit()
        snapshot_id = snapshot.source_pack_version.id
        snapshot_version_id = snapshot.source_version.id
        expected_memberships = [
            (snapshot.source_version.id, snapshot.asset.id, "PRIMARY"),
            *[
                (write.source_version.id, write.asset.id, role)
                for role, write in zip(
                    ("SUPPORTING", "STYLE", "REFERENCE", "OPERATOR_CONTEXT"),
                    members,
                    strict=True,
                )
            ],
        ]
        assert [
            (member.source_version_id, member.source_asset_id, member.role)
            for member in session.scalars(
                select(SourcePackMembership)
                .where(SourcePackMembership.source_pack_version_id == snapshot_id)
                .order_by(SourcePackMembership.ordinal)
            ).all()
        ] == expected_memberships

    saved = authorized_client.post(
        "/api/transformations",
        json=_transformation_request("Primary source, revision one.", snapshot_version_id),
    )
    assert saved.status_code == 200
    inspected = authorized_client.get(
        f"/api/transformations/{saved.json()['transformation_run_id']}/source-pack"
    )
    version = inspected.json()["versions"][1]
    assert [member["role"] for member in version["memberships"]] == [
        "PRIMARY",
        "SUPPORTING",
        "STYLE",
        "REFERENCE",
        "OPERATOR_CONTEXT",
    ]
    assert [member["source_version_id"] for member in version["memberships"]] == [
        snapshot_version_id,
        *[write.source_version.id for write in members],
    ]

    with factory() as session:
        next_revision = create_source_pack_version(
            session,
            primary.source.owner_id,
            "Primary source, revision two.",
            source=primary.source,
            parent_source_version_id=snapshot_version_id,
        )
        session.commit()
        inherited = list(
            session.scalars(
                select(SourcePackMembership)
                .where(
                    SourcePackMembership.source_pack_version_id
                    == next_revision.source_pack_version.id
                )
                .order_by(SourcePackMembership.ordinal)
            ).all()
        )
        assert [member.role for member in inherited] == [
            "PRIMARY",
            "SUPPORTING",
            "STYLE",
            "REFERENCE",
            "OPERATOR_CONTEXT",
        ]


def test_pack_membership_rejects_a_source_owned_by_another_user(
    auth_database: tuple[TestClient, object, sessionmaker[Session]],
) -> None:
    _client, _engine, factory = auth_database
    with factory() as session:
        owner = User(username="member_owner", password_hash="!disabled-test!")
        other_owner = User(username="member_other", password_hash="!disabled-test!")
        session.add_all([owner, other_owner])
        session.flush()
        primary = create_source_pack_version(session, owner.id, "Primary source.")
        foreign = create_source_pack_version(session, other_owner.id, "Foreign source.")
        with pytest.raises(ValueError, match="authenticated owner"):
            create_source_pack_version(
                session,
                owner.id,
                "Revised primary source.",
                source=primary.source,
                parent_source_version_id=primary.source_version.id,
                memberships=[
                    SourcePackMembershipInput(
                        source_version_id=foreign.source_version.id,
                        source_asset_id=foreign.asset.id,
                        role="SUPPORTING",
                    )
                ],
            )
        session.rollback()
    assert segment_source_text("# Page 3\n\nEvidence text.") == [
        ("page:3", "# Page 3"),
        ("page:3:paragraph:1", "Evidence text."),
    ]
    assert segment_source_text("# Page 3\n\nEvidence text.") == segment_source_text(
        "# Page 3\n\nEvidence text."
    )


def test_source_writer_rejects_a_parent_from_another_pack(
    authorized_client: TestClient,
    auth_database: tuple[TestClient, object, sessionmaker[Session]],
) -> None:
    _client, _engine, factory = auth_database
    with factory() as session:
        owner = session.scalar(select(User).order_by(User.id))
        assert owner is not None
        first = create_source_pack_version(session, owner.id, "First pack source.")
        second = create_source_pack_version(session, owner.id, "Second pack source.")
        with pytest.raises(ValueError, match="Parent source version must belong to the source"):
            create_source_pack_version(
                session,
                owner.id,
                "Invalid cross-pack parent.",
                source=second.source,
                parent_source_version_id=first.source_version.id,
            )
        session.rollback()
