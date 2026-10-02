import json
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_current_user
from app.database import get_db_session
from app.models import ArtifactRun, ArtifactVersion, TransformationRun, User
from app.presentation import PresentationSpec

router = APIRouter()


class EditArtifactRequest(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)


class ReviewArtifactRequest(BaseModel):
    review_status: Literal["accepted", "rejected"]


class ArtifactVersionResponse(BaseModel):
    id: int
    artifact_run_id: int
    version_number: int
    source_version_id: int
    content: str
    provider: str | None
    model: str | None
    prompt_version: str | None
    prompt_hash: str | None
    review_status: Literal["draft", "accepted", "rejected"]


def _owned_artifact_run(session: Session, user: User, artifact_run_id: int) -> ArtifactRun | None:
    return session.scalar(
        select(ArtifactRun)
        .join(TransformationRun, TransformationRun.id == ArtifactRun.transformation_run_id)
        .where(ArtifactRun.id == artifact_run_id, TransformationRun.owner_id == user.id)
    )


def _version_response(version: ArtifactVersion) -> ArtifactVersionResponse:
    return ArtifactVersionResponse(
        id=version.id,
        artifact_run_id=version.artifact_run_id,
        version_number=version.version_number,
        source_version_id=version.source_version_id,
        content=version.content,
        provider=version.provider,
        model=version.model,
        prompt_version=version.prompt_version,
        prompt_hash=version.prompt_hash,
        review_status=cast(Literal["draft", "accepted", "rejected"], version.review_status),
    )


@router.post("/artifact-runs/{artifact_run_id}/versions", response_model=ArtifactVersionResponse)
def create_edited_artifact_version(
    artifact_run_id: int,
    request: EditArtifactRequest,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ArtifactVersionResponse:
    artifact_run = _owned_artifact_run(session, user, artifact_run_id)
    if artifact_run is None:
        raise HTTPException(status_code=404, detail="Artifact run not found")
    previous = session.scalar(
        select(ArtifactVersion)
        .where(ArtifactVersion.artifact_run_id == artifact_run.id)
        .order_by(ArtifactVersion.version_number.desc())
    )
    if previous is None:
        raise HTTPException(status_code=409, detail="Generate this artifact before editing it")

    content = request.content.strip()
    if not content:
        raise HTTPException(
            status_code=422,
            detail={"code": "empty_artifact", "message": "Artifact content cannot be empty."},
        )
    if artifact_run.output_type == "presentation":
        try:
            presentation = PresentationSpec.model_validate_json(content)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_presentation",
                    "message": "Presentation content does not match the required structure.",
                },
            ) from None
        content = json.dumps(
            presentation.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    version = ArtifactVersion(
        artifact_run_id=artifact_run.id,
        version_number=previous.version_number + 1,
        source_version_id=previous.source_version_id,
        content=content,
        provider=None,
        model=None,
        prompt_version=None,
        prompt_hash=None,
        review_status="draft",
    )
    session.add(version)
    session.commit()
    session.refresh(version)
    return _version_response(version)


@router.patch(
    "/artifact-versions/{artifact_version_id}/review",
    response_model=ArtifactVersionResponse,
)
def set_artifact_review_status(
    artifact_version_id: int,
    request: ReviewArtifactRequest,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ArtifactVersionResponse:
    version = session.scalar(
        select(ArtifactVersion)
        .join(ArtifactRun, ArtifactRun.id == ArtifactVersion.artifact_run_id)
        .join(TransformationRun, TransformationRun.id == ArtifactRun.transformation_run_id)
        .where(ArtifactVersion.id == artifact_version_id, TransformationRun.owner_id == user.id)
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Artifact version not found")

    latest_id = session.scalar(
        select(ArtifactVersion.id)
        .where(ArtifactVersion.artifact_run_id == version.artifact_run_id)
        .order_by(ArtifactVersion.version_number.desc())
    )
    if latest_id != version.id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "version_not_latest",
                "message": "Only the latest version can be reviewed.",
            },
        )

    version.review_status = request.review_status
    session.commit()
    session.refresh(version)
    return _version_response(version)
