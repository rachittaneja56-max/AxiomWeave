import json
from typing import cast

from auth_support import login
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.evidence import get_analysis_provider
from app.api.generation import get_generation_provider
from app.api.revisions import get_revision_provider
from app.generation import (
    GenerationProviderError,
    GenerationRequest,
    GenerationResult,
    StructuredGenerationResult,
)
from app.models import ArtifactVersion, SourceVersion, TransformationRun
from app.presentation import PresentationSpec, SlideSpec


class AcceptanceProvider:
    def __init__(self) -> None:
        self.presentation_attempts = 0

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        if "Executive Summary" in request.transformation_instructions:
            text = "The center opened Saturday."
        elif "LinkedIn post" in request.transformation_instructions:
            text = "The center opened Sunday."
        else:
            text = "Visitors can enter on Maple Street."
        return GenerationResult(text=text, provider="fixture", model="deterministic")

    async def generate_structured[T: BaseModel](
        self, request: GenerationRequest, response_model: type[T]
    ) -> StructuredGenerationResult[T]:
        from app.api.evidence import ClaimEvidenceProposal, DiscrepancyAnalysis, EvidenceAnalysis
        from app.api.revisions import TargetedArtifactContent

        if response_model is PresentationSpec:
            self.presentation_attempts += 1
            if self.presentation_attempts == 1:
                raise GenerationProviderError()
            value: BaseModel = PresentationSpec(
                title="Community Center Update",
                slides=[
                    SlideSpec(
                        title="Opening",
                        key_message="The center opens Saturday.",
                        bullets=["Opening day is Saturday."],
                        visual_recommendation="A calendar highlighting Saturday.",
                        speaker_notes="Welcome visitors and explain the opening date.",
                    ),
                    SlideSpec(
                        title="Arrival",
                        key_message="Visitors can use Maple Street.",
                        bullets=["Use the Maple Street entrance."],
                        visual_recommendation="A map marker at Maple Street.",
                        speaker_notes="Point out the visitor entrance.",
                    ),
                ],
            )
        elif response_model is EvidenceAnalysis:
            value = EvidenceAnalysis(
                proposals=[
                    ClaimEvidenceProposal(
                        claim_text="The center opened Saturday.",
                        proposed_quote="The community center opened on Saturday.",
                    ),
                    ClaimEvidenceProposal(
                        claim_text="The center has free parking.",
                        proposed_quote="The center has free parking.",
                    ),
                ]
            )
        elif response_model is DiscrepancyAnalysis:
            value = DiscrepancyAnalysis(
                possible_discrepancy=True,
                statement_a="The center opened Saturday.",
                statement_b="The center opened Sunday.",
                discrepancy_type="date_conflict",
                explanation="The sibling artifacts give different opening days.",
            )
        elif response_model is TargetedArtifactContent:
            value = TargetedArtifactContent(content="The center opens Sunday.")
        else:
            value = response_model.model_validate({"content": "Updated from V2."})
        return StructuredGenerationResult(
            value=cast(T, value), provider="fixture", model="deterministic"
        )


def test_tier_a_acceptance_workflow(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client, "acceptance-owner")
    provider = AcceptanceProvider()
    from app.main import app

    app.dependency_overrides[get_generation_provider] = lambda: provider
    app.dependency_overrides[get_revision_provider] = lambda: provider
    app.dependency_overrides[get_analysis_provider] = lambda: provider

    saved = client.post(
        "/api/transformations",
        json={
            "source_text": (
                "The community center opened on Saturday.\n\nVisitors can enter on Maple Street."
            ),
            "supporting_context": "Use a welcoming, concise voice.",
            "output_types": ["executive_summary", "linkedin_post", "advisory", "presentation"],
            "audience": "Local residents",
            "tone": "Welcoming",
            "language": "English",
            "detail_level": "standard",
            "objective": "Announce the opening",
            "style": "Plain language",
        },
    )
    assert saved.status_code == 200
    transformation_id = saved.json()["transformation_run_id"]
    source_v1_id = saved.json()["source_version"]["id"]

    generated = client.post(f"/api/transformations/{transformation_id}/generate")
    assert generated.status_code == 200
    assert generated.json()["status"] == "partial_failure"
    artifacts = {item["output_type"]: item for item in generated.json()["artifacts"]}
    assert {name for name, item in artifacts.items() if item["status"] == "succeeded"} == {
        "executive_summary",
        "linkedin_post",
        "advisory",
    }
    assert artifacts["presentation"]["status"] == "failed"
    retried = client.post(
        f"/api/artifact-runs/{artifacts['presentation']['artifact_run_id']}/retry"
    )
    assert retried.status_code == 200
    assert retried.json()["status"] == "succeeded"
    assert json.loads(retried.json()["artifact_version"]["content"])["slides"][0]["speaker_notes"]

    summary_run = artifacts["executive_summary"]["artifact_run_id"]
    summary_v1_id = artifacts["executive_summary"]["artifact_version"]["id"]
    edited = client.post(
        f"/api/artifact-runs/{summary_run}/versions",
        json={"content": "The community center opened on Saturday. Edited for clarity."},
    )
    assert edited.status_code == 200
    summary_v2_id = edited.json()["id"]
    assert edited.json()["version_number"] == 2
    assert (
        client.patch(
            f"/api/artifact-versions/{summary_v2_id}/review", json={"review_status": "accepted"}
        ).json()["review_status"]
        == "accepted"
    )
    assert (
        client.patch(
            f"/api/artifact-versions/{artifacts['advisory']['artifact_version']['id']}/review",
            json={"review_status": "rejected"},
        ).status_code
        == 200
    )

    evidence = client.post(
        f"/api/artifact-versions/{summary_v2_id}/evidence/analyze",
        json={"source_version_id": source_v1_id},
    )
    assert evidence.status_code == 200
    assert [item["status"] for item in evidence.json()] == ["linked", "support_not_located"]
    assert client.get(f"/api/source-versions/{source_v1_id}").status_code == 200
    linked_quote = client.get(f"/api/artifact-versions/{summary_v2_id}/evidence").json()[0]
    assert linked_quote["source_quote"] == "The community center opened on Saturday."

    linkedin_v1_id = artifacts["linkedin_post"]["artifact_version"]["id"]
    discrepancy = client.post(
        "/api/discrepancies/analyze",
        json={"artifact_version_a_id": summary_v1_id, "artifact_version_b_id": linkedin_v1_id},
    )
    finding = discrepancy.json()["finding"]
    assert finding["review_status"] == "open"
    summary_before_dismissal = client.get(f"/api/transformations/{transformation_id}").json()
    dismissed = client.patch(
        f"/api/discrepancies/{finding['id']}", json={"review_status": "dismissed"}
    )
    assert dismissed.json()["review_status"] == "dismissed"
    assert (
        client.get(f"/api/transformations/{transformation_id}").json()["artifact_runs"]
        == summary_before_dismissal["artifact_runs"]
    )

    revision = client.post(
        f"/api/transformations/{transformation_id}/source-versions",
        json={
            "source_text": (
                "The community center opened on Sunday.\n\nVisitors can enter on Maple Street."
            )
        },
    )
    assert revision.status_code == 200
    revision_body = revision.json()
    source_v2_id = revision_body["source_version"]["id"]
    assert revision_body["changes"][0]["change_type"] == "changed"
    assert revision_body["changes"][0]["old_text"] == ("The community center opened on Saturday.")
    assert revision_body["changes"][0]["new_text"] == ("The community center opened on Sunday.")
    assert any(
        item["artifact_version_id"] == summary_v2_id
        for item in revision_body["potentially_affected_artifacts"]
    )
    with factory() as session:
        v1 = session.get(SourceVersion, source_v1_id)
        v2 = session.get(SourceVersion, source_v2_id)
        transformation = session.get(TransformationRun, transformation_id)
        original = session.get(ArtifactVersion, summary_v1_id)
        assert v1 is not None and v1.source_text.startswith(
            "The community center opened on Saturday."
        )
        assert v2 is not None and v2.parent_source_version_id == v1.id
        assert transformation is not None and transformation.source_version_id == v2.id
        assert original is not None and original.source_version_id == v1.id
        assert original.content == "The center opened Saturday."

    targeted = client.post(f"/api/artifact-runs/{summary_run}/targeted-update")
    assert targeted.status_code == 200
    assert targeted.json()["artifact_version"]["version_number"] == 3
    assert targeted.json()["artifact_version"]["source_version_id"] == source_v2_id
    regenerated = client.post(
        f"/api/artifact-runs/{artifacts['linkedin_post']['artifact_run_id']}/regenerate"
    )
    assert regenerated.status_code == 200
    assert regenerated.json()["artifact_version"]["source_version_id"] == source_v2_id
    assert client.get(f"/api/transformations/{transformation_id}").status_code == 200

    login(client, "unrelated-owner")
    assert client.get(f"/api/transformations/{transformation_id}").status_code == 404
    assert client.get(f"/api/source-versions/{source_v1_id}").status_code == 404
    assert client.get(f"/api/artifact-versions/{summary_v2_id}/evidence").status_code == 404
