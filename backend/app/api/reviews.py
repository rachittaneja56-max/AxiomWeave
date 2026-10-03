from hashlib import sha256
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.evidence import get_analysis_provider, process_claim_scan
from app.artifact_contracts import ARTIFACT_CONTRACTS, validate_artifact_content
from app.artifact_lineage import persist_artifact_blocks
from app.audit import record_audit_event
from app.auth import require_current_user
from app.claim_scanning import create_or_get_claim_scan
from app.commands import (
    ReviewArtifactVersionCommand,
    SaveArtifactVersionCommand,
    dispatch_application_command,
    dispatch_manual_application_command_async,
)
from app.database import get_db_session
from app.domain.transformation import OutputType
from app.generation import StructuredGenerationProvider
from app.model_policy import provider_profile_allows_source, resolve_model_profile
from app.models import (
    ArtifactReviewDecision,
    ArtifactRun,
    ArtifactVersion,
    ClaimScan,
    SourceVersion,
    TransformationRun,
    User,
    utc_now,
)

router = APIRouter()


class EditArtifactRequest(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)


class ReviewArtifactRequest(BaseModel):
    review_status: Literal["accepted", "rejected"]
    note: str | None = Field(default=None, max_length=500)


class ArtifactVersionResponse(BaseModel):
    id: int
    artifact_run_id: int
    version_number: int
    source_version_id: int
    context_manifest_id: int | None
    content: str
    provider: str | None
    model: str | None
    prompt_version: str | None
    prompt_hash: str | None
    artifact_schema_version: str | None
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
        context_manifest_id=version.context_manifest_id,
        content=version.content,
        provider=version.provider,
        model=version.model,
        prompt_version=version.prompt_version,
        prompt_hash=version.prompt_hash,
        artifact_schema_version=version.artifact_schema_version,
        review_status=cast(Literal["draft", "accepted", "rejected"], version.review_status),
    )


@router.post("/artifact-runs/{artifact_run_id}/versions", response_model=ArtifactVersionResponse)
async def create_edited_artifact_version(
    artifact_run_id: int,
    request: EditArtifactRequest,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    provider: Annotated[StructuredGenerationProvider | None, Depends(get_analysis_provider)],
    http_request: Request,
) -> ArtifactVersionResponse:
    result = await dispatch_manual_application_command_async(
        SaveArtifactVersionCommand(artifact_run_id=artifact_run_id, content=request.content),
        user=user,
        session=session,
        provider=provider,
        request_id=getattr(http_request.state, "request_id", None),
    )
    return cast(ArtifactVersionResponse, result)


async def execute_save_artifact_version(
    command: SaveArtifactVersionCommand,
    *,
    user: User,
    session: Session,
    provider: StructuredGenerationProvider | None,
    request_id: str | None,
) -> ArtifactVersionResponse:
    artifact_run_id = command.artifact_run_id
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

    content = command.content.strip()
    if not content:
        raise HTTPException(
            status_code=422,
            detail={"code": "empty_artifact", "message": "Artifact content cannot be empty."},
        )
    output_type = OutputType(artifact_run.output_type)
    try:
        content = validate_artifact_content(output_type, content)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail={
                "code": f"invalid_{output_type.value}",
                "message": "Artifact content does not match the required family contract.",
            },
        ) from None
    contract = ARTIFACT_CONTRACTS[output_type]
    edit_prompt_hash = sha256(
        f"manual_edit_v1:{output_type.value}:{contract.schema_version}".encode()
    ).hexdigest()

    version = ArtifactVersion(
        artifact_run_id=artifact_run.id,
        version_number=previous.version_number + 1,
        source_version_id=previous.source_version_id,
        content=content,
        context_manifest_id=previous.context_manifest_id,
        provider="human",
        model="manual-edit",
        prompt_version="manual_edit_v1",
        prompt_hash=edit_prompt_hash,
        artifact_schema_version=contract.schema_version,
        review_status="draft",
        origin="manual_edit",
    )
    session.add(version)
    session.flush()
    record_audit_event(
        session,
        owner_id=user.id,
        action_type="artifact_version.edited",
        target_type="artifact_version",
        target_id=version.id,
        request_id=request_id,
        safe_metadata={"artifact_run_id": artifact_run.id},
    )
    persist_artifact_blocks(
        session,
        version,
        output_type,
        parent_version=previous,
        origin="manual_edit",
    )
    create_or_get_claim_scan(session, user.id, version)
    session.commit()
    if provider is not None:
        scan = session.scalar(select(ClaimScan).where(ClaimScan.artifact_version_id == version.id))
        source_version = session.get(SourceVersion, version.source_version_id)
        eligible = source_version is not None and provider_profile_allows_source(
            resolve_model_profile("evidence_analysis"), source_version.sensitivity_class
        )
        if scan is not None and source_version is not None and eligible:
            try:
                await process_claim_scan(session, user, scan, version, source_version, provider)
            except Exception:
                # The immutable edit remains successful; its persisted scan state stays visible.
                session.rollback()
    session.refresh(version)
    return _version_response(version)


def execute_review_artifact_version(
    artifact_version_id: int,
    review_status: Literal["accepted", "rejected"],
    note: str | None,
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

    version.review_status = review_status
    session.add(
        ArtifactReviewDecision(
            owner_id=user.id,
            artifact_version_id=version.id,
            decision=review_status,
            note=note.strip() if note else None,
            created_at=utc_now(),
        )
    )
    session.commit()
    session.refresh(version)
    return _version_response(version)


@router.patch(
    "/artifact-versions/{artifact_version_id}/review",
    response_model=ArtifactVersionResponse,
)
def set_artifact_review_status(
    artifact_version_id: int,
    body: ReviewArtifactRequest,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> ArtifactVersionResponse:
    result = dispatch_application_command(
        ReviewArtifactVersionCommand(
            artifact_version_id=artifact_version_id,
            review_status=body.review_status,
            note=body.note,
        ),
        session=session,
        user=user,
        request_id=getattr(request.state, "request_id", None),
    )
    return cast(ArtifactVersionResponse, result)
