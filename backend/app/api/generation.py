from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.artifact_generators import generate_artifact
from app.auth import require_current_user
from app.database import get_db_session
from app.domain.transformation import OutputType, TransformationRequest
from app.generation import GenerationProvider
from app.models import ArtifactRun, ArtifactVersion, Source, SourceVersion, TransformationRun, User
from app.openai_provider import OpenAIGenerationProvider
from app.settings import get_settings

router = APIRouter()
SUPPORTED_OUTPUTS = (
    OutputType.EXECUTIVE_SUMMARY,
    OutputType.LINKEDIN_POST,
    OutputType.ADVISORY,
    OutputType.PRESENTATION,
)


def get_generation_provider() -> GenerationProvider | None:
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    return OpenAIGenerationProvider(settings.openai_api_key, settings.openai_model)


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
    output_type: Literal["executive_summary", "linkedin_post", "advisory", "presentation"]
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


def _transformation_request(
    transformation: TransformationRun, source_version: SourceVersion, output_type: OutputType
) -> TransformationRequest:
    return TransformationRequest(
        source_text=source_version.source_text,
        output_types=[output_type],
        audience=transformation.audience,
        tone=transformation.tone,
        language=transformation.language,
        detail_level=cast(Literal["brief", "standard", "detailed"], transformation.detail_level),
        objective=transformation.objective,
        style=transformation.style,
    )


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
            Literal["executive_summary", "linkedin_post", "advisory", "presentation"],
            artifact_run.output_type,
        ),
        status=cast(Literal["pending", "running", "succeeded", "failed"], artifact_run.status),
        artifact_version=artifact_version,
    )


async def _generate_one(
    session: Session,
    transformation: TransformationRun,
    source_version: SourceVersion,
    artifact_run: ArtifactRun,
    provider: GenerationProvider,
) -> None:
    artifact_run.status = "running"
    session.commit()
    try:
        output_type = OutputType(artifact_run.output_type)
        request = _transformation_request(transformation, source_version, output_type)
        draft = await generate_artifact(
            provider,
            request,
            transformation.supporting_context,
            output_type,
        )
    except Exception:
        artifact_run.status = "failed"
        session.commit()
        return

    latest = _latest_version(session, artifact_run)
    version = ArtifactVersion(
        artifact_run_id=artifact_run.id,
        version_number=1 if latest is None else latest.version_number + 1,
        source_version_id=source_version.id,
        content=draft.content,
        provider=draft.provider,
        model=draft.model,
        prompt_version=draft.prompt_version,
        prompt_hash=draft.prompt_hash,
    )
    session.add(version)
    artifact_run.status = "succeeded"
    session.commit()
    session.refresh(artifact_run)


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
)
async def generate_selected_artifacts(
    transformation_run_id: int,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    provider: Annotated[GenerationProvider | None, Depends(get_generation_provider)],
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
    new_runs: list[ArtifactRun] = []
    for output_type in selected_outputs:
        if output_type.value not in runs_by_output:
            artifact_run = ArtifactRun(
                transformation_run_id=transformation.id,
                output_type=output_type.value,
                status="pending",
            )
            session.add(artifact_run)
            new_runs.append(artifact_run)
            runs_by_output[output_type.value] = artifact_run

    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "artifact_run_exists", "message": "Generation runs already exist."},
        ) from None

    if provider is None:
        for artifact_run in new_runs:
            artifact_run.status = "failed"
        session.commit()
        raise HTTPException(
            status_code=503,
            detail={
                "code": "generation_not_configured",
                "message": "Generation is not configured on this server.",
            },
        )

    session.commit()
    for artifact_run in new_runs:
        await _generate_one(session, transformation, source_version, artifact_run, provider)

    artifacts = [
        _run_detail(session, user, runs_by_output[output_type.value])
        for output_type in selected_outputs
    ]
    return GenerationBatchResponse(status=_batch_status(artifacts), artifacts=artifacts)


@router.post("/artifact-runs/{artifact_run_id}/retry", response_model=ArtifactRunDetail)
async def retry_failed_artifact(
    artifact_run_id: int,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    provider: Annotated[GenerationProvider | None, Depends(get_generation_provider)],
) -> ArtifactRunDetail:
    row = session.execute(
        select(ArtifactRun, TransformationRun)
        .join(TransformationRun, TransformationRun.id == ArtifactRun.transformation_run_id)
        .where(ArtifactRun.id == artifact_run_id, TransformationRun.owner_id == user.id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Artifact run not found")
    artifact_run, transformation = row
    if artifact_run.status != "failed":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "artifact_not_failed",
                "message": "Only failed outputs can be retried.",
            },
        )
    if provider is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "generation_not_configured",
                "message": "Generation is not configured on this server.",
            },
        )

    source_version = _owned_source_version(session, user, transformation)
    await _generate_one(session, transformation, source_version, artifact_run, provider)
    return _run_detail(session, user, artifact_run)
