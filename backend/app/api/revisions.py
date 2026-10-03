from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_current_user
from app.database import get_db_session
from app.job_queue import enqueue_artifact_job
from app.models import (
    ArtifactRun,
    ArtifactVersion,
    Job,
    Source,
    SourceVersion,
    TransformationRun,
    User,
)
from app.source_alignment import align_source_versions
from app.source_revisions import (
    AffectedArtifactEvidence,
    SourceSegmentChange,
    diff_source_versions,
    find_potentially_affected_artifacts,
)
from app.source_versions import create_source_version, normalize_source_text

router = APIRouter()


class CreateSourceVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_text: str = Field(min_length=1, max_length=20_000)

    @field_validator("source_text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return normalize_source_text(value)


class SourceVersionSummary(BaseModel):
    id: int
    version_number: int
    content_hash: str
    created_at: datetime


class SourceSegmentChangeResponse(BaseModel):
    change_type: Literal["added", "removed", "changed"]
    locator: str
    old_text: str | None
    new_text: str | None


class AffectedArtifactResponse(BaseModel):
    artifact_run_id: int
    artifact_version_id: int
    output_type: str
    artifact_version_number: int
    evidence_claims: list[str]
    impact_state: Literal["unaffected", "affected", "needs_review", "unknown"]
    affected_block_keys: list[str]
    review_block_keys: list[str]
    unknown_block_keys: list[str]
    targeted_update_available: bool


class SourceRevisionStatus(BaseModel):
    transformation_run_id: int
    parent_source_version: SourceVersionSummary | None
    source_version: SourceVersionSummary
    changes: list[SourceSegmentChangeResponse]
    potentially_affected_artifacts: list[AffectedArtifactResponse]


def _owned_transformation(
    session: Session, user: User, transformation_run_id: int
) -> TransformationRun | None:
    return session.scalar(
        select(TransformationRun).where(
            TransformationRun.id == transformation_run_id,
            TransformationRun.owner_id == user.id,
        )
    )


def _owned_source_version(
    session: Session, user: User, source_version_id: int
) -> SourceVersion | None:
    return session.scalar(
        select(SourceVersion)
        .join(Source, Source.id == SourceVersion.source_id)
        .where(SourceVersion.id == source_version_id, Source.owner_id == user.id)
    )


def _source_summary(version: SourceVersion) -> SourceVersionSummary:
    return SourceVersionSummary(
        id=version.id,
        version_number=version.version_number,
        content_hash=version.content_hash,
        created_at=version.created_at,
    )


def _change_response(change: SourceSegmentChange) -> SourceSegmentChangeResponse:
    return SourceSegmentChangeResponse(
        change_type=change.change_type,
        locator=change.locator,
        old_text=change.old_text,
        new_text=change.new_text,
    )


def _affected_response(
    affected: AffectedArtifactEvidence,
) -> AffectedArtifactResponse:
    return AffectedArtifactResponse(
        artifact_run_id=affected.artifact_run.id,
        artifact_version_id=affected.artifact_version.id,
        output_type=affected.artifact_run.output_type,
        artifact_version_number=affected.artifact_version.version_number,
        evidence_claims=[link.claim_text for link in affected.evidence_links],
        impact_state=affected.impact_state,
        affected_block_keys=list(affected.affected_block_keys),
        review_block_keys=list(affected.review_block_keys),
        unknown_block_keys=list(affected.unknown_block_keys),
        targeted_update_available=affected.targeted_update_available,
    )


@router.post(
    "/transformations/{transformation_run_id}/source-versions",
    response_model=SourceRevisionStatus,
)
def create_transformation_source_version(
    transformation_run_id: int,
    request: CreateSourceVersionRequest,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> SourceRevisionStatus:
    transformation = _owned_transformation(session, user, transformation_run_id)
    if transformation is None:
        raise HTTPException(status_code=404, detail="Transformation not found")
    old_source = _owned_source_version(session, user, transformation.source_version_id)
    if old_source is None:
        raise HTTPException(status_code=404, detail="Source version not found")
    source = session.get(Source, old_source.source_id)
    if source is None or source.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Source not found")
    try:
        new_source = create_source_version(
            session,
            source,
            request.source_text,
            parent_source_version_id=old_source.id,
        )
        align_source_versions(session, old_source, new_source)
        transformation.source_version_id = new_source.id
        session.commit()
    except Exception:
        session.rollback()
        raise HTTPException(
            status_code=500,
            detail={
                "code": "source_revision_failed",
                "message": "The source update could not be saved.",
            },
        ) from None
    session.refresh(transformation)
    session.refresh(new_source)
    changes = diff_source_versions(session, old_source, new_source)
    affected = find_potentially_affected_artifacts(session, old_source, new_source, changes)
    return SourceRevisionStatus(
        transformation_run_id=transformation.id,
        parent_source_version=_source_summary(old_source),
        source_version=_source_summary(new_source),
        changes=[_change_response(change) for change in changes],
        potentially_affected_artifacts=[_affected_response(item) for item in affected],
    )


@router.get(
    "/transformations/{transformation_run_id}/revision-impact",
    response_model=SourceRevisionStatus,
)
def get_transformation_revision_impact(
    transformation_run_id: int,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> SourceRevisionStatus:
    transformation = _owned_transformation(session, user, transformation_run_id)
    if transformation is None:
        raise HTTPException(status_code=404, detail="Transformation not found")
    current = _owned_source_version(session, user, transformation.source_version_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Source version not found")
    parent = (
        _owned_source_version(session, user, current.parent_source_version_id)
        if current.parent_source_version_id is not None
        else None
    )
    changes = diff_source_versions(session, parent, current) if parent is not None else []
    affected = (
        find_potentially_affected_artifacts(session, parent, current, changes)
        if parent is not None
        else []
    )
    return SourceRevisionStatus(
        transformation_run_id=transformation.id,
        parent_source_version=_source_summary(parent) if parent is not None else None,
        source_version=_source_summary(current),
        changes=[_change_response(change) for change in changes],
        potentially_affected_artifacts=[_affected_response(item) for item in affected],
    )


@router.post(
    "/artifact-runs/{artifact_run_id}/targeted-update",
    response_model=dict[str, object],
    status_code=status.HTTP_202_ACCEPTED,
)
def targeted_update_artifact(
    artifact_run_id: int,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    row = session.execute(
        select(ArtifactRun, TransformationRun)
        .join(TransformationRun, TransformationRun.id == ArtifactRun.transformation_run_id)
        .where(ArtifactRun.id == artifact_run_id, TransformationRun.owner_id == user.id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Artifact run not found")
    artifact_run, transformation = row
    artifact_run_id = artifact_run.id
    output_type = artifact_run.output_type
    active_job = session.scalar(
        select(Job).where(
            Job.artifact_run_id == artifact_run_id,
            Job.status.in_(("queued", "running")),
        )
    )
    if active_job is not None:
        return {
            "artifact_run_id": artifact_run_id,
            "output_type": output_type,
            "status": "pending" if active_job.status == "queued" else "running",
        }
    latest = session.scalar(
        select(ArtifactVersion)
        .where(ArtifactVersion.artifact_run_id == artifact_run_id)
        .order_by(ArtifactVersion.version_number.desc())
    )
    if latest is None:
        raise HTTPException(status_code=409, detail="Generate an artifact before updating it")
    new_source = _owned_source_version(session, user, transformation.source_version_id)
    old_source = _owned_source_version(session, user, latest.source_version_id)
    if new_source is None or old_source is None:
        raise HTTPException(status_code=404, detail="Source version not found")
    if new_source.id == old_source.id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "source_not_updated",
                "message": "Create a new source version before targeting an artifact update.",
            },
        )
    impact = next(
        (
            item
            for item in find_potentially_affected_artifacts(
                session,
                old_source,
                new_source,
                diff_source_versions(session, old_source, new_source),
            )
            if item.artifact_version.id == latest.id
        ),
        None,
    )
    if impact is None or not impact.targeted_update_available:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "targeted_update_requires_review",
                "message": (
                    "Safe block-level impact is unavailable. Review evidence or regenerate "
                    "the artifact."
                ),
                "impact_state": impact.impact_state if impact is not None else "unknown",
            },
        )
    if artifact_run.status != "succeeded":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "artifact_not_succeeded",
                "message": "Only successful artifacts can be updated.",
            },
        )
    artifact_run.status = "pending"
    enqueue_artifact_job(
        session,
        artifact_run,
        new_source,
        base_artifact_version_id=latest.id,
        targeted_block_keys=list(impact.affected_block_keys),
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        active_job = session.scalar(
            select(Job).where(
                Job.artifact_run_id == artifact_run_id,
                Job.status.in_(("queued", "running")),
            )
        )
        if active_job is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "targeted_update_conflict",
                    "message": "The artifact update could not be queued.",
                },
            ) from None
        return {
            "artifact_run_id": artifact_run_id,
            "output_type": output_type,
            "status": "pending" if active_job.status == "queued" else "running",
        }
    return {
        "artifact_run_id": artifact_run_id,
        "output_type": output_type,
        "status": "pending",
    }
