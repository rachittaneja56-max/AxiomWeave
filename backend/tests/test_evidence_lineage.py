import json
from typing import TypeVar, cast

from auth_support import login
from fastapi.testclient import TestClient
from generation_support import run_generation
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.evidence import ClaimEvidenceProposal, EvidenceAnalysis, get_analysis_provider
from app.api.generation import get_generation_provider
from app.artifact_lineage import (
    LineageProposalItem,
    LineageProposalSet,
    validate_and_store_lineage_proposals,
)
from app.evidence_verifier import SemanticEvidenceItem, SemanticEvidenceResult
from app.generation import GenerationRequest, GenerationResult, StructuredGenerationResult
from app.main import app
from app.models import (
    ArtifactVersion,
    ContextManifestEntry,
    SourceAsset,
    SourcePackMembership,
    SourcePackVersion,
    SourceRegion,
    SourceVersion,
    User,
)

T = TypeVar("T", bound=BaseModel)

SOURCE_TEXT = (
    "The community center opened on Saturday. Visitors can enter on Maple Street. "
    "The community center has a welcome desk. The main hall has two floors."
)
ARTIFACT_CLAIMS = [
    "The center's opening is on Saturday.",
    "Visitors use the Maple Street entrance.",
    "The center has a welcome desk.",
    "The main hall has two floors.",
    "The center offers free parking.",
    "The center provides guided tours.",
    "Visitors can enter on Maple Street.",
    "Welcome to the community center.",
]
EVIDENCE_STATES = [
    "quote_located",
    "supported",
    "partial",
    "contradicted",
    "missing",
    "ambiguous",
    "conflict",
    "non_factual",
]


def integer_field(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise AssertionError(f"{key} must be an integer")
    return value


SOURCE_QUOTES = [
    "The community center opened on Saturday.",
    "Visitors can enter on Maple Street.",
    "The community center has a welcome desk.",
    "The main hall has two floors.",
    "",
    "The community center opened on Saturday.",
    "Visitors can enter on Maple Street.",
    "",
]


class PhaseFourProvider:
    supports_lineage = True
    supports_automatic_claim_scan = True

    def __init__(self, invalid_region_ids: list[int]) -> None:
        self.invalid_region_ids = invalid_region_ids

    async def generate(self, _request: GenerationRequest) -> GenerationResult:
        return GenerationResult(
            text="\n\n".join(ARTIFACT_CLAIMS), provider="fixture", model="deterministic"
        )

    async def generate_structured[TModel: BaseModel](
        self, request: GenerationRequest, response_model: type[TModel]
    ) -> StructuredGenerationResult[TModel]:

        if response_model is LineageProposalSet:
            regions: list[dict[str, object]] = json.loads(request.source_text)
            region_id = integer_field(regions[0], "region_id")
            region_text = str(regions[0]["text"])
            quote = "The community center opened on Saturday."
            start = region_text.index(quote)
            proposals = [
                LineageProposalItem(
                    block_key="paragraph:1",
                    claim_text=ARTIFACT_CLAIMS[0],
                    source_region_id=region_id,
                    source_quote=quote,
                    quote_start=start,
                    quote_end=start + len(quote),
                ),
                LineageProposalItem(
                    block_key="paragraph:1",
                    claim_text="Cross-owner region candidate.",
                    source_region_id=self.invalid_region_ids[0],
                    source_quote=quote,
                    quote_start=start,
                    quote_end=start + len(quote),
                ),
                LineageProposalItem(
                    block_key="paragraph:1",
                    claim_text="Outside-manifest region candidate.",
                    source_region_id=self.invalid_region_ids[1],
                    source_quote=quote,
                    quote_start=start,
                    quote_end=start + len(quote),
                ),
                LineageProposalItem(
                    block_key="paragraph:1",
                    claim_text="Missing region candidate.",
                    source_region_id=9_999_999,
                    source_quote=quote,
                    quote_start=start,
                    quote_end=start + len(quote),
                ),
                LineageProposalItem(
                    block_key="paragraph:1",
                    claim_text="Invalid exact span candidate.",
                    source_region_id=region_id,
                    source_quote="not a source quotation",
                    quote_start=0,
                    quote_end=5,
                ),
                LineageProposalItem(
                    block_key="paragraph:1",
                    claim_text="Invalid assertion candidate.",
                    source_region_id=region_id,
                    knowledge_assertion_id=9_999_999,
                    source_quote=quote,
                    quote_start=start,
                    quote_end=start + len(quote),
                ),
                LineageProposalItem(
                    block_key="other-artifact:paragraph:1",
                    claim_text="Unknown block candidate.",
                    source_region_id=region_id,
                    source_quote=quote,
                    quote_start=start,
                    quote_end=start + len(quote),
                ),
            ]
            value: BaseModel = LineageProposalSet(proposals=proposals)
        elif response_model is EvidenceAnalysis:
            value = EvidenceAnalysis(
                proposals=[
                    ClaimEvidenceProposal(
                        claim_text=claim,
                        artifact_quote=claim,
                    )
                    for claim in ARTIFACT_CLAIMS
                ],
                analysis_complete=True,
            )
        elif response_model is SemanticEvidenceResult:
            regions: list[dict[str, object]] = json.loads(request.source_text)
            claims: list[dict[str, object]] = json.loads(request.artifact_content)
            region_id = integer_field(regions[0], "region_id")
            region_text = str(regions[0]["text"])
            items: list[SemanticEvidenceItem] = []
            for claim in claims:
                proposition = str(claim["proposition"])
                claim_index = ARTIFACT_CLAIMS.index(proposition)
                state = EVIDENCE_STATES[claim_index]
                quote = SOURCE_QUOTES[claim_index]
                start = region_text.index(quote) if quote else None
                items.append(
                    SemanticEvidenceItem(
                        material_claim_id=integer_field(claim, "material_claim_id"),
                        evidence_state=state,  # type: ignore[arg-type]
                        source_region_id=region_id if quote else None,
                        source_quote=quote,
                        source_quote_start=start,
                        source_quote_end=start + len(quote) if start is not None else None,
                        reason_code=f"fixture_{state}",
                    )
                )
            value = SemanticEvidenceResult(complete=True, assessments=items)
        else:
            raise AssertionError(f"Unexpected structured model: {response_model.__name__}")
        return StructuredGenerationResult(
            value=cast(TModel, value), provider="fixture", model="deterministic"
        )


def create_transformation(client: TestClient, source_text: str, username: str) -> int:
    response = client.post(
        "/api/transformations",
        json={
            "source_text": source_text,
            "output_types": ["advisory"],
            "audience": "community members",
            "tone": "clear",
            "language": "English",
            "detail_level": "standard",
            "objective": "inform",
            "style": "plain language",
        },
    )
    assert response.status_code == 200, f"{username}: {response.text}"
    return response.json()["transformation_run_id"]


def region_for_source(session: Session, source_version_id: int) -> SourceRegion:
    pack_version = session.scalar(
        select(SourcePackVersion).where(SourcePackVersion.source_version_id == source_version_id)
    )
    assert pack_version is not None
    region = session.scalar(
        select(SourceRegion)
        .join(SourceAsset, SourceAsset.id == SourceRegion.source_asset_id)
        .join(SourcePackMembership, SourcePackMembership.source_asset_id == SourceAsset.id)
        .where(SourcePackMembership.source_pack_version_id == pack_version.id)
    )
    assert region is not None
    return region


def test_lineage_validation_evidence_states_and_human_adjudication(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    owner_cookie = login(client, "lineage-owner")
    same_owner_external_id = create_transformation(
        client, "A region in a different source pack.", "lineage-owner"
    )
    target_transformation_id = create_transformation(client, SOURCE_TEXT, "lineage-owner")

    other_owner_cookie = login(client, "lineage-other-owner")
    other_owner_external_id = create_transformation(
        client, "A private region owned by someone else.", "lineage-other-owner"
    )
    with factory() as session:
        same_owner_version_id = session.scalar(
            select(SourceVersion.id)
            .join(ArtifactVersion, ArtifactVersion.source_version_id == SourceVersion.id)
            .where(SourceVersion.id < 0)
        )
        assert same_owner_version_id is None
        same_owner_source_id = session.scalar(
            select(SourceVersion.id).where(
                SourceVersion.source_text == "A region in a different source pack."
            )
        )
        other_owner_source_id = session.scalar(
            select(SourceVersion.id).where(
                SourceVersion.source_text == "A private region owned by someone else."
            )
        )
        assert same_owner_source_id is not None and other_owner_source_id is not None
        same_owner_region_id = region_for_source(session, same_owner_source_id).id
        other_owner_region_id = region_for_source(session, other_owner_source_id).id

    _ = same_owner_external_id, other_owner_external_id
    client.cookies.set("axiomweave_session", owner_cookie)
    provider = PhaseFourProvider([other_owner_region_id, same_owner_region_id])
    app.dependency_overrides[get_generation_provider] = lambda: provider
    app.dependency_overrides[get_analysis_provider] = lambda: provider
    transformation_id = target_transformation_id
    generated = run_generation(client, transformation_id, factory, provider)
    assert generated.json()["status"] == "succeeded"
    artifact = generated.json()["artifacts"][0]
    version_id = artifact["artifact_version"]["id"]

    coverage = client.get(f"/api/artifact-versions/{version_id}/claim-scan").json()
    assert coverage["status"] == "complete"
    assert coverage["claims_found"] == 8
    assert coverage["completed_batches"] == coverage["total_batches"] == 1

    lineage = client.get(f"/api/artifact-versions/{version_id}/lineage").json()
    assert lineage["lineage_available"] is True
    validated = [item for item in lineage["proposals"] if item["validation_state"] == "validated"]
    rejected = [item for item in lineage["proposals"] if item["validation_state"] != "validated"]
    assert len(validated) == 1
    assert len(rejected) == 6
    assert validated[0]["material_claim_id"] is not None
    assert {item["validation_state"] for item in rejected} == {
        "invalid_scope",
        "invalid_region",
        "invalid_span",
        "invalid_assertion",
        "unresolved",
    }

    assessed = client.post(f"/api/artifact-versions/{version_id}/evidence/verify")
    assert assessed.status_code == 200, assessed.text
    assessments = assessed.json()
    assert len(assessments) == 8
    propositions = {item["id"]: item["proposition"] for item in lineage["claims"]}
    assessed_by_proposition = {
        propositions[item["material_claim_id"]]: item["evidence_state"] for item in assessments
    }
    actual_states = [assessed_by_proposition[claim] for claim in ARTIFACT_CLAIMS]
    assert actual_states == EVIDENCE_STATES
    assert {item["assessment_method"] for item in assessments} == {"semantic_verifier"}
    assert all(item["review_state"] == "needs_review" for item in assessments)

    contradicted = next(item for item in assessments if item["evidence_state"] == "contradicted")
    client.cookies.set("axiomweave_session", other_owner_cookie)
    assert client.get(f"/api/artifact-versions/{version_id}/lineage").status_code == 404
    assert (
        client.patch(
            f"/api/claim-evidence-assessments/{contradicted['id']}/review",
            json={"adjudicated_state": "supported"},
        ).status_code
        == 404
    )

    client.cookies.set("axiomweave_session", owner_cookie)
    reviewed = client.patch(
        f"/api/claim-evidence-assessments/{contradicted['id']}/review",
        json={"adjudicated_state": "supported"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["evidence_state"] == "contradicted"
    assert reviewed.json()["assessment_method"] == "semantic_verifier"
    assert reviewed.json()["adjudicated_state"] == "supported"
    assert reviewed.json()["review_state"] == "reviewed"

    with factory() as session:
        artifact_version = session.get(ArtifactVersion, version_id)
        owner = session.scalar(select(User).where(User.username == "lineage_owner"))
        assert artifact_version is not None and artifact_version.context_manifest_id is not None
        assert owner is not None
        entry = session.scalar(
            select(ContextManifestEntry).where(
                ContextManifestEntry.context_manifest_id == artifact_version.context_manifest_id,
                ContextManifestEntry.selected.is_(True),
            )
        )
        assert entry is not None
        membership = session.get(SourcePackMembership, entry.membership_id)
        region = session.get(SourceRegion, entry.source_region_id)
        assert membership is not None and region is not None and region.text is not None
        source_regions = list(
            session.scalars(
                select(SourceRegion).where(SourceRegion.source_asset_id == entry.source_asset_id)
            )
        )
        disallowed_region = SourceRegion(
            source_asset_id=entry.source_asset_id,
            ordinal=max(item.ordinal for item in source_regions) + 1,
            locator="disallowed-role-test",
            region_type="paragraph",
            text=region.text,
        )
        session.add(disallowed_region)
        session.flush()
        disallowed_entry = ContextManifestEntry(
            context_manifest_id=artifact_version.context_manifest_id,
            source_region_id=disallowed_region.id,
            source_asset_id=entry.source_asset_id,
            membership_id=membership.id,
            role="STYLE",
            selected=True,
            locator=disallowed_region.locator,
            content_hash=entry.content_hash,
            estimated_context_units=len(region.text),
            reason="disallowed_role_test",
        )
        session.add(disallowed_entry)
        session.flush()
        disallowed_role_proposal = validate_and_store_lineage_proposals(
            session,
            owner,
            artifact_version,
            [
                LineageProposalItem(
                    block_key="paragraph:1",
                    claim_text="Disallowed source role candidate.",
                    source_region_id=disallowed_region.id,
                    source_quote=region.text,
                    quote_start=0,
                    quote_end=len(region.text),
                )
            ],
        )[0]
        assert disallowed_role_proposal.validation_state == "invalid_scope"
        session.commit()
