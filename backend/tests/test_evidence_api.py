from typing import TypeVar

from auth_support import login
from fastapi.testclient import TestClient
from generation_support import run_generation
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.evidence import get_analysis_provider
from app.api.generation import get_generation_provider
from app.generation import (
    GenerationProviderError,
    GenerationRequest,
    GenerationResult,
    StructuredGenerationResult,
)
from app.models import ArtifactRun, ArtifactVersion, DiscrepancyFinding, EvidenceLink

T = TypeVar("T", bound=BaseModel)


class FakeGenerationProvider:
    def __init__(self) -> None:
        self.count = 0

    async def generate(self, _request: GenerationRequest) -> GenerationResult:
        self.count += 1
        text = (
            "The community center opened on Saturday."
            if self.count == 1
            else "The community center opened on Sunday."
        )
        return GenerationResult(text=text, provider="test", model="fixture")


class FakeAnalysisProvider:
    def __init__(self, values: list[BaseModel] | None = None, *, fail: bool = False) -> None:
        self.values = values or []
        self.fail = fail

    async def generate_structured[TModel: BaseModel](
        self, _request: GenerationRequest, response_model: type[TModel]
    ) -> StructuredGenerationResult[TModel]:
        if self.fail:
            raise GenerationProviderError()
        value = self.values.pop(0)
        return StructuredGenerationResult(
            value=response_model.model_validate(value.model_dump()),
            provider="test",
            model="fixture",
        )


def set_providers(generation: FakeGenerationProvider, analysis: FakeAnalysisProvider) -> None:
    from app.main import app

    app.dependency_overrides[get_generation_provider] = lambda: generation
    app.dependency_overrides[get_analysis_provider] = lambda: analysis


def create_sibling_artifacts(
    client: TestClient, factory: sessionmaker[Session]
) -> tuple[int, int, int, int]:
    response = client.post(
        "/api/transformations",
        json={
            "source_text": (
                "The community center opened on Saturday.\n\nVisitors can enter on Maple Street."
            ),
            "supporting_context": "Keep claims source-grounded.",
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
    transformation_id = response.json()["transformation_run_id"]
    generated = run_generation(client, transformation_id, factory)
    assert generated.status_code == 200
    artifacts = generated.json()["artifacts"]
    return (
        transformation_id,
        response.json()["source_version"]["id"],
        artifacts[0]["artifact_version"]["id"],
        artifacts[1]["artifact_version"]["id"],
    )


def test_evidence_quotes_are_verified_against_the_exact_source_version(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    from app.api.evidence import ClaimEvidenceProposal, EvidenceAnalysis

    client, _engine, factory = auth_database
    login(client)
    set_providers(
        FakeGenerationProvider(),
        FakeAnalysisProvider(
            [
                EvidenceAnalysis(
                    proposals=[
                        ClaimEvidenceProposal(
                            claim_text="The center opened Saturday.",
                            proposed_quote="The community center opened on Saturday.",
                        ),
                        ClaimEvidenceProposal(
                            claim_text="The center has free parking.",
                            proposed_quote="The center has free parking.",
                        ),
                        ClaimEvidenceProposal(
                            claim_text="The source omits an opening time.",
                            proposed_quote="",
                        ),
                    ]
                )
            ]
        ),
    )
    _transformation_id, source_version_id, artifact_version_id, _sibling_id = (
        create_sibling_artifacts(client, factory)
    )

    response = client.post(
        f"/api/artifact-versions/{artifact_version_id}/evidence/analyze",
        json={"source_version_id": source_version_id},
    )

    assert response.status_code == 200
    evidence = response.json()
    assert evidence[0]["status"] == "linked"
    assert evidence[0]["source_quote"] == "The community center opened on Saturday."
    assert evidence[0]["source_locator"] == "paragraph:1"
    assert evidence[1]["status"] == "support_not_located"
    assert evidence[1]["source_quote"] is None
    assert evidence[1]["source_locator"] is None
    assert evidence[2]["status"] == "support_not_located"
    with factory() as session:
        rows = list(session.scalars(select(EvidenceLink).order_by(EvidenceLink.id)))
        assert [row.status for row in rows] == [
            "linked",
            "support_not_located",
            "support_not_located",
        ]


def test_wrong_source_is_rejected_and_analysis_failure_leaves_artifact_unchanged(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    from app.api.evidence import EvidenceAnalysis

    client, _engine, factory = auth_database
    login(client)
    set_providers(FakeGenerationProvider(), FakeAnalysisProvider([EvidenceAnalysis(proposals=[])]))
    transformation_id, source_version_id, artifact_version_id, _sibling_id = (
        create_sibling_artifacts(client, factory)
    )
    other = client.post(
        "/api/transformations",
        json={
            "source_text": "A different source version.",
            "output_types": ["executive_summary"],
            "audience": "readers",
            "tone": "clear",
            "language": "English",
            "detail_level": "standard",
            "objective": "inform",
            "style": "plain language",
        },
    )
    other_source_version_id = other.json()["source_version"]["id"]
    other_transformation_id = other.json()["transformation_run_id"]
    other_generated = run_generation(client, other_transformation_id, factory).json()
    other_artifact_version_id = other_generated["artifacts"][0]["artifact_version"]["id"]
    mismatch = client.post(
        f"/api/artifact-versions/{artifact_version_id}/evidence/analyze",
        json={"source_version_id": other_source_version_id},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "source_version_mismatch"
    cross_source_comparison = client.post(
        "/api/discrepancies/analyze",
        json={
            "artifact_version_a_id": artifact_version_id,
            "artifact_version_b_id": other_artifact_version_id,
        },
    )
    assert cross_source_comparison.status_code == 409
    assert cross_source_comparison.json()["error"]["code"] == "incompatible_artifacts"

    with factory() as session:
        version_before = session.get(ArtifactVersion, artifact_version_id)
        assert version_before is not None
        content_before = version_before.content
        run_id = version_before.artifact_run_id
        run_before = session.get(ArtifactRun, run_id)
        assert run_before is not None
        status_before = run_before.status
    set_providers(FakeGenerationProvider(), FakeAnalysisProvider(fail=True))
    failed = client.post(
        f"/api/artifact-versions/{artifact_version_id}/evidence/analyze",
        json={"source_version_id": source_version_id},
    )
    assert failed.status_code == 502
    assert failed.json()["error"]["code"] == "evidence_analysis_failed"
    with factory() as session:
        version_after = session.get(ArtifactVersion, artifact_version_id)
        assert version_after is not None
        assert version_after.content == content_before
        run_after = session.get(ArtifactRun, run_id)
        assert run_after is not None
        assert run_after.status == status_before
    assert client.get(f"/api/transformations/{transformation_id}").status_code == 200


def test_sibling_discrepancy_is_advisory_and_dismissal_only_changes_review_state(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    from app.api.evidence import DiscrepancyAnalysis

    client, _engine, factory = auth_database
    login(client)
    set_providers(
        FakeGenerationProvider(),
        FakeAnalysisProvider(
            [
                DiscrepancyAnalysis(
                    possible_discrepancy=True,
                    statement_a="The center opened on Saturday.",
                    statement_b="The center opened on Sunday.",
                    discrepancy_type="opening_date",
                    explanation="The two outputs state different opening days.",
                )
            ]
        ),
    )
    _transformation_id, _source_version_id, version_a_id, version_b_id = create_sibling_artifacts(
        client, factory
    )
    response = client.post(
        "/api/discrepancies/analyze",
        json={
            "artifact_version_a_id": version_a_id,
            "artifact_version_b_id": version_b_id,
        },
    )
    assert response.status_code == 200
    finding = response.json()["finding"]
    assert finding["review_status"] == "open"
    assert finding["statement_a"] == "The center opened on Saturday."
    assert finding["statement_b"] == "The center opened on Sunday."
    with factory() as session:
        versions_before = [
            session.get(ArtifactVersion, version_id) for version_id in (version_a_id, version_b_id)
        ]
        assert all(version is not None for version in versions_before)
        before = [version.content for version in versions_before if version is not None]

    dismissed = client.patch(
        f"/api/discrepancies/{finding['id']}", json={"review_status": "dismissed"}
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["review_status"] == "dismissed"
    with factory() as session:
        versions_after = [
            session.get(ArtifactVersion, version_id) for version_id in (version_a_id, version_b_id)
        ]
        assert all(version is not None for version in versions_after)
        after = [version.content for version in versions_after if version is not None]
        stored = session.get(DiscrepancyFinding, finding["id"])
        assert stored is not None
        assert stored.statement_a == "The center opened on Saturday."
        assert stored.review_status == "dismissed"
    assert before == after


def test_sibling_discrepancy_provider_failure_is_safe_502(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    set_providers(FakeGenerationProvider(), FakeAnalysisProvider(fail=True))
    _transformation_id, _source_version_id, version_a_id, version_b_id = create_sibling_artifacts(
        client, factory
    )

    response = client.post(
        "/api/discrepancies/analyze",
        json={
            "artifact_version_a_id": version_a_id,
            "artifact_version_b_id": version_b_id,
        },
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "discrepancy_analysis_failed"
    assert response.json()["error"]["message"] == "Discrepancy analysis failed."


def test_equivalent_paraphrases_create_no_discrepancy_and_cross_user_access_is_denied(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    from app.api.evidence import DiscrepancyAnalysis, EvidenceAnalysis

    client, _engine, factory = auth_database
    login(client, "first-owner")
    set_providers(
        FakeGenerationProvider(),
        FakeAnalysisProvider(
            [DiscrepancyAnalysis(possible_discrepancy=False), EvidenceAnalysis(proposals=[])]
        ),
    )
    _transformation_id, source_version_id, version_a_id, version_b_id = create_sibling_artifacts(
        client, factory
    )
    equivalent = client.post(
        "/api/discrepancies/analyze",
        json={
            "artifact_version_a_id": version_a_id,
            "artifact_version_b_id": version_b_id,
        },
    )
    assert equivalent.status_code == 200
    assert equivalent.json()["finding"] is None

    login(client, "second-owner")
    assert client.get(f"/api/source-versions/{source_version_id}").status_code == 404
    assert client.get(f"/api/artifact-versions/{version_a_id}/evidence").status_code == 404
    assert client.get(f"/api/artifact-versions/{version_a_id}/discrepancies").status_code == 404
    denied = client.post(
        f"/api/artifact-versions/{version_a_id}/evidence/analyze",
        json={"source_version_id": source_version_id},
    )
    assert denied.status_code == 404
