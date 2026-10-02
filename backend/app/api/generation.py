from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_current_user
from app.database import get_db_session
from app.domain.transformation import OutputType
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
from app.provider_factory import get_generation_provider as get_generation_provider

__all__ = ["get_generation_provider", "router"]

router = APIRouter()
SUPPORTED_OUTPUTS = (
    OutputType.EXECUTIVE_SUMMARY,
    OutputType.LINKEDIN_POST,
    OutputType.X_POST,
    OutputType.ADVISORY,
    OutputType.PRESENTATION,
)


class GeneratedArtifactVersion(BaseModel):
    id: int
    version_number: int
    source_version_id: int
    source_version_number: int
    content: str
    provider: str
    model: str
    prompt_version: str
    prompt_hash: str


class ArtifactRunDetail(BaseModel):
    artifact_run_id: int
    output_type: Literal["executive_summary", "linkedin_post", "x_post", "advisory", "presentation"]
    status: Literal["pending", "running", "succeeded", "failed"]
    artifact_version: GeneratedArtifactVersion | None


class GenerationBatchResponse(BaseModel):
    status: Literal["succeeded", "partial_failure", "running"]
    artifacts: list[ArtifactRunDetail]


def _owned_source_version(
    session: Session, user: User, transformation: TransformationRun
) -> SourceVersion:
    source_version = session.scalar(
        select(SourceVersion)
        .join(Source, Source.id == SourceVersion.source_id)
        .where(
            SourceVersion.id == transformation.source_version_id,
            Source.owner_id == user.id,
        )
    )
    if source_version is None:
        raise HTTPException(status_code=404, detail="Source version not found")
    return source_version


def _latest_version(session: Session, artifact_run: ArtifactRun) -> ArtifactVersion | None:
    return session.scalar(
        select(ArtifactVersion)
        .where(ArtifactVersion.artifact_run_id == artifact_run.id)
        .order_by(ArtifactVersion.version_number.desc())
    )


def _run_detail(session: Session, user: User, artifact_run: ArtifactRun) -> ArtifactRunDetail:
    version = _latest_version(session, artifact_run)
    artifact_version = None
    if version is not None:
        source_version_number = session.scalar(
            select(SourceVersion.version_number)
            .join(Source, Source.id == SourceVersion.source_id)
            .where(
                SourceVersion.id == version.source_version_id,
                Source.owner_id == user.id,
            )
        )
        if source_version_number is None:
            raise HTTPException(status_code=404, detail="Source version not found")
        artifact_version = GeneratedArtifactVersion(
            id=version.id,
            version_number=version.version_number,
            source_version_id=version.source_version_id,
            source_version_number=source_version_number,
            content=version.content,
            provider=version.provider or "",
            model=version.model or "",
            prompt_version=version.prompt_version or "",
            prompt_hash=version.prompt_hash or "",
        )
    return ArtifactRunDetail(
        artifact_run_id=artifact_run.id,
        output_type=cast(
            Literal["executive_summary", "linkedin_post", "x_post", "advisory", "presentation"],
            artifact_run.output_type,
        ),
        status=cast(Literal["pending", "running", "succeeded", "failed"], artifact_run.status),
        artifact_version=artifact_version,
    )


def _batch_status(
    artifacts: list[ArtifactRunDetail],
) -> Literal["succeeded", "partial_failure", "running"]:
    if any(item.status in {"pending", "running"} for item in artifacts):
        return "running"
    if any(item.status == "failed" for item in artifacts):
        return "partial_failure"
    return "succeeded"


@router.post(
    "/transformations/{transformation_run_id}/generate",
    response_model=GenerationBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_selected_artifacts(
    transformation_run_id: int,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> GenerationBatchResponse:
    transformation = session.scalar(
        select(TransformationRun).where(
            TransformationRun.id == transformation_run_id,
            TransformationRun.owner_id == user.id,
        )
    )
    if transformation is None:
        raise HTTPException(status_code=404, detail="Transformation not found")

    selected_outputs = [OutputType(value) for value in transformation.selected_output_types]
    if not selected_outputs or any(output not in SUPPORTED_OUTPUTS for output in selected_outputs):
        raise HTTPException(status_code=409, detail="No supported outputs were selected")

    source_version = _owned_source_version(session, user, transformation)
    existing_runs = list(
        session.scalars(
            select(ArtifactRun).where(ArtifactRun.transformation_run_id == transformation.id)
        ).all()
    )
    runs_by_output = {item.output_type: item for item in existing_runs}
    for output_type in selected_outputs:
        if output_type.value not in runs_by_output:
            artifact_run = ArtifactRun(
                transformation_run_id=transformation.id,
                output_type=output_type.value,
                status="pending",
            )
            session.add(artifact_run)
            runs_by_output[output_type.value] = artifact_run

    try:
        session.flush()
        for output_type in selected_outputs:
            artifact_run = runs_by_output[output_type.value]
            active_job = session.scalar(
                select(Job.id).where(
                    Job.artifact_run_id == artifact_run.id,
                    Job.status.in_(("queued", "running")),
                )
            )
            if active_job is not None or artifact_run.status == "succeeded":
                continue
            if artifact_run.status == "failed":
                continue
            artifact_run.status = "pending"
            enqueue_artifact_job(session, artifact_run, source_version)
        session.commit()
    except IntegrityError:
        session.rollback()
        existing_runs = list(
            session.scalars(
                select(ArtifactRun).where(ArtifactRun.transformation_run_id == transformation.id)
            ).all()
        )
        runs_by_output = {item.output_type: item for item in existing_runs}
        if any(output.value not in runs_by_output for output in selected_outputs):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "artifact_run_exists",
                    "message": "Generation could not be queued. Please retry.",
                },
            ) from None

    artifacts = [
        _run_detail(session, user, runs_by_output[output_type.value])
        for output_type in selected_outputs
    ]
    return GenerationBatchResponse(status=_batch_status(artifacts), artifacts=artifacts)


@router.post(
    "/artifact-runs/{artifact_run_id}/retry",
    response_model=ArtifactRunDetail,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_failed_artifact(
    artifact_run_id: int,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ArtifactRunDetail:
    row = session.execute(
        select(ArtifactRun, TransformationRun)
        .join(TransformationRun, TransformationRun.id == ArtifactRun.transformation_run_id)
        .where(ArtifactRun.id == artifact_run_id, TransformationRun.owner_id == user.id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Artifact run not found")
    artifact_run, transformation = row
    active_job = session.scalar(
        select(Job).where(
            Job.artifact_run_id == artifact_run.id,
            Job.status.in_(("queued", "running")),
        )
    )
    if active_job is not None:
        return _run_detail(session, user, artifact_run)
    if artifact_run.status != "failed":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "artifact_not_failed",
                "message": "Only failed outputs can be retried.",
            },
        )
    previous_job = session.scalar(
        select(Job)
        .where(Job.artifact_run_id == artifact_run.id)
        .order_by(Job.created_at.desc(), Job.id.desc())
    )
    artifact_run.status = "pending"
    if previous_job is not None and previous_job.status == "failed":
        previous_job.status = "queued"
        previous_job.failure_code = None
        previous_job.terminal_at = None
    else:
        source_version = _owned_source_version(session, user, transformation)
        enqueue_artifact_job(session, artifact_run, source_version)
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
                detail={"code": "retry_conflict", "message": "Retry could not be queued."},
            ) from None
        artifact_run = session.get(ArtifactRun, artifact_run_id)
        if artifact_run is None:
            raise HTTPException(status_code=404, detail="Artifact run not found") from None
    return _run_detail(session, user, artifact_run)


@router.post(
    "/artifact-runs/{artifact_run_id}/regenerate",
    response_model=ArtifactRunDetail,
    status_code=status.HTTP_202_ACCEPTED,
)
def regenerate_artifact(
    artifact_run_id: int,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ArtifactRunDetail:
    row = session.execute(
        select(ArtifactRun, TransformationRun)
        .join(TransformationRun, TransformationRun.id == ArtifactRun.transformation_run_id)
        .where(ArtifactRun.id == artifact_run_id, TransformationRun.owner_id == user.id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Artifact run not found")
    artifact_run, transformation = row
    active_job = session.scalar(
        select(Job).where(
            Job.artifact_run_id == artifact_run.id,
            Job.status.in_(("queued", "running")),
        )
    )
    if active_job is not None:
        return _run_detail(session, user, artifact_run)
    if artifact_run.status != "succeeded":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "artifact_not_succeeded",
                "message": "Only successful artifacts can be regenerated.",
            },
        )
    source_version = _owned_source_version(session, user, transformation)
    artifact_run.status = "pending"
    enqueue_artifact_job(session, artifact_run, source_version)
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
                    "code": "regeneration_conflict",
                    "message": "Regeneration could not be queued.",
                },
            ) from None
        artifact_run = session.get(ArtifactRun, artifact_run_id)
        if artifact_run is None:
            raise HTTPException(status_code=404, detail="Artifact run not found") from None
    return _run_detail(session, user, artifact_run)
