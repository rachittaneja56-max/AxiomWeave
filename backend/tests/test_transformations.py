import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.transformation import SOURCE_TEXT_MAX_LENGTH, OutputType
from app.main import app
from app.models import (
    ArtifactRun,
    Source,
    SourcePackVersion,
    SourceSegment,
    SourceVersion,
    TransformationRun,
    User,
    source_content_hash,
)
from app.source_versions import create_source_version, normalize_source_text, segment_source_text

client: TestClient = TestClient(app)


@pytest.fixture(autouse=True)
def use_authenticated_test_client(authorized_client: TestClient) -> None:
    global client
    client = authorized_client


def valid_request(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "source_text": "The project team will open the new community garden on Saturday.",
        "output_types": ["executive_summary"],
        "audience": "Local residents",
        "tone": "Welcoming",
        "language": "English",
        "detail_level": "standard",
        "objective": "Announce the opening",
        "style": "Plain language",
    }
    request.update(overrides)
    return request


def test_prepare_accepts_single_output_and_applies_defaults() -> None:
    request = valid_request()
    request.pop("language")
    request.pop("detail_level")

    response = client.post("/api/transformations/prepare", json=request)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "request": {
            **request,
            "language": "English",
            "detail_level": "standard",
        },
    }


def test_prepare_accepts_multiple_output_types() -> None:
    request = valid_request(output_types=["executive_summary", "linkedin_post", "presentation"])

    response = client.post("/api/transformations/prepare", json=request)

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "request": request}


def test_create_accepts_all_seven_known_output_types() -> None:
    from app.domain.transformation import CreateTransformationRequest

    outputs = [output.value for output in OutputType]
    request = valid_request(output_types=outputs)
    validated = CreateTransformationRequest.model_validate(request)
    assert [output.value for output in validated.output_types] == outputs


def test_create_transformation_serializes_all_seven_family_names() -> None:
    outputs = [output.value for output in OutputType]
    response = client.post("/api/transformations", json=valid_request(output_types=outputs))
    assert response.status_code == 200
    assert response.json()["output_types"] == outputs

    invalid = client.post(
        "/api/transformations",
        json=valid_request(output_types=["future_unknown_family"]),
    )
    assert invalid.status_code == 422


@pytest.mark.parametrize("source_text", ["", " \n\t"])
def test_prepare_rejects_empty_or_whitespace_source(source_text: str) -> None:
    response = client.post(
        "/api/transformations/prepare", json=valid_request(source_text=source_text)
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert response.json()["error"]["fields"][0]["field"] == "source_text"


def test_prepare_rejects_empty_output_selection() -> None:
    response = client.post("/api/transformations/prepare", json=valid_request(output_types=[]))

    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["field"] == "output_types"


def test_prepare_rejects_unsupported_output_type() -> None:
    response = client.post(
        "/api/transformations/prepare", json=valid_request(output_types=["generic_text"])
    )

    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["field"] == "output_types.0"


def test_prepare_rejects_duplicate_output_types() -> None:
    response = client.post(
        "/api/transformations/prepare",
        json=valid_request(output_types=["advisory", "advisory"]),
    )

    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["field"] == "output_types"


def test_prepare_rejects_oversized_source() -> None:
    response = client.post(
        "/api/transformations/prepare",
        json=valid_request(source_text="a" * 20_001),
    )

    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["field"] == "source_text"


def test_prepare_rejects_invalid_detail_level() -> None:
    response = client.post(
        "/api/transformations/prepare", json=valid_request(detail_level="extreme")
    )

    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["field"] == "detail_level"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("audience", "a" * 121),
        ("tone", "t" * 81),
        ("language", "l" * 81),
        ("objective", "o" * 161),
        ("style", "s" * 121),
    ],
)
def test_prepare_rejects_control_text_over_limit(field: str, value: str) -> None:
    response = client.post("/api/transformations/prepare", json=valid_request(**{field: value}))

    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["field"] == field


def test_normalizes_source_transport_without_rewriting_content() -> None:
    assert normalize_source_text("\ufeffCafé\r\nline\rnext  ") == "Café\nline\nnext  "
    assert normalize_source_text("x" * SOURCE_TEXT_MAX_LENGTH) == "x" * SOURCE_TEXT_MAX_LENGTH
    with pytest.raises(ValueError, match="non-whitespace"):
        normalize_source_text(" \r\n\t")
    with pytest.raises(ValueError, match="20,000"):
        normalize_source_text("x" * (SOURCE_TEXT_MAX_LENGTH + 1))


def test_segments_headings_and_paragraphs_deterministically() -> None:
    source = (
        "# Programme Update\n\nThe first paragraph\ncontinues here.\n\n"
        "## Budget\n\nThe approved budget is ₹40 crore."
    )
    expected = [
        ("heading:1", "# Programme Update"),
        ("paragraph:1", "The first paragraph\ncontinues here."),
        ("heading:2", "## Budget"),
        ("paragraph:2", "The approved budget is ₹40 crore."),
    ]
    assert segment_source_text(source) == expected
    assert segment_source_text(source) == expected


def persisted_request(**overrides: object) -> dict[str, object]:
    return {
        **valid_request(
            source_text="\ufeff# Budget\r\n\r\nThe approved budget is ₹40 crore.",
            output_types=["executive_summary", "presentation"],
        ),
        "supporting_context": "For district administrators.",
        **overrides,
    }


def test_persisted_transformation_requires_authentication(
    auth_database: tuple[TestClient, object, sessionmaker[Session]],
) -> None:
    _client, _engine, _factory = auth_database
    with TestClient(app) as anonymous_client:
        response = anonymous_client.post("/api/transformations", json=persisted_request())
    assert response.status_code == 401


def test_persists_source_snapshot_segments_and_controls(
    auth_database: tuple[TestClient, object, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    response = client.post("/api/transformations", json=persisted_request())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "saved"
    assert body["output_types"] == ["executive_summary", "presentation"]
    assert "source_text" not in body and "supporting_context" not in body

    with factory() as session:
        sources = list(session.scalars(select(Source)))
        versions = list(session.scalars(select(SourceVersion)))
        segments = list(session.scalars(select(SourceSegment).order_by(SourceSegment.ordinal)))
        runs = list(session.scalars(select(TransformationRun)))
        current_user = session.scalar(select(User))
        assert len(sources) == len(versions) == len(runs) == 1
        assert current_user is not None
        assert sources[0].owner_id == runs[0].owner_id == current_user.id
        assert versions[0].source_id == sources[0].id
        assert versions[0].version_number == 1
        assert versions[0].source_text == "# Budget\n\nThe approved budget is ₹40 crore."
        assert versions[0].content_hash == source_content_hash(versions[0].source_text)
        assert versions[0].content_hash == body["source_version"]["content_hash"]
        assert [item.segment_text for item in segments] == [
            "# Budget",
            "The approved budget is ₹40 crore.",
        ]
        assert runs[0].source_version_id == versions[0].id
        assert runs[0].supporting_context == "For district administrators."
        assert runs[0].selected_output_types == ["executive_summary", "presentation"]
        assert (runs[0].audience, runs[0].tone, runs[0].language) == (
            "Local residents",
            "Welcoming",
            "English",
        )
        assert (runs[0].detail_level, runs[0].objective, runs[0].style) == (
            "standard",
            "Announce the opening",
            "Plain language",
        )
        assert body["source_version"]["segment_count"] == 2
        assert session.scalar(select(func.count()).select_from(TransformationRun)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRun)) == 0


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"output_types": ["unknown_family"]}, "output_types"),
        ({"owner_id": 999}, "owner_id"),
        ({"user_id": 999}, "user_id"),
        ({"source_text": " \t\r\n"}, "source_text"),
        ({"source_text": "x" * 20_001}, "source_text"),
        ({"supporting_context": "x" * 5_001}, "supporting_context"),
    ],
)
def test_persisted_transformation_rejects_invalid_source_context_or_outputs(
    overrides: dict[str, object], field: str
) -> None:
    response = client.post("/api/transformations", json=persisted_request(**overrides))
    assert response.status_code == 422
    assert field in {item["field"].split(".")[0] for item in response.json()["error"]["fields"]}


def test_failed_segment_creation_rolls_back_all_rows(
    auth_database: tuple[TestClient, object, sessionmaker[Session]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import source_versions

    client, _engine, factory = auth_database

    def fail_segmentation(_source_text: str) -> list[tuple[str, str]]:
        raise RuntimeError("internal detail")

    monkeypatch.setattr(source_versions, "segment_source_text", fail_segmentation)
    response = client.post("/api/transformations", json=persisted_request())
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "save_failed"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Source)) == 0
        assert session.scalar(select(func.count()).select_from(SourceVersion)) == 0
        assert session.scalar(select(func.count()).select_from(SourceSegment)) == 0
        assert session.scalar(select(func.count()).select_from(TransformationRun)) == 0


def test_source_version_function_appends_without_overwriting_history(
    auth_database: tuple[TestClient, object, sessionmaker[Session]],
) -> None:
    _client, _engine, factory = auth_database
    with factory() as session:
        with session.begin():
            source = Source(owner_id=1)
            session.add(source)
            session.flush()
            first = create_source_version(session, source, "# V1\n\nFirst source.")
            session.flush()
            first_id = first.id
            first_hash = first.content_hash
        with session.begin():
            source = session.get(Source, source.id)
            assert source is not None
            second = create_source_version(
                session,
                source,
                "# V2\n\nSecond source.",
                parent_source_version_id=first_id,
            )
            session.flush()
            assert second.version_number == 2
        versions = list(
            session.scalars(select(SourceVersion).order_by(SourceVersion.version_number))
        )
        assert [item.id for item in versions] == [first_id, second.id]
        assert versions[0].content_hash == first_hash
        assert [item.source_text for item in versions] == [
            "# V1\n\nFirst source.",
            "# V2\n\nSecond source.",
        ]
        segments = list(
            session.scalars(select(SourceSegment).order_by(SourceSegment.source_version_id))
        )
        assert [item.segment_text for item in segments] == [
            "# V1",
            "First source.",
            "# V2",
            "Second source.",
        ]
        pack_versions = list(
            session.scalars(
                select(SourcePackVersion)
                .where(SourcePackVersion.source_version_id.in_([first_id, second.id]))
                .order_by(SourcePackVersion.version_number)
            ).all()
        )
        assert [item.version_number for item in pack_versions] == [1, 2]
        assert pack_versions[0].parent_source_pack_version_id is None
        assert pack_versions[1].parent_source_pack_version_id == pack_versions[0].id
