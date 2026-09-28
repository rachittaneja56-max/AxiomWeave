from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_current_user
from app.database import get_db_session
from app.domain.transformation import OutputType, TransformationRequest
from app.executive_summary import (
    EXECUTIVE_SUMMARY_PROMPT_VERSION,
    ExecutiveSummaryGenerator,
    executive_summary_prompt_hash,
)
from app.generation import GenerationProvider
from app.models import ArtifactRun, ArtifactVersion, Source, SourceVersion, TransformationRun, User
from app.openai_provider import OpenAIGenerationProvider
from app.settings import get_settings

router = APIRouter()


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


class GeneratedArtifact(BaseModel):
    status: Literal["succeeded"]
    artifact_run_id: int
    output_type: Literal["executive_summary"]
    artifact_version: GeneratedArtifactVersion


@router.post(
    "/transformations/{transformation_run_id}/generate",
    response_model=GeneratedArtifact,
)
async def generate_executive_summary(
    transformation_run_id: int,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    provider: Annotated[GenerationProvider | None, Depends(get_generation_provider)],
) -> GeneratedArtifact:
    transformation = session.scalar(
        select(TransformationRun).where(
            TransformationRun.id == transformation_run_id,
            TransformationRun.owner_id == user.id,
        )
    )
    if transformation is None:
        raise HTTPException(status_code=404, detail="Transformation not found")

    if OutputType.EXECUTIVE_SUMMARY.value not in transformation.selected_output_types:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "output_not_selected",
                "message": "Executive Summary was not selected for this transformation.",
            },
        )

    existing = session.scalar(
        select(ArtifactRun).where(
            ArtifactRun.transformation_run_id == transformation.id,
            ArtifactRun.output_type == OutputType.EXECUTIVE_SUMMARY.value,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "artifact_run_exists",
                "message": "An Executive Summary generation run already exists.",
            },
        )

    artifact_run = ArtifactRun(
        transformation_run_id=transformation.id,
        output_type=OutputType.EXECUTIVE_SUMMARY.value,
        status="pending",
    )
    session.add(artifact_run)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "artifact_run_exists", "message": "Generation run already exists."},
        ) from None

    if provider is None:
        artifact_run.status = "failed"
        session.commit()
        raise HTTPException(
            status_code=503,
            detail={
                "code": "generation_not_configured",
                "message": "Generation is not configured on this server.",
            },
        )

    artifact_run.status = "running"
    session.commit()

    source_version = session.scalar(
        select(SourceVersion)
        .join(Source, Source.id == SourceVersion.source_id)
        .where(
            SourceVersion.id == transformation.source_version_id,
            Source.owner_id == user.id,
        )
    )
    if source_version is None:
        artifact_run.status = "failed"
        session.commit()
        raise HTTPException(status_code=500, detail="Source version is unavailable")

    request = TransformationRequest(
        source_text=source_version.source_text,
        output_types=[OutputType.EXECUTIVE_SUMMARY],
        audience=transformation.audience,
        tone=transformation.tone,
        language=transformation.language,
        detail_level=cast(Literal["brief", "standard", "detailed"], transformation.detail_level),
        objective=transformation.objective,
        style=transformation.style,
    )

    try:
        draft = await ExecutiveSummaryGenerator(provider).generate(
            request, supporting_context=transformation.supporting_context
        )
    except Exception:
        artifact_run.status = "failed"
        session.commit()
        raise HTTPException(
            status_code=502,
            detail={
                "code": "generation_failed",
                "message": "The Executive Summary could not be generated. Please retry.",
            },
        ) from None

    version = ArtifactVersion(
        artifact_run_id=artifact_run.id,
        version_number=1,
        source_version_id=source_version.id,
        content=draft.content,
        provider=draft.provider,
        model=draft.model,
        prompt_version=EXECUTIVE_SUMMARY_PROMPT_VERSION,
        prompt_hash=executive_summary_prompt_hash(),
    )
    session.add(version)
    artifact_run.status = "succeeded"
    session.commit()
    session.refresh(version)

    return GeneratedArtifact(
        status="succeeded",
        artifact_run_id=artifact_run.id,
        output_type="executive_summary",
        artifact_version=GeneratedArtifactVersion(
            id=version.id,
            version_number=version.version_number,
            source_version_id=version.source_version_id,
            source_version_number=source_version.version_number,
            content=version.content,
            provider=draft.provider,
            model=draft.model,
            prompt_version=EXECUTIVE_SUMMARY_PROMPT_VERSION,
            prompt_hash=version.prompt_hash or "",
        ),
    )
