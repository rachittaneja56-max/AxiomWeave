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
    SourcePackVersion,
    SourceVersion,
    User,
)
from app.private_asset_storage import (
    MAX_PRIVATE_ASSET_BYTES,
    AssetStorageError,
    LocalPrivateAssetStore,
    StoredPrivateAsset,
)
from app.source_versions import (
    create_source_pack_version,
    safe_original_filename,
    segment_source_text,
    validate_authority_role,
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
    assert asset["authority_role"] == "authoritative"
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
    assert "storage_key" not in asset


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
    returned_asset = pack.json()["versions"][0]["assets"][0]
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
    regions = pack.json()["versions"][0]["assets"][0]["regions"]
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
    asset = pack.json()["versions"][0]["assets"][0]
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


def test_authority_and_page_region_rules_are_small_and_deterministic() -> None:
    assert validate_authority_role("authoritative") == "authoritative"
    assert validate_authority_role("supporting") == "supporting"
    with pytest.raises(ValueError, match="authority role"):
        validate_authority_role("model_decides")
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
