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
    StructuredGenerationProvider,
    StructuredGenerationResult,
)
from app.models import (
    ArtifactRun,
    ArtifactVersion,
    ClaimBatch,
    ContextManifestEntry,
    DiscrepancyFinding,
    EvidenceLink,
    KnowledgeAssertion,
    KnowledgeRelation,
    MaterialClaim,
    Source,
    SourceRegion,
    User,
)
from app.source_versions import create_source_version

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
        self, request: GenerationRequest, response_model: type[TModel]
    ) -> StructuredGenerationResult[TModel]:
        _ = request
        if self.fail:
            raise GenerationProviderError()
        value = self.values.pop(0)
        return StructuredGenerationResult(
            value=response_model.model_validate(value.model_dump()),
            provider="test",
            model="fixture",
        )


def set_providers(
    generation: FakeGenerationProvider, analysis: StructuredGenerationProvider
) -> None:
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


class BatchClaimProvider:
    def __init__(self, claims: list[str], *, fail_ordinal: int | None = None) -> None:
        self.claims = claims
        self.fail_ordinal = fail_ordinal
        self.calls: list[int] = []

    async def generate_structured[TModel: BaseModel](
        self, request: GenerationRequest, response_model: type[TModel]
    ) -> StructuredGenerationResult[TModel]:
        import re

        from app.api.evidence import ClaimEvidenceProposal, EvidenceAnalysis

        ordinal_match = re.search(r"batch (\d+) of", request.transformation_instructions)
        ordinal = int(ordinal_match.group(1)) if ordinal_match else 1
        self.calls.append(ordinal)
        if ordinal == self.fail_ordinal:
            raise GenerationProviderError()
        proposals: list[ClaimEvidenceProposal] = []
        for claim in self.claims:
            start = request.artifact_content.find(claim)
            if start < 0:
                continue
            proposals.append(
                ClaimEvidenceProposal(
                    claim_text=claim,
                    proposed_quote=claim,
                    artifact_quote=claim,
                    artifact_start=start,
                    artifact_end=start + len(claim),
                )
            )
        value = EvidenceAnalysis(proposals=proposals, analysis_complete=True)
        return StructuredGenerationResult(
            value=response_model.model_validate(value.model_dump()),
            provider="test",
            model="batch-fixture",
        )


def _artifact_with_content(
    client: TestClient,
    factory: sessionmaker[Session],
    source_text: str,
    artifact_content: str,
    analysis_provider: BatchClaimProvider,
) -> tuple[int, int]:
    set_providers(FakeGenerationProvider(), analysis_provider)
    saved = client.post(
        "/api/transformations",
        json={
            "source_text": source_text,
            "output_types": ["advisory"],
            "audience": "readers",
            "tone": "clear",
            "language": "English",
            "detail_level": "standard",
            "objective": "inform",
            "style": "plain language",
        },
    )
    assert saved.status_code == 200
    generated = run_generation(client, saved.json()["transformation_run_id"], factory)
    assert generated.status_code == 200
    artifact_version_id = generated.json()["artifacts"][0]["artifact_version"]["id"]
    source_version_id = saved.json()["source_version"]["id"]
    with factory() as session:
        version = session.get(ArtifactVersion, artifact_version_id)
        assert version is not None
        version.content = artifact_content
        session.commit()
    return source_version_id, artifact_version_id


def test_material_claim_scan_persists_more_than_eight_and_reports_denominator(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    claims = [f"Claim {number} occurred in {2010 + number}." for number in range(1, 13)]
    provider = BatchClaimProvider(claims)
    source_version_id, artifact_version_id = _artifact_with_content(
        client, factory, "\n\n".join(claims), "\n\n".join(claims), provider
    )

    response = client.post(
        f"/api/artifact-versions/{artifact_version_id}/evidence/analyze",
        json={"source_version_id": source_version_id},
    )

    assert response.status_code == 200
    assert len(response.json()) == 12
    coverage = client.get(f"/api/artifact-versions/{artifact_version_id}/claim-scan")
    assert coverage.status_code == 200
    assert coverage.json()["status"] == "complete"
    assert coverage.json()["total_batches"] == 1
    assert coverage.json()["completed_batches"] == 1
    assert coverage.json()["claims_found"] == 12
    assertions = client.get(f"/api/artifact-versions/{artifact_version_id}/assertions")
    assert assertions.status_code == 200
    assert len(assertions.json()) == 12
    assert all(item["provenance_state"] == "validated" for item in assertions.json())
    assert all(item["review_state"] == "needs_review" for item in assertions.json())
    with factory() as session:
        assertion_rows = list(
            session.scalars(
                select(KnowledgeAssertion)
                .where(KnowledgeAssertion.source_pack_version_id.is_not(None))
                .order_by(KnowledgeAssertion.id)
            )
        )
        owner_id = assertion_rows[0].owner_id
        relation = KnowledgeRelation(
            owner_id=owner_id,
            source_assertion_id=assertion_rows[0].id,
            target_assertion_id=assertion_rows[1].id,
            relation_kind="same_event",
            extraction_profile="manual_test_fixture",
            extraction_profile_version=1,
            review_state="needs_review",
        )
        session.add(relation)
        session.commit()
        assert session.get(KnowledgeRelation, relation.id) is not None
    login(client, "other-assertion-owner")
    assert client.get(f"/api/artifact-versions/{artifact_version_id}/assertions").status_code == 404


def test_claim_scan_failure_is_visible_and_resume_only_retries_incomplete_batches(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    claims = [f"Claim {number} occurred." for number in range(1, 5)]
    paragraphs = [claim + " " + ("background " * 140) for claim in claims]
    artifact_content = "\n\n".join(paragraphs)
    first_provider = BatchClaimProvider(claims, fail_ordinal=2)
    source_version_id, artifact_version_id = _artifact_with_content(
        client,
        factory,
        "\n\n".join(claims),
        artifact_content,
        first_provider,
    )

    failed = client.post(
        f"/api/artifact-versions/{artifact_version_id}/evidence/analyze",
        json={"source_version_id": source_version_id},
    )
    assert failed.status_code == 502
    coverage = client.get(f"/api/artifact-versions/{artifact_version_id}/claim-scan").json()
    assert coverage["status"] == "failed"
    assert coverage["total_batches"] == 4
    assert coverage["completed_batches"] == 1
    assert coverage["failed_batches"] == 1
    assert coverage["claims_found"] == 1
    scan_id = coverage["id"]

    retry_provider = BatchClaimProvider(claims)
    set_providers(FakeGenerationProvider(), retry_provider)
    resumed = client.post(f"/api/claim-scans/{scan_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "complete"
    assert resumed.json()["completed_batches"] == 4
    assert resumed.json()["claims_found"] == 4
    assert retry_provider.calls == [2, 3, 4]
    with factory() as session:
        batches = list(
            session.scalars(
                select(ClaimBatch)
                .where(ClaimBatch.claim_scan_id == scan_id)
                .order_by(ClaimBatch.ordinal)
            )
        )
        claims_found = list(
            session.scalars(select(MaterialClaim).where(MaterialClaim.claim_scan_id == scan_id))
        )
    assert [batch.attempt_count for batch in batches] == [1, 2, 1, 1]
    assert len(claims_found) == 4


def test_model_region_id_cannot_create_cross_pack_assertion_and_bad_span_is_unresolved(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    claim = "The station opened in 2022."
    provider = BatchClaimProvider([claim])
    source_version_id, artifact_version_id = _artifact_with_content(
        client, factory, claim, claim, provider
    )
    with factory() as session:
        other_owner = User(username="other-owner", password_hash="!test!")
        session.add(other_owner)
        session.flush()
        other_source = Source(owner_id=other_owner.id, title="Other owner's source")
        session.add(other_source)
        session.flush()
        other_version = create_source_version(session, other_source, claim)
        region_id = session.scalar(select(SourceRegion.id).order_by(SourceRegion.id.desc()))
        assert region_id is not None
        assert other_version.id > source_version_id
        session.commit()

    from app.api.evidence import ClaimEvidenceProposal, EvidenceAnalysis

    class InvalidIdProvider(BatchClaimProvider):
        async def generate_structured[TModel: BaseModel](
            self, request: GenerationRequest, response_model: type[TModel]
        ) -> StructuredGenerationResult[TModel]:
            start = request.artifact_content.find(claim)
            value = EvidenceAnalysis(
                proposals=[
                    ClaimEvidenceProposal(
                        claim_text=claim,
                        proposed_quote=claim,
                        artifact_quote=claim,
                        artifact_start=start,
                        artifact_end=start + len(claim),
                        source_region_id=region_id,
                    )
                ]
            )
            return StructuredGenerationResult(
                value=response_model.model_validate(value.model_dump()),
                provider="test",
                model="invalid-region-id",
            )

    set_providers(FakeGenerationProvider(), InvalidIdProvider([claim]))
    response = client.post(
        f"/api/artifact-versions/{artifact_version_id}/evidence/analyze",
        json={"source_version_id": source_version_id},
    )
    assert response.status_code == 200
    assert (
        client.get(f"/api/artifact-versions/{artifact_version_id}/claim-scan").json()["status"]
        == "needs_review"
    )
    assertions = client.get(f"/api/artifact-versions/{artifact_version_id}/assertions").json()
    assert len(assertions) == 1
    assert assertions[0]["knowledge_assertion_id"] is None
    assert assertions[0]["provenance_state"] is None

    with factory() as session:
        artifact_version = session.get(ArtifactVersion, artifact_version_id)
        assert artifact_version is not None and artifact_version.context_manifest_id is not None
        manifest_entry = session.scalar(
            select(ContextManifestEntry).where(
                ContextManifestEntry.context_manifest_id == artifact_version.context_manifest_id,
                ContextManifestEntry.selected.is_(True),
            )
        )
        assert manifest_entry is not None
        asset_regions = list(
            session.scalars(
                select(SourceRegion).where(
                    SourceRegion.source_asset_id == manifest_entry.source_asset_id
                )
            )
        )
        excluded_region = SourceRegion(
            source_asset_id=manifest_entry.source_asset_id,
            ordinal=max(region.ordinal for region in asset_regions) + 1,
            locator="post-manifest-added-region",
            region_type="paragraph",
            text=claim,
        )
        session.add(excluded_region)
        session.commit()
        excluded_region_id = excluded_region.id

    class ExcludedRegionProvider(BatchClaimProvider):
        async def generate_structured[TModel: BaseModel](
            self, request: GenerationRequest, response_model: type[TModel]
        ) -> StructuredGenerationResult[TModel]:
            start = request.artifact_content.find(claim)
            value = EvidenceAnalysis(
                proposals=[
                    ClaimEvidenceProposal(
                        claim_text=claim,
                        proposed_quote=claim,
                        artifact_quote=claim,
                        artifact_start=start,
                        artifact_end=start + len(claim),
                        source_region_id=excluded_region_id,
                    )
                ],
                analysis_complete=True,
            )
            return StructuredGenerationResult(
                value=response_model.model_validate(value.model_dump()),
                provider="test",
                model="excluded-context-region",
            )

    scan_id = client.get(f"/api/artifact-versions/{artifact_version_id}/claim-scan").json()["id"]
    set_providers(FakeGenerationProvider(), ExcludedRegionProvider([claim]))
    resumed = client.post(f"/api/claim-scans/{scan_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "needs_review"
    assertions = client.get(f"/api/artifact-versions/{artifact_version_id}/assertions").json()
    assert assertions[0]["knowledge_assertion_id"] is None
    assert assertions[0]["provenance_state"] is None


def test_invalid_exact_source_offsets_create_unresolved_candidate_assertion(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    claim = "The station opened in 2022."
    source_version_id, artifact_version_id = _artifact_with_content(
        client, factory, claim, claim, BatchClaimProvider([claim])
    )
    with factory() as session:
        region_id = session.scalar(select(SourceRegion.id).order_by(SourceRegion.id.desc()))
        assert region_id is not None

    from app.api.evidence import ClaimEvidenceProposal, EvidenceAnalysis

    class InvalidOffsetsProvider(BatchClaimProvider):
        async def generate_structured[TModel: BaseModel](
            self, request: GenerationRequest, response_model: type[TModel]
        ) -> StructuredGenerationResult[TModel]:
            start = request.artifact_content.find(claim)
            value = EvidenceAnalysis(
                proposals=[
                    ClaimEvidenceProposal(
                        claim_text=claim,
                        proposed_quote=claim,
                        artifact_quote=claim,
                        artifact_start=start,
                        artifact_end=start + len(claim),
                        source_region_id=region_id,
                        source_quote_start=1,
                        source_quote_end=len(claim) + 1,
                    )
                ]
            )
            return StructuredGenerationResult(
                value=response_model.model_validate(value.model_dump()),
                provider="test",
                model="invalid-source-offsets",
            )

    set_providers(FakeGenerationProvider(), InvalidOffsetsProvider([claim]))
    response = client.post(
        f"/api/artifact-versions/{artifact_version_id}/evidence/analyze",
        json={"source_version_id": source_version_id},
    )
    assert response.status_code == 200
    assertions = client.get(f"/api/artifact-versions/{artifact_version_id}/assertions")
    assert assertions.status_code == 200
    assert assertions.json()[0]["provenance_state"] == "unresolved"
    assert assertions.json()[0]["source_quote_start"] is None
    assert assertions.json()[0]["source_quote_end"] is None
    assert assertions.json()[0]["review_state"] == "needs_review"
