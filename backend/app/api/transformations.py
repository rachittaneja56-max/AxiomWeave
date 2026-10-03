from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.artifact_contracts import ARTIFACT_CONTRACTS
from app.audit import record_audit_event
from app.auth import require_current_user
from app.claim_scanning import claim_scan_coverage
from app.commands import CreateTransformationCommand, dispatch_manual_application_command
from app.database import get_db_session
from app.domain.transformation import (
    CreateTransformationRequest,
    OutputType,
    PreparedTransformationRequest,
    TransformationRequest,
)
from app.models import (
    ArtifactRun,
    ArtifactVersion,
    ClaimScan,
    ContextManifest,
    ContextManifestEntry,
    Job,
    MediaRightsRecord,
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
)
from app.source_versions import create_source_pack_version, create_source_version

router = APIRouter()

_OUTPUT_TYPES = frozenset(output_type.value for output_type in ARTIFACT_CONTRACTS)
_ARTIFACT_STATUSES = ("pending", "running", "succeeded", "failed")


class SourceVersionSummary(BaseModel):
    id: int
    version_number: int
    content_hash: str
    created_at: datetime


class DashboardArtifactState(BaseModel):
    output_type: OutputType
    status: Literal["pending", "running", "succeeded", "failed"] | None
    latest_version_number: int | None
    review_status: Literal["draft", "accepted", "rejected"] | None


class ContextManifestSummary(BaseModel):
    id: int
    source_version_id: int
    source_pack_version_id: int
    route: str
    context_profile: str
    state: str
    extraction_coverage: str
    estimated_context_units: int
    context_budget_units: int
    region_count: int
    warnings: list[str]
    created_at: datetime


class ClaimScanSummary(BaseModel):
    id: int
    status: Literal["pending", "running", "complete", "failed", "needs_review"]
    total_batches: int
    completed_batches: int
    failed_batches: int
    needs_review_batches: int
    claims_found: int


class TransformationCard(BaseModel):
    transformation_run_id: int
    source_version: SourceVersionSummary
    output_types: list[str]
    artifact_states: list[DashboardArtifactState]
    status: Literal["Draft", "Generating", "Review Required", "Partial Failure", "Complete"]
    created_at: datetime
    updated_at: datetime


class ArtifactVersionHistory(BaseModel):
    id: int
    version_number: int
    source_version_id: int
    context_manifest_id: int | None
    source_version_number: int
    content: str
    provider: str | None
    model: str | None
    prompt_version: str | None
    prompt_hash: str | None
    artifact_schema_version: str | None
    review_status: Literal["draft", "accepted", "rejected"]
    created_at: datetime
    context_manifest: ContextManifestSummary | None = None
    claim_scan: ClaimScanSummary | None = None


class ArtifactRunHistory(BaseModel):
    artifact_run_id: int
    output_type: OutputType
    status: Literal["pending", "running", "succeeded", "failed"]
    versions: list[ArtifactVersionHistory]
    context_manifest: ContextManifestSummary | None = None


class TransformationDetail(BaseModel):
    transformation_run_id: int
    source_version: SourceVersionSummary
    controls: dict[str, str]
    output_types: list[str]
    status: Literal["Draft", "Generating", "Review Required", "Partial Failure", "Complete"]
    created_at: datetime
    updated_at: datetime
    artifact_runs: list[ArtifactRunHistory]


class SourceRegionInspection(BaseModel):
    id: int
    source_segment_id: int | None
    ordinal: int
    locator: str
    region_type: str
    page_number: int | None
    text: str | None
    locator_kind: str | None
    locator_metadata: dict[str, object] | None


class SourceAssetInspection(BaseModel):
    id: int
    source_kind: Literal["text", "file", "url", "image", "audio", "video"]
    media_type: str
    original_filename: str | None
    byte_size: int
    content_hash: str
    provenance_url: str | None
    extraction_method: str
    extraction_profile: str
    extraction_profile_version: int
    extraction_coverage: Literal["complete", "partial", "unavailable"]
    extraction_details: dict[str, object] | None
    preview_url: str | None = None
    download_url: str | None = None
    rights_basis: str | None = None
    consent_state: str | None = None
    consent_required: bool | None = None
    attribution: str | None = None
    regions: list[SourceRegionInspection]


class SourcePackMembershipInspection(BaseModel):
    id: int
    source_version_id: int
    source_asset_id: int
    ordinal: int
    role: Literal["PRIMARY", "SUPPORTING", "STYLE", "REFERENCE", "OPERATOR_CONTEXT"]
    asset: SourceAssetInspection


class SourcePackVersionInspection(BaseModel):
    id: int
    source_version_id: int
    version_number: int
    parent_source_pack_version_id: int | None
    content_hash: str
    created_at: datetime
    assets: list[SourceAssetInspection]
    memberships: list[SourcePackMembershipInspection]


class SourcePackInspection(BaseModel):
    id: int
    title: str | None
    created_at: datetime
    versions: list[SourcePackVersionInspection]


def _owner_source_version(session: Session, user: User, version_id: int) -> SourceVersion | None:
    return session.scalar(
        select(SourceVersion)
        .join(Source, Source.id == SourceVersion.source_id)
        .where(SourceVersion.id == version_id, Source.owner_id == user.id)
    )


def _latest_artifact_version(session: Session, artifact_run: ArtifactRun) -> ArtifactVersion | None:
    return session.scalar(
        select(ArtifactVersion)
        .where(ArtifactVersion.artifact_run_id == artifact_run.id)
        .order_by(ArtifactVersion.version_number.desc())
    )


def _aggregate_status(
    artifact_runs: list[ArtifactRun], latest_versions: dict[int, ArtifactVersion]
) -> Literal["Draft", "Generating", "Review Required", "Partial Failure", "Complete"]:
    if not artifact_runs:
        return "Draft"
    if any(run.status in {"pending", "running"} for run in artifact_runs):
        return "Generating"
    if any(run.status == "failed" for run in artifact_runs):
        return "Partial Failure"
    if any(
        latest_versions.get(run.id) is None or latest_versions[run.id].review_status != "accepted"
        for run in artifact_runs
    ):
        return "Review Required"
    return "Complete"


def _dashboard_card(
    session: Session, user: User, transformation: TransformationRun
) -> TransformationCard:
    source_version = _owner_source_version(session, user, transformation.source_version_id)
    if source_version is None:
        raise HTTPException(status_code=404, detail="Source version not found")
    source_summary = SourceVersionSummary(
        id=source_version.id,
        version_number=source_version.version_number,
        content_hash=source_version.content_hash,
        created_at=source_version.created_at,
    )
    artifact_runs = list(
        session.scalars(
            select(ArtifactRun)
            .where(ArtifactRun.transformation_run_id == transformation.id)
            .order_by(ArtifactRun.id)
        ).all()
    )
    latest_versions = {
        run.id: version
        for run in artifact_runs
        if (version := _latest_artifact_version(session, run)) is not None
    }
    by_type = {run.output_type: run for run in artifact_runs}
    artifact_states = [
        DashboardArtifactState(
            output_type=OutputType(output_type),
            status=(
                cast(
                    Literal["pending", "running", "succeeded", "failed"],
                    by_type[output_type].status,
                )
                if output_type in by_type
                else None
            ),
            latest_version_number=(
                latest_versions[by_type[output_type].id].version_number
                if output_type in by_type and by_type[output_type].id in latest_versions
                else None
            ),
            review_status=(
                cast(
                    Literal["draft", "accepted", "rejected"],
                    latest_versions[by_type[output_type].id].review_status,
                )
                if output_type in by_type and by_type[output_type].id in latest_versions
                else None
            ),
        )
        for output_type in transformation.selected_output_types
        if output_type in _OUTPUT_TYPES
    ]
    timestamps = [transformation.created_at, *(run.created_at for run in artifact_runs)]
    timestamps.extend(version.created_at for version in latest_versions.values())
    return TransformationCard(
        transformation_run_id=transformation.id,
        source_version=source_summary,
        output_types=transformation.selected_output_types,
        artifact_states=artifact_states,
        status=_aggregate_status(artifact_runs, latest_versions),
        created_at=transformation.created_at,
        updated_at=max(timestamps),
    )


def _artifact_history(
    session: Session, user: User, artifact_run: ArtifactRun
) -> ArtifactRunHistory:
    versions = list(
        session.scalars(
            select(ArtifactVersion)
            .where(ArtifactVersion.artifact_run_id == artifact_run.id)
            .order_by(ArtifactVersion.version_number)
        ).all()
    )
    history: list[ArtifactVersionHistory] = []
    for version in versions:
        source_version = _owner_source_version(session, user, version.source_version_id)
        if source_version is None:
            raise HTTPException(status_code=404, detail="Source version not found")
        history.append(
            ArtifactVersionHistory(
                id=version.id,
                version_number=version.version_number,
                source_version_id=version.source_version_id,
                context_manifest_id=version.context_manifest_id,
                source_version_number=source_version.version_number,
                content=version.content,
                provider=version.provider,
                model=version.model,
                prompt_version=version.prompt_version,
                prompt_hash=version.prompt_hash,
                artifact_schema_version=version.artifact_schema_version,
                review_status=cast(Literal["draft", "accepted", "rejected"], version.review_status),
                created_at=version.created_at,
                context_manifest=_context_manifest_summary(
                    session, user, version.context_manifest_id
                ),
                claim_scan=_claim_scan_summary(session, user, version.id),
            )
        )
    latest_job = session.scalar(
        select(Job)
        .where(Job.artifact_run_id == artifact_run.id)
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(1)
    )
    return ArtifactRunHistory(
        artifact_run_id=artifact_run.id,
        output_type=OutputType(artifact_run.output_type),
        status=cast(Literal["pending", "running", "succeeded", "failed"], artifact_run.status),
        versions=history,
        context_manifest=(
            _context_manifest_summary(session, user, latest_job.context_manifest_id)
            if latest_job is not None
            else None
        ),
    )


def _context_manifest_summary(
    session: Session, user: User, manifest_id: int | None
) -> ContextManifestSummary | None:
    if manifest_id is None:
        return None
    manifest = session.scalar(
        select(ContextManifest).where(
            ContextManifest.id == manifest_id,
            ContextManifest.owner_id == user.id,
        )
    )
    if manifest is None:
        return None
    region_count = (
        session.scalar(
            select(func.count(ContextManifestEntry.id)).where(
                ContextManifestEntry.context_manifest_id == manifest.id,
                ContextManifestEntry.selected.is_(True),
            )
        )
        or 0
    )
    return ContextManifestSummary(
        id=manifest.id,
        source_version_id=manifest.source_version_id,
        source_pack_version_id=manifest.source_pack_version_id,
        route=manifest.route,
        context_profile=manifest.context_profile,
        state=manifest.state,
        extraction_coverage=manifest.extraction_coverage,
        estimated_context_units=manifest.estimated_context_units,
        context_budget_units=manifest.context_budget_units,
        region_count=region_count,
        warnings=manifest.warnings,
        created_at=manifest.created_at,
    )


def _claim_scan_summary(
    session: Session, user: User, artifact_version_id: int
) -> ClaimScanSummary | None:
    scan = session.scalar(
        select(ClaimScan).where(
            ClaimScan.artifact_version_id == artifact_version_id,
            ClaimScan.owner_id == user.id,
        )
    )
    if scan is None:
        return None
    coverage = claim_scan_coverage(session, scan)
    return ClaimScanSummary(
        id=scan.id,
        status=cast(
            Literal["pending", "running", "complete", "failed", "needs_review"], scan.status
        ),
        total_batches=int(coverage["total_batches"]),
        completed_batches=int(coverage["completed_batches"]),
        failed_batches=int(coverage["failed_batches"]),
        needs_review_batches=int(coverage["needs_review_batches"]),
        claims_found=int(coverage["claims_found"]),
    )


@router.get("/transformations", response_model=list[TransformationCard])
def list_transformations(
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[TransformationCard]:
    transformations = list(
        session.scalars(
            select(TransformationRun)
            .where(TransformationRun.owner_id == user.id)
            .order_by(TransformationRun.created_at.desc(), TransformationRun.id.desc())
        ).all()
    )
    return [_dashboard_card(session, user, item) for item in transformations]


@router.get("/transformations/{transformation_run_id}", response_model=TransformationDetail)
def get_transformation_detail(
    transformation_run_id: int,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> TransformationDetail:
    transformation = session.scalar(
        select(TransformationRun).where(
            TransformationRun.id == transformation_run_id,
            TransformationRun.owner_id == user.id,
        )
    )

    if transformation is None:
        raise HTTPException(status_code=404, detail="Transformation not found")
    card = _dashboard_card(session, user, transformation)
    runs = list(
        session.scalars(
            select(ArtifactRun)
            .where(ArtifactRun.transformation_run_id == transformation.id)
            .order_by(ArtifactRun.id)
        ).all()
    )
    timestamps = [transformation.created_at, card.updated_at]
    return TransformationDetail(
        transformation_run_id=transformation.id,
        source_version=card.source_version,
        controls={
            "audience": transformation.audience,
            "tone": transformation.tone,
            "language": transformation.language,
            "detail_level": transformation.detail_level,
            "objective": transformation.objective,
            "style": transformation.style,
        },
        output_types=transformation.selected_output_types,
        status=card.status,
        created_at=transformation.created_at,
        updated_at=max(timestamps),
        artifact_runs=[_artifact_history(session, user, item) for item in runs],
    )


@router.get(
    "/transformations/{transformation_run_id}/source-pack",
    response_model=SourcePackInspection,
)
def get_transformation_source_pack(
    transformation_run_id: int,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> SourcePackInspection:
    transformation = session.scalar(
        select(TransformationRun).where(
            TransformationRun.id == transformation_run_id,
            TransformationRun.owner_id == user.id,
        )
    )
    if transformation is None:
        raise HTTPException(status_code=404, detail="Transformation not found")
    source_pack = session.scalar(
        select(SourcePack)
        .join(SourcePackVersion, SourcePackVersion.source_pack_id == SourcePack.id)
        .where(
            SourcePack.owner_id == user.id,
            SourcePackVersion.source_version_id == transformation.source_version_id,
        )
    )
    if source_pack is None:
        raise HTTPException(status_code=404, detail="Transformation not found")
    pack_versions = list(
        session.scalars(
            select(SourcePackVersion)
            .where(SourcePackVersion.source_pack_id == source_pack.id)
            .order_by(SourcePackVersion.version_number)
        ).all()
    )
    versions: list[SourcePackVersionInspection] = []

    def inspect_asset(asset: SourceAsset) -> SourceAssetInspection:
        regions = list(
            session.scalars(
                select(SourceRegion)
                .where(SourceRegion.source_asset_id == asset.id)
                .order_by(SourceRegion.ordinal)
            ).all()
        )
        rights = session.scalar(
            select(MediaRightsRecord).where(MediaRightsRecord.source_asset_id == asset.id)
        )
        is_media = asset.source_kind in {"image", "audio", "video"}
        return SourceAssetInspection(
            id=asset.id,
            source_kind=cast(
                Literal["text", "file", "url", "image", "audio", "video"],
                asset.source_kind,
            ),
            media_type=asset.media_type,
            original_filename=asset.original_filename,
            byte_size=asset.byte_size,
            content_hash=asset.content_hash,
            provenance_url=asset.provenance_url,
            extraction_method=asset.extraction_method,
            extraction_profile=asset.extraction_profile,
            extraction_profile_version=asset.extraction_profile_version,
            extraction_coverage=cast(
                Literal["complete", "partial", "unavailable"], asset.extraction_coverage
            ),
            extraction_details=asset.extraction_details,
            preview_url=f"/api/source-assets/{asset.id}/preview" if is_media else None,
            download_url=f"/api/source-assets/{asset.id}/download" if is_media else None,
            rights_basis=rights.rights_basis if rights is not None else None,
            consent_state=rights.consent_state if rights is not None else None,
            consent_required=rights.consent_required if rights is not None else None,
            attribution=rights.attribution if rights is not None else None,
            regions=[
                SourceRegionInspection(
                    id=region.id,
                    source_segment_id=region.source_segment_id,
                    ordinal=region.ordinal,
                    locator=region.locator,
                    region_type=region.region_type,
                    page_number=region.page_number,
                    text=region.text,
                    locator_kind=region.locator_kind,
                    locator_metadata=region.locator_metadata,
                )
                for region in regions
            ],
        )

    for pack_version in pack_versions:
        assets = list(
            session.scalars(
                select(SourceAsset)
                .where(SourceAsset.source_pack_version_id == pack_version.id)
                .order_by(SourceAsset.id)
            ).all()
        )
        asset_views = [inspect_asset(asset) for asset in assets]
        memberships = session.execute(
            select(SourcePackMembership, SourceAsset)
            .join(SourceAsset, SourceAsset.id == SourcePackMembership.source_asset_id)
            .join(SourcePackVersion, SourcePackVersion.id == SourceAsset.source_pack_version_id)
            .join(SourcePack, SourcePack.id == SourcePackVersion.source_pack_id)
            .join(SourceVersion, SourceVersion.id == SourcePackMembership.source_version_id)
            .join(Source, Source.id == SourceVersion.source_id)
            .where(
                SourcePackMembership.source_pack_version_id == pack_version.id,
                SourcePack.owner_id == user.id,
                Source.owner_id == user.id,
            )
            .order_by(SourcePackMembership.ordinal)
        ).all()
        membership_views: list[SourcePackMembershipInspection] = []
        for membership, source_asset in memberships:
            membership_views.append(
                SourcePackMembershipInspection(
                    id=membership.id,
                    source_version_id=membership.source_version_id,
                    source_asset_id=membership.source_asset_id,
                    ordinal=membership.ordinal,
                    role=cast(
                        Literal[
                            "PRIMARY",
                            "SUPPORTING",
                            "STYLE",
                            "REFERENCE",
                            "OPERATOR_CONTEXT",
                        ],
                        membership.role,
                    ),
                    asset=inspect_asset(source_asset),
                )
            )
        versions.append(
            SourcePackVersionInspection(
                id=pack_version.id,
                source_version_id=pack_version.source_version_id,
                version_number=pack_version.version_number,
                parent_source_pack_version_id=pack_version.parent_source_pack_version_id,
                content_hash=pack_version.content_hash,
                created_at=pack_version.created_at,
                assets=asset_views,
                memberships=membership_views,
            )
        )
    return SourcePackInspection(
        id=source_pack.id,
        title=source_pack.title,
        created_at=source_pack.created_at,
        versions=versions,
    )


@router.post("/transformations/prepare", response_model=PreparedTransformationRequest)
def prepare_transformation(
    transformation_request: TransformationRequest,
    _user: Annotated[User, Depends(require_current_user)],
) -> PreparedTransformationRequest:
    return PreparedTransformationRequest(request=transformation_request)


class SavedSourceVersion(BaseModel):
    id: int
    version_number: int
    content_hash: str
    segment_count: int


class SavedTransformation(BaseModel):
    status: Literal["saved"] = "saved"
    transformation_run_id: int
    source_id: int
    source_version: SavedSourceVersion
    output_types: list[str]


@router.post("/transformations", response_model=SavedTransformation)
def save_transformation(
    transformation_request: CreateTransformationRequest,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> SavedTransformation:
    result = dispatch_manual_application_command(
        CreateTransformationCommand(request=transformation_request),
        session=session,
        user=user,
        request_id=getattr(request.state, "request_id", None),
    )
    return cast(SavedTransformation, result)


def execute_create_transformation(
    transformation_request: CreateTransformationRequest,
    *,
    user: User,
    session: Session,
    request_id: str | None,
) -> SavedTransformation:
    try:
        if transformation_request.source_version_id is None:
            write = create_source_pack_version(session, user.id, transformation_request.source_text)
            source = write.source
            source_version = write.source_version
        else:
            source_version = _owner_source_version(
                session, user, transformation_request.source_version_id
            )
            if source_version is None:
                raise HTTPException(status_code=404, detail="Source version not found")
            source = session.get(Source, source_version.source_id)
            if source is None:
                raise HTTPException(status_code=404, detail="Source version not found")
            if source_version.source_text != transformation_request.source_text:
                source_version = create_source_version(
                    session,
                    source,
                    transformation_request.source_text,
                    parent_source_version_id=source_version.id,
                )
        session.flush()
        run = TransformationRun(
            owner_id=user.id,
            source_version_id=source_version.id,
            supporting_context=transformation_request.supporting_context,
            audience=transformation_request.audience,
            tone=transformation_request.tone,
            language=transformation_request.language,
            detail_level=transformation_request.detail_level,
            objective=transformation_request.objective,
            style=transformation_request.style,
            selected_output_types=[item.value for item in transformation_request.output_types],
        )
        session.add(run)
        session.flush()
        record_audit_event(
            session,
            owner_id=user.id,
            action_type="transformation.created",
            target_type="transformation",
            target_id=run.id,
            request_id=request_id,
            safe_metadata={"output_type_count": len(transformation_request.output_types)},
        )
        segment_count = (
            session.scalar(
                select(func.count())
                .select_from(SourceSegment)
                .where(SourceSegment.source_version_id == source_version.id)
            )
            or 0
        )
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise HTTPException(
            status_code=500,
            detail={"code": "save_failed", "message": "The transformation could not be saved."},
        ) from None

    return SavedTransformation(
        transformation_run_id=run.id,
        source_id=source.id,
        source_version=SavedSourceVersion(
            id=source_version.id,
            version_number=source_version.version_number,
            content_hash=source_version.content_hash,
            segment_count=segment_count,
        ),
        output_types=[item.value for item in transformation_request.output_types],
    )
