from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_current_user
from app.database import get_db_session
from app.domain.transformation import (
    CreateTransformationRequest,
    PreparedTransformationRequest,
    TransformationRequest,
)
from app.models import (
    ArtifactRun,
    ArtifactVersion,
    Source,
    SourceSegment,
    SourceVersion,
    TransformationRun,
    User,
)
from app.source_versions import create_source_version

router = APIRouter()

_OUTPUT_TYPES = ("executive_summary", "linkedin_post", "x_post", "advisory", "presentation")
_ARTIFACT_STATUSES = ("pending", "running", "succeeded", "failed")


class SourceVersionSummary(BaseModel):
    id: int
    version_number: int
    content_hash: str
    created_at: datetime


class DashboardArtifactState(BaseModel):
    output_type: Literal["executive_summary", "linkedin_post", "x_post", "advisory", "presentation"]
    status: Literal["pending", "running", "succeeded", "failed"] | None
    latest_version_number: int | None
    review_status: Literal["draft", "accepted", "rejected"] | None


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
    source_version_number: int
    content: str
    provider: str | None
    model: str | None
    prompt_version: str | None
    prompt_hash: str | None
    review_status: Literal["draft", "accepted", "rejected"]
    created_at: datetime


class ArtifactRunHistory(BaseModel):
    artifact_run_id: int
    output_type: Literal["executive_summary", "linkedin_post", "x_post", "advisory", "presentation"]
    status: Literal["pending", "running", "succeeded", "failed"]
    versions: list[ArtifactVersionHistory]


class TransformationDetail(BaseModel):
    transformation_run_id: int
    source_version: SourceVersionSummary
    controls: dict[str, str]
    output_types: list[str]
    status: Literal["Draft", "Generating", "Review Required", "Partial Failure", "Complete"]
    created_at: datetime
    updated_at: datetime
    artifact_runs: list[ArtifactRunHistory]


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
            output_type=output_type,
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
                source_version_number=source_version.version_number,
                content=version.content,
                provider=version.provider,
                model=version.model,
                prompt_version=version.prompt_version,
                prompt_hash=version.prompt_hash,
                review_status=cast(Literal["draft", "accepted", "rejected"], version.review_status),
                created_at=version.created_at,
            )
        )
    return ArtifactRunHistory(
        artifact_run_id=artifact_run.id,
        output_type=cast(
            Literal["executive_summary", "linkedin_post", "x_post", "advisory", "presentation"],
            artifact_run.output_type,
        ),
        status=cast(Literal["pending", "running", "succeeded", "failed"], artifact_run.status),
        versions=history,
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
) -> SavedTransformation:
    try:
        source = Source(owner_id=user.id)
        session.add(source)
        session.flush()
        source_version = create_source_version(session, source, transformation_request.source_text)
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
        segment_count = (
            session.scalar(
                select(func.count())
                .select_from(SourceSegment)
                .where(SourceSegment.source_version_id == source_version.id)
            )
            or 0
        )
        session.commit()
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
