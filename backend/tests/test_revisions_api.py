from typing import TypeVar, cast

from auth_support import login
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.generation import get_generation_provider
from app.api.revisions import get_revision_provider
from app.generation import GenerationRequest, GenerationResult, StructuredGenerationResult
from app.models import (
    ArtifactVersion,
    EvidenceLink,
    SourceSegment,
    SourceVersion,
    TransformationRun,
)
from app.presentation import PresentationSpec, SlideSpec

T = TypeVar("T", bound=BaseModel)


class RevisionProvider:
    def __init__(self) -> None:
        self.generated = 0
        self.structured_requests: list[GenerationRequest] = []

    async def generate(self, _request: GenerationRequest) -> GenerationResult:
        self.generated += 1
        return GenerationResult(
            text="Full regeneration from source V2.", provider="test", model="fixture"
        )

    async def generate_structured[TModel: BaseModel](
        self, request: GenerationRequest, response_model: type[TModel]
    ) -> StructuredGenerationResult[TModel]:
        self.structured_requests.append(request)
        if response_model is PresentationSpec:
            value = PresentationSpec(
                title="Updated briefing",
                slides=[
                    SlideSpec(
                        title="Opening",
                        key_message="The center opened Sunday.",
                        bullets=["The center opened Sunday."],
                        visual_recommendation="Building entrance.",
                        speaker_notes="Share the updated opening day.",
                    ),
                    SlideSpec(
                        title="Visit",
                        key_message="Visitors enter on Maple Street.",
                        bullets=["Use the Maple Street entrance."],
                        visual_recommendation="Entrance sign.",
                        speaker_notes="Point out the entrance.",
                    ),
                ],
            )
        else:
            value = response_model.model_validate(
                {"content": "Targeted update: the center opened Sunday."}
            )
        return StructuredGenerationResult(
            value=cast(TModel, value), provider="test", model="fixture"
        )


def install_revision_provider(provider: RevisionProvider) -> None:
    from app.main import app

    app.dependency_overrides[get_generation_provider] = lambda: provider
    app.dependency_overrides[get_revision_provider] = lambda: provider


def create_transformation(client: TestClient) -> int:
    response = client.post(
        "/api/transformations",
        json={
            "source_text": (
                "The community center opened on Saturday.\n\nVisitors enter on Maple Street."
            ),
            "supporting_context": "Keep the announcement clear.",
            "output_types": ["executive_summary", "linkedin_post"],
            "audience": "community members",
            "tone": "clear",
            "language": "English",
            "detail_level": "standard",
            "objective": "inform",
            "style": "plain language",
        },
    )
    assert response.status_code == 200
    return response.json()["transformation_run_id"]


def test_source_v2_diff_impact_targeted_update_and_full_regeneration(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    provider = RevisionProvider()
    install_revision_provider(provider)
    transformation_id = create_transformation(client)
    generated = client.post(f"/api/transformations/{transformation_id}/generate").json()
    first_run, second_run = generated["artifacts"]
    first_version_id = first_run["artifact_version"]["id"]
    second_version_id = second_run["artifact_version"]["id"]

    with factory() as session:
        first_version = session.get(ArtifactVersion, first_version_id)
        second_version = session.get(ArtifactVersion, second_version_id)
        assert first_version is not None
        assert second_version is not None
        source_v1 = session.get(SourceVersion, first_version.source_version_id)
        assert source_v1 is not None
        first_segment = session.scalar(
            select(SourceSegment).where(
                SourceSegment.source_version_id == source_v1.id,
                SourceSegment.locator == "paragraph:1",
            )
        )
        second_segment = session.scalar(
            select(SourceSegment).where(
                SourceSegment.source_version_id == source_v1.id,
                SourceSegment.locator == "paragraph:2",
            )
        )
        assert first_segment is not None
        assert second_segment is not None
        session.add_all(
            [
                EvidenceLink(
                    artifact_version_id=first_version.id,
                    claim_text="The center opened Saturday.",
                    source_version_id=source_v1.id,
                    source_segment_id=first_segment.id,
                    source_quote=first_segment.segment_text,
                    source_locator=first_segment.locator,
                    status="linked",
                ),
                EvidenceLink(
                    artifact_version_id=second_version.id,
                    claim_text="Visitors enter on Maple Street.",
                    source_version_id=source_v1.id,
                    source_segment_id=second_segment.id,
                    source_quote=second_segment.segment_text,
                    source_locator=second_segment.locator,
                    status="linked",
                ),
            ]
        )
        session.commit()
        source_id = source_v1.source_id
        original_source_text = source_v1.source_text
        original_artifact_content = first_version.content

    update = client.post(
        f"/api/transformations/{transformation_id}/source-versions",
        json={
            "source_text": (
                "The community center opened on Sunday.\n\nVisitors enter on Maple Street."
            )
        },
    )
    assert update.status_code == 200
    update_body = update.json()
    source_v2_id = update_body["source_version"]["id"]
    assert update_body["parent_source_version"]["id"] != source_v2_id
    assert update_body["changes"] == [
        {
            "change_type": "changed",
            "locator": "paragraph:1",
            "old_text": "The community center opened on Saturday.",
            "new_text": "The community center opened on Sunday.",
        }
    ]
    assert len(update_body["potentially_affected_artifacts"]) == 1
    assert update_body["potentially_affected_artifacts"][0]["artifact_version_id"] == (
        first_version_id
    )

    with factory() as session:
        v1_after = session.get(SourceVersion, update_body["parent_source_version"]["id"])
        v2 = session.get(SourceVersion, source_v2_id)
        assert v1_after is not None and v2 is not None
        assert v1_after.source_text == original_source_text
        assert v2.source_id == source_id
        assert v2.parent_source_version_id == v1_after.id
        transformation = session.get(TransformationRun, transformation_id)
        assert transformation is not None
        assert transformation.source_version_id == v2.id

    targeted = client.post(f"/api/artifact-runs/{first_run['artifact_run_id']}/targeted-update")
    assert targeted.status_code == 200
    targeted_version = targeted.json()["artifact_version"]
    assert targeted_version["version_number"] == 2
    assert targeted_version["source_version_id"] == source_v2_id
    assert targeted_version["content"] == "Targeted update: the center opened Sunday."
    request = provider.structured_requests[0]
    assert (
        request.source_text
        == "The community center opened on Sunday.\n\nVisitors enter on Maple Street."
    )
    assert request.prior_source_text == original_source_text
    assert '"change_type": "changed"' in request.changed_source_material
    assert request.artifact_content == original_artifact_content
    assert request.supporting_context == "Keep the announcement clear."
    assert "Audience: community members" in request.transformation_instructions

    comparison = client.post(
        "/api/discrepancies/analyze",
        json={
            "artifact_version_a_id": first_version_id,
            "artifact_version_b_id": targeted_version["id"],
        },
    )
    assert comparison.status_code == 409
    assert comparison.json()["error"]["code"] == "incompatible_artifacts"

    regenerated = client.post(f"/api/artifact-runs/{first_run['artifact_run_id']}/regenerate")
    assert regenerated.status_code == 200
    assert regenerated.json()["artifact_version"]["version_number"] == 3
    assert regenerated.json()["artifact_version"]["source_version_id"] == source_v2_id
    assert regenerated.json()["artifact_version"]["content"] == "Full regeneration from source V2."

    detail = client.get(f"/api/transformations/{transformation_id}").json()
    versions = detail["artifact_runs"][0]["versions"]
    assert [item["version_number"] for item in versions] == [1, 2, 3]
    assert [item["source_version_id"] for item in versions] == [
        update_body["parent_source_version"]["id"],
        source_v2_id,
        source_v2_id,
    ]


def test_revision_impact_is_owner_scoped(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, _factory = auth_database
    login(client, "first-owner")
    provider = RevisionProvider()
    install_revision_provider(provider)
    transformation_id = create_transformation(client)
    assert (
        client.get(f"/api/transformations/{transformation_id}/revision-impact").status_code == 200
    )
    login(client, "second-owner")
    assert (
        client.get(f"/api/transformations/{transformation_id}/revision-impact").status_code == 404
    )
    assert (
        client.post(
            f"/api/transformations/{transformation_id}/source-versions",
            json={"source_text": "A private replacement source."},
        ).status_code
        == 404
    )
