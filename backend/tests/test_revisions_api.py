import json
from typing import TypeVar, cast

import pytest
from auth_support import login
from fastapi.testclient import TestClient
from generation_support import drain_jobs, run_artifact_action, run_generation
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.evidence import EvidenceAnalysis, get_analysis_provider
from app.api.generation import get_generation_provider
from app.artifact_contracts import (
    InfographicCalloutBlock,
    InfographicSpec,
    VideoPackageSpec,
    VideoSceneSpec,
)
from app.artifact_generators import TargetedBlockReplacement, TargetedBlockReplacementSet
from app.artifact_lineage import add_validated_dependency, extract_artifact_blocks
from app.domain.transformation import OutputType
from app.generation import GenerationRequest, GenerationResult, StructuredGenerationResult
from app.main import app
from app.models import (
    ArtifactBlock,
    ArtifactBlockDependency,
    ArtifactVersion,
    EvidenceLink,
    Job,
    SourceAsset,
    SourcePackMembership,
    SourcePackVersion,
    SourceRegion,
    SourceRegionAlignment,
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
        self.response_models: list[type[BaseModel]] = []

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.generated += 1
        return GenerationResult(text=request.source_text, provider="test", model="fixture")

    async def generate_structured[TModel: BaseModel](
        self, request: GenerationRequest, response_model: type[TModel]
    ) -> StructuredGenerationResult[TModel]:
        self.structured_requests.append(request)
        self.response_models.append(response_model)
        if response_model is TargetedBlockReplacementSet:
            allowed: list[dict[str, str]] = json.loads(request.artifact_content)
            value = TargetedBlockReplacementSet(
                replacements=[
                    TargetedBlockReplacement(
                        block_key=item["block_key"],
                        replacement_text=request.source_text.split("\n\n", 1)[0],
                    )
                    for item in allowed
                ]
            )
        elif response_model is PresentationSpec:
            opening_day = "Sunday" if "Sunday" in request.source_text else "Saturday"
            value = PresentationSpec(
                title="Updated briefing",
                slides=[
                    SlideSpec(
                        title="Opening",
                        key_message=f"The center opened on {opening_day}.",
                        bullets=[f"The center opened on {opening_day}."],
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
        elif response_model is InfographicSpec:
            opening_day = "Sunday" if "Sunday" in request.source_text else "Saturday"
            value = InfographicSpec(
                title="Updated infographic",
                key_message=f"The center opened on {opening_day}.",
                blocks=[InfographicCalloutBlock(label="Opening", value=opening_day)],
                visual_direction="Use a simple calendar illustration.",
            )
        elif response_model is VideoPackageSpec:
            opening_day = "Sunday" if "Sunday" in request.source_text else "Saturday"
            value = VideoPackageSpec(
                title="Updated video package",
                concept="Share the updated opening day.",
                scenes=[
                    VideoSceneSpec(
                        title="Updated opening",
                        narration=f"The center opened on {opening_day}.",
                        on_screen_text=[f"Opened {opening_day}"],
                        visual_direction="Show the center entrance.",
                    )
                ],
            )
        else:
            value = response_model.model_validate(
                {"content": "Targeted update: the center opened Sunday."}
            )
        return StructuredGenerationResult(
            value=cast(TModel, value), provider="test", model="fixture"
        )


class CompleteEmptyScanRevisionProvider(RevisionProvider):
    supports_phase4_automatic_claim_scan = True

    async def generate_structured[TModel: BaseModel](
        self, request: GenerationRequest, response_model: type[TModel]
    ) -> StructuredGenerationResult[TModel]:
        if response_model is EvidenceAnalysis:
            value = EvidenceAnalysis(proposals=[], analysis_complete=True)
            return StructuredGenerationResult(
                value=cast(TModel, value), provider="test", model="empty-scan"
            )
        return await super().generate_structured(request, response_model)


def create_transformation(client: TestClient) -> int:
    response = client.post(
        "/api/transformations",
        json={
            "source_text": (
                "The community center opened on Saturday.\n\nVisitors enter on Maple Street."
                "\n\nHours are posted."
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


def attach_dependency(
    session: Session,
    version: ArtifactVersion,
    *,
    block_key: str,
    locator: str = "paragraph:1",
) -> None:
    block = session.scalar(
        select(ArtifactBlock).where(
            ArtifactBlock.artifact_version_id == version.id,
            ArtifactBlock.block_key == block_key,
        )
    )
    assert block is not None
    pack_version = session.scalar(
        select(SourcePackVersion).where(
            SourcePackVersion.source_version_id == version.source_version_id
        )
    )
    assert pack_version is not None
    region = session.scalar(
        select(SourceRegion)
        .join(SourceAsset, SourceAsset.id == SourceRegion.source_asset_id)
        .join(SourcePackMembership, SourcePackMembership.source_asset_id == SourceAsset.id)
        .where(
            SourcePackMembership.source_pack_version_id == pack_version.id,
            SourceRegion.locator == locator,
        )
    )
    assert region is not None
    add_validated_dependency(
        session,
        block,
        region,
        assertion=None,
        dependency_kind="lineage",
        origin="proposal",
        profile_version="revision-test:1",
    )


def test_source_v2_diff_impact_targeted_update_and_full_regeneration(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    provider = RevisionProvider()
    transformation_id = create_transformation(client)
    generated = run_generation(client, transformation_id, factory, provider).json()
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
        attach_dependency(session, first_version, block_key="paragraph:1")
        attach_dependency(session, first_version, block_key="paragraph:2", locator="paragraph:2")
        attach_dependency(session, first_version, block_key="paragraph:3", locator="paragraph:3")
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
                "The community center opened on Sunday.\n\nHours are posted."
                "\n\nVisitors enter on Maple Street."
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
        },
        {
            "change_type": "changed",
            "locator": "paragraph:2",
            "old_text": "Visitors enter on Maple Street.",
            "new_text": "Hours are posted.",
        },
        {
            "change_type": "changed",
            "locator": "paragraph:3",
            "old_text": "Hours are posted.",
            "new_text": "Visitors enter on Maple Street.",
        },
    ]
    impacts = {
        item["artifact_version_id"]: item for item in update_body["potentially_affected_artifacts"]
    }
    assert len(impacts) == 2
    assert impacts[first_version_id]["impact_state"] == "affected"
    assert impacts[first_version_id]["affected_block_keys"] == ["paragraph:1"]
    assert impacts[first_version_id]["review_block_keys"] == []
    assert impacts[first_version_id]["unknown_block_keys"] == []
    assert impacts[second_version_id]["impact_state"] == "unknown"
    blocked_target = client.post(
        f"/api/artifact-runs/{second_run['artifact_run_id']}/targeted-update"
    )
    assert blocked_target.status_code == 409

    with factory() as session:
        v1_after = session.get(SourceVersion, update_body["parent_source_version"]["id"])
        v2 = session.get(SourceVersion, source_v2_id)
        assert v1_after is not None and v2 is not None
        assert v1_after.source_text == original_source_text
        assert v2.source_id == source_id
        assert v2.parent_source_version_id == v1_after.id
        v1_pack_version = session.scalar(
            select(SourcePackVersion).where(SourcePackVersion.source_version_id == v1_after.id)
        )
        v2_pack_version = session.scalar(
            select(SourcePackVersion).where(SourcePackVersion.source_version_id == v2.id)
        )
        assert v1_pack_version is not None and v2_pack_version is not None
        assert v2_pack_version.version_number == 2
        assert v2_pack_version.parent_source_pack_version_id == v1_pack_version.id
        assert v1_pack_version.content_hash == v1_after.content_hash
        assert v2_pack_version.content_hash == v2.content_hash
        transformation = session.get(TransformationRun, transformation_id)
        assert transformation is not None
        assert transformation.source_version_id == v2.id

    targeted = client.post(f"/api/artifact-runs/{first_run['artifact_run_id']}/targeted-update")
    assert targeted.status_code == 202
    assert targeted.json()["status"] == "pending"
    duplicate = client.post(f"/api/artifact-runs/{first_run['artifact_run_id']}/targeted-update")
    assert duplicate.status_code == 202
    pending_detail = client.get(f"/api/transformations/{transformation_id}").json()
    pending_run = next(
        item
        for item in pending_detail["artifact_runs"]
        if item["artifact_run_id"] == first_run["artifact_run_id"]
    )
    assert pending_run["status"] == "pending"
    assert [version["id"] for version in pending_run["versions"]] == [first_version_id]
    with factory() as session:
        jobs = list(
            session.scalars(
                select(Job)
                .where(Job.artifact_run_id == first_run["artifact_run_id"])
                .order_by(Job.id)
            )
        )
        assert len(jobs) == 2
        assert sum(job.status in {"queued", "running"} for job in jobs) == 1
        assert jobs[-1].source_version_id == source_v2_id
        assert jobs[-1].base_artifact_version_id == first_version_id
    drain_jobs(factory, provider)
    detail_after_target = client.get(f"/api/transformations/{transformation_id}").json()
    targeted_version = detail_after_target["artifact_runs"][0]["versions"][-1]
    assert targeted_version["version_number"] == 2
    assert targeted_version["source_version_id"] == source_v2_id
    assert targeted_version["content"] == (
        "The community center opened on Sunday.\n\nVisitors enter on Maple Street."
        "\n\nHours are posted."
    )
    request = provider.structured_requests[0]
    assert (
        request.source_text == "The community center opened on Sunday.\n\nHours are posted."
        "\n\nVisitors enter on Maple Street."
    )
    assert request.prior_source_text == original_source_text
    assert '"alignment_state": "changed"' in request.changed_source_material
    authorized_blocks = json.loads(request.artifact_content)
    assert len(authorized_blocks) == 1
    assert authorized_blocks[0]["block_key"] == "paragraph:1"
    assert authorized_blocks[0]["visible_text"] == "The community center opened on Saturday."
    assert (
        len(extract_artifact_blocks(OutputType.EXECUTIVE_SUMMARY, original_artifact_content)) == 3
    )
    preserved_text = "\n\n".join(
        block.visible_text
        for block in extract_artifact_blocks(
            OutputType.EXECUTIVE_SUMMARY, targeted_version["content"]
        )
        if block.block_key == "paragraph:2"
    )
    assert preserved_text == "Visitors enter on Maple Street."
    assert "Hours are posted." in targeted_version["content"]
    with factory() as session:
        targeted_version_id = targeted_version["id"]
        version_blocks = {
            block.block_key: block.id
            for block in session.scalars(
                select(ArtifactBlock).where(
                    ArtifactBlock.artifact_version_id == targeted_version_id
                )
            )
        }
        v1_pack_version_id = session.scalar(
            select(SourcePackVersion.id).where(
                SourcePackVersion.source_version_id == update_body["parent_source_version"]["id"]
            )
        )
        v2_pack_version_id = session.scalar(
            select(SourcePackVersion.id).where(SourcePackVersion.source_version_id == source_v2_id)
        )
        assert v1_pack_version_id is not None and v2_pack_version_id is not None
        moved_rows = list(
            session.scalars(
                select(SourceRegionAlignment).where(
                    SourceRegionAlignment.parent_pack_version_id == v1_pack_version_id,
                    SourceRegionAlignment.child_pack_version_id == v2_pack_version_id,
                    SourceRegionAlignment.alignment_state == "moved",
                )
            )
        )
        assert len(moved_rows) == 2
        expected_new_region_ids = {row.new_region_id for row in moved_rows}
        carried = list(
            session.scalars(
                select(ArtifactBlockDependency).where(
                    ArtifactBlockDependency.artifact_block_id.in_(
                        [version_blocks["paragraph:2"], version_blocks["paragraph:3"]]
                    )
                )
            )
        )
        assert len(carried) == 2
        assert {dependency.source_region_id for dependency in carried} == expected_new_region_ids
        assert all(dependency.origin == "carried_forward" for dependency in carried)
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

    regenerated = run_artifact_action(
        client, first_run["artifact_run_id"], "regenerate", factory, provider
    )
    assert regenerated.status_code == 200
    assert regenerated.json()["artifact_version"]["version_number"] == 3
    assert regenerated.json()["artifact_version"]["source_version_id"] == source_v2_id
    assert regenerated.json()["artifact_version"]["content"] == (
        "The community center opened on Sunday.\n\nHours are posted."
        "\n\nVisitors enter on Maple Street."
    )
    detail = client.get(f"/api/transformations/{transformation_id}").json()
    versions = detail["artifact_runs"][0]["versions"]
    assert [item["version_number"] for item in versions] == [1, 2, 3]
    assert [item["source_version_id"] for item in versions] == [
        update_body["parent_source_version"]["id"],
        source_v2_id,
        source_v2_id,
    ]


def test_x_post_targeted_update_from_source_v2_keeps_output_contract(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    provider = RevisionProvider()
    response = client.post(
        "/api/transformations",
        json={
            "source_text": "The center opens Saturday.",
            "output_types": ["x_post"],
            "audience": "community",
            "tone": "clear",
            "language": "English",
            "detail_level": "brief",
            "objective": "inform",
            "style": "plain",
        },
    )
    transformation_id = response.json()["transformation_run_id"]
    generated = run_generation(client, transformation_id, factory, provider).json()
    artifact = generated["artifacts"][0]
    with factory() as session:
        version = session.get(ArtifactVersion, artifact["artifact_version"]["id"])
        assert version is not None
        attach_dependency(session, version, block_key="paragraph:1")
        session.commit()

    revised = client.post(
        f"/api/transformations/{transformation_id}/source-versions",
        json={"source_text": "The center opens Sunday."},
    )
    assert revised.status_code == 200
    source_v2_id = revised.json()["source_version"]["id"]
    targeted = client.post(f"/api/artifact-runs/{artifact['artifact_run_id']}/targeted-update")
    assert targeted.status_code == 202
    drain_jobs(factory, provider)
    detail = client.get(f"/api/transformations/{transformation_id}").json()
    version = detail["artifact_runs"][0]["versions"][-1]
    assert version["source_version_id"] == source_v2_id
    assert version["version_number"] == 2
    assert len(version["content"]) <= 280
    request = provider.structured_requests[-1]
    assert request.max_output_tokens == 220
    assert "maximum of 280 Unicode code points" in request.transformation_instructions

    versions = detail["artifact_runs"][0]["versions"]
    assert [item["version_number"] for item in versions] == [1, 2]
    assert [item["source_version_id"] for item in versions] == [
        revised.json()["parent_source_version"]["id"],
        source_v2_id,
    ]


@pytest.mark.parametrize(
    ("output_type", "response_model"),
    [
        ("presentation", PresentationSpec),
        ("infographic", InfographicSpec),
        ("video_package", VideoPackageSpec),
    ],
)
def test_structured_family_targeted_update_uses_v2_contract_and_lineage(
    output_type: str,
    response_model: type[BaseModel],
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    provider = RevisionProvider()
    saved = client.post(
        "/api/transformations",
        json={
            "source_text": "The center opened on Saturday.\n\nVisitors may bring one guest.",
            "output_types": [output_type],
            "audience": "community members",
            "tone": "clear",
            "language": "English",
            "detail_level": "standard",
            "objective": "inform",
            "style": "plain language",
        },
    )
    transformation_id = saved.json()["transformation_run_id"]
    first = run_generation(client, transformation_id, factory, provider).json()["artifacts"][0]
    first_version = first["artifact_version"]
    with factory() as session:
        version = session.get(ArtifactVersion, first_version["id"])
        assert version is not None
        affected_keys = {
            "presentation": {"slide:1:key_message", "slide:1:bullet:1"},
            "infographic": {"infographic:key_message", "block:1:value"},
            "video_package": {"scene:1:narration", "scene:1:on_screen:1"},
        }[output_type]
        blocks = list(
            session.scalars(
                select(ArtifactBlock).where(ArtifactBlock.artifact_version_id == version.id)
            )
        )
        for block in blocks:
            attach_dependency(
                session,
                version,
                block_key=block.block_key,
                locator=("paragraph:1" if block.block_key in affected_keys else "paragraph:2"),
            )
        session.commit()

    revised = client.post(
        f"/api/transformations/{transformation_id}/source-versions",
        json={"source_text": "The center opened on Sunday.\n\nVisitors may bring one guest."},
    )
    assert revised.status_code == 200
    source_v2_id = revised.json()["source_version"]["id"]
    targeted = client.post(f"/api/artifact-runs/{first['artifact_run_id']}/targeted-update")
    assert targeted.status_code == 202
    drain_jobs(factory, provider)

    detail = client.get(f"/api/transformations/{transformation_id}").json()
    versions = detail["artifact_runs"][0]["versions"]
    assert [version["version_number"] for version in versions] == [1, 2]
    assert versions[0]["source_version_id"] == revised.json()["parent_source_version"]["id"]
    assert versions[1]["source_version_id"] == source_v2_id
    assert versions[1]["artifact_schema_version"] == "1"
    assert versions[1]["context_manifest_id"] is not None
    assert provider.response_models[-1] is TargetedBlockReplacementSet
    parsed = response_model.model_validate_json(versions[1]["content"])
    assert parsed
    assert first_version["context_manifest_id"] is not None
    allowed_keys = {
        item["block_key"] for item in json.loads(provider.structured_requests[-1].artifact_content)
    }
    assert allowed_keys == affected_keys
    old_blocks = {
        block.block_key: block.visible_text
        for block in extract_artifact_blocks(OutputType(output_type), first_version["content"])
    }
    new_blocks = {
        block.block_key: block.visible_text
        for block in extract_artifact_blocks(OutputType(output_type), versions[1]["content"])
    }
    assert old_blocks.keys() == new_blocks.keys()
    assert all(old_blocks[key] == new_blocks[key] for key in old_blocks.keys() - allowed_keys)
    assert all(old_blocks[key] != new_blocks[key] for key in allowed_keys)


@pytest.mark.parametrize("output_type", ["executive_summary", "presentation"])
def test_source_revision_preserves_unrelated_manual_edits(
    output_type: str,
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    provider = CompleteEmptyScanRevisionProvider()
    app.dependency_overrides[get_generation_provider] = lambda: provider
    app.dependency_overrides[get_analysis_provider] = lambda: provider
    saved = client.post(
        "/api/transformations",
        json={
            "source_text": (
                "The community center opened on Saturday.\n\nVisitors enter on Maple Street."
            ),
            "output_types": [output_type],
            "audience": "community members",
            "tone": "clear",
            "language": "English",
            "detail_level": "standard",
            "objective": "inform",
            "style": "plain language",
        },
    )
    assert saved.status_code == 200
    transformation_id = saved.json()["transformation_run_id"]
    generated = run_generation(client, transformation_id, factory, provider)
    assert generated.status_code == 200
    artifact = generated.json()["artifacts"][0]
    run_id = artifact["artifact_run_id"]
    original = artifact["artifact_version"]
    changed_source_block = (
        "paragraph:1" if output_type == "executive_summary" else "slide:1:key_message"
    )
    manual_text = "An editor added this visual cue."
    if output_type == "executive_summary":
        parent_content = original["content"]
        manual_content = parent_content.replace("Visitors enter on Maple Street.", manual_text, 1)
        assert manual_content != parent_content
    else:
        parsed = PresentationSpec.model_validate_json(original["content"])
        parsed.slides[1] = parsed.slides[1].model_copy(
            update={"visual_recommendation": "Use a blue map marker."}
        )
        manual_content = parsed.model_dump_json()
        manual_text = "Use a blue map marker."

    with factory() as session:
        parent_version = session.get(ArtifactVersion, original["id"])
        assert parent_version is not None
        attach_dependency(session, parent_version, block_key=changed_source_block)
        session.commit()

    manual_edit = client.post(
        f"/api/artifact-runs/{run_id}/versions", json={"content": manual_content}
    )
    assert manual_edit.status_code == 200
    manual_version_id = manual_edit.json()["id"]
    assert (
        client.get(f"/api/artifact-versions/{manual_version_id}/claim-scan").json()["status"]
        == "complete"
    )

    source_update = client.post(
        f"/api/transformations/{transformation_id}/source-versions",
        json={
            "source_text": (
                "The community center opened on Sunday.\n\nVisitors enter on Maple Street."
            )
        },
    )
    assert source_update.status_code == 200
    impact = next(
        item
        for item in source_update.json()["potentially_affected_artifacts"]
        if item["artifact_version_id"] == manual_version_id
    )
    assert impact["impact_state"] == "affected"
    assert impact["affected_block_keys"] == [changed_source_block]
    assert impact["unknown_block_keys"] == []
    assert impact["targeted_update_available"] is True

    targeted = client.post(f"/api/artifact-runs/{run_id}/targeted-update")
    assert targeted.status_code == 202
    drain_jobs(factory, provider)
    detail = client.get(f"/api/transformations/{transformation_id}").json()
    versions = detail["artifact_runs"][0]["versions"]
    assert len(versions) == 3
    assert versions[1]["id"] == manual_version_id
    assert versions[1]["review_status"] == "draft"
    assert versions[1]["content"] == manual_edit.json()["content"]
    latest = versions[2]
    assert latest["review_status"] == "draft"
    if output_type == "executive_summary":
        blocks = {
            block.block_key: block.visible_text
            for block in extract_artifact_blocks(OutputType(output_type), latest["content"])
        }
        assert blocks["paragraph:1"] == "The community center opened on Sunday."
        assert blocks["paragraph:2"] == manual_text
        assert latest["content"].count(manual_text) == 1
    else:
        before_blocks = {
            block.block_key: block.visible_text
            for block in extract_artifact_blocks(OutputType(output_type), manual_content)
        }
        after_blocks = {
            block.block_key: block.visible_text
            for block in extract_artifact_blocks(OutputType(output_type), latest["content"])
        }
        assert before_blocks["slide:2:visual_recommendation"] == manual_text
        assert after_blocks["slide:2:visual_recommendation"] == manual_text
        assert {key for key in before_blocks if before_blocks[key] != after_blocks[key]} == {
            changed_source_block
        }


def test_revision_impact_is_owner_scoped(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, _factory = auth_database
    login(client, "first-owner")
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


def test_ambiguous_region_alignment_blocks_targeted_update(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    provider = RevisionProvider()
    saved = client.post(
        "/api/transformations",
        json={
            "source_text": "Visitors enter on Maple Street.",
            "output_types": ["executive_summary"],
            "audience": "community members",
            "tone": "clear",
            "language": "English",
            "detail_level": "standard",
            "objective": "inform",
            "style": "plain language",
        },
    )
    transformation_id = saved.json()["transformation_run_id"]
    artifact = run_generation(client, transformation_id, factory, provider).json()["artifacts"][0]
    artifact_version_id = artifact["artifact_version"]["id"]
    with factory() as session:
        version = session.get(ArtifactVersion, artifact_version_id)
        assert version is not None
        attach_dependency(session, version, block_key="paragraph:1")
        session.commit()

    updated = client.post(
        f"/api/transformations/{transformation_id}/source-versions",
        json={
            "source_text": (
                "Notice.\n\nVisitors enter on Maple Street.\n\nVisitors enter on Maple Street."
            )
        },
    )
    assert updated.status_code == 200
    impact = next(
        item
        for item in updated.json()["potentially_affected_artifacts"]
        if item["artifact_version_id"] == artifact_version_id
    )
    assert impact["impact_state"] == "needs_review"
    assert impact["review_block_keys"] == ["paragraph:1"]
    assert impact["targeted_update_available"] is False
    blocked = client.post(f"/api/artifact-runs/{artifact['artifact_run_id']}/targeted-update")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "targeted_update_requires_review"
