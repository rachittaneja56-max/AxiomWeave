from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_current_user
from app.database import get_db_session
from app.media_renderer import MediaRenderError, probe_media_bytes, validate_image_bytes
from app.media_workflows import (
    MEDIA_AUDIO_MAX_BYTES,
    MEDIA_AUDIO_MAX_DURATION_MS,
    MEDIA_IMAGE_MAX_BYTES,
    MEDIA_IMAGE_MAX_DIMENSION,
    MEDIA_IMAGE_MAX_PIXELS,
    create_media_render,
    review_media_render,
    rights_are_eligible,
)
from app.models import (
    ArtifactVersion,
    Job,
    JobAttempt,
    MediaAsset,
    MediaOperationMetric,
    MediaRender,
    MediaReviewDecision,
    MediaRightsRecord,
    MediaTask,
    User,
    utc_now,
)
from app.private_asset_storage import (
    MAX_RENDERED_MEDIA_BYTES,
    AssetStorageError,
    get_private_asset_store,
)

router = APIRouter()


class SceneMediaSelection(BaseModel):
    scene_index: int = Field(ge=0, le=15)
    visual_asset_id: int | None = Field(default=None, gt=0)
    audio_asset_id: int | None = Field(default=None, gt=0)


def _empty_scene_media() -> list[SceneMediaSelection]:
    return []


class CreateMediaRenderRequest(BaseModel):
    scene_durations_ms: list[int | None] | None = None
    scene_media: list[SceneMediaSelection] = Field(
        default_factory=_empty_scene_media, max_length=16
    )


class RightsUpdateRequest(BaseModel):
    rights_basis: Literal[
        "user_owned", "permission_confirmed", "public_domain", "not_applicable", "unknown"
    ]
    consent_state: Literal["confirmed", "not_applicable", "unknown"]
    consent_required: bool = False
    attribution: str | None = Field(default=None, max_length=500)


class MediaReviewRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=500)


class MediaAssetResponse(BaseModel):
    id: int
    purpose: str
    media_type: str
    byte_size: int
    content_hash: str
    width: int | None
    height: int | None
    duration_ms: int | None
    created_at: datetime
    preview_url: str
    download_url: str


class RightsResponse(BaseModel):
    rights_basis: str
    consent_state: str
    consent_required: bool
    attribution: str | None
    eligible_for_composition: bool


class MediaTaskResponse(BaseModel):
    id: int
    task_key: str
    task_kind: str
    ordinal: int | None
    status: str
    failure_code: str | None
    job_status: str | None
    attempts: int
    assets: list[MediaAssetResponse]


class MediaMetricResponse(BaseModel):
    operation_type: str
    elapsed_ms: int
    input_bytes: int
    output_bytes: int
    output_duration_ms: int | None
    tool_version: str
    external_api_cost: float | None


class MediaReviewResponse(BaseModel):
    reviewer_user_id: int
    primary_asset_hash: str
    decision: str
    note: str | None
    created_at: datetime


class MediaRenderResponse(BaseModel):
    id: int
    artifact_version_id: int
    artifact_family: str
    renderer_profile: str
    renderer_version: str
    render_plan: dict[str, object]
    status: str
    failure_code: str | None
    created_at: datetime
    completed_at: datetime | None
    primary_asset: MediaAssetResponse | None
    tasks: list[MediaTaskResponse]
    metrics: list[MediaMetricResponse]
    reviews: list[MediaReviewResponse]
    review_copy: str


def _asset_response(asset: MediaAsset) -> MediaAssetResponse:
    return MediaAssetResponse(
        id=asset.id,
        purpose=asset.purpose,
        media_type=asset.media_type,
        byte_size=asset.byte_size,
        content_hash=asset.content_hash,
        width=asset.width,
        height=asset.height,
        duration_ms=asset.duration_ms,
        created_at=asset.created_at,
        preview_url=f"/api/media-assets/{asset.id}/preview",
        download_url=f"/api/media-assets/{asset.id}/download",
    )


def _owned_asset(session: Session, asset_id: int, owner_id: int) -> MediaAsset | None:
    return session.scalar(
        select(MediaAsset).where(MediaAsset.id == asset_id, MediaAsset.owner_id == owner_id)
    )


def _rights_record(session: Session, asset_id: int) -> MediaRightsRecord | None:
    return session.scalar(
        select(MediaRightsRecord).where(MediaRightsRecord.media_asset_id == asset_id)
    )


def _rights_response(record: MediaRightsRecord) -> RightsResponse:
    return RightsResponse(
        rights_basis=record.rights_basis,
        consent_state=record.consent_state,
        consent_required=record.consent_required,
        attribution=record.attribution,
        eligible_for_composition=rights_are_eligible(record),
    )


def _owned_render(session: Session, render_id: int, owner_id: int) -> MediaRender | None:
    return session.scalar(
        select(MediaRender).where(MediaRender.id == render_id, MediaRender.owner_id == owner_id)
    )


def _render_response(session: Session, render: MediaRender) -> MediaRenderResponse:
    task_responses: list[MediaTaskResponse] = []
    tasks = session.scalars(
        select(MediaTask)
        .where(MediaTask.render_id == render.id)
        .order_by(MediaTask.ordinal, MediaTask.id)
    ).all()
    for task in tasks:
        job = session.scalar(
            select(Job).where(Job.media_task_id == task.id).order_by(Job.id.desc())
        )
        attempts = (
            session.scalar(
                select(func.count()).select_from(JobAttempt).where(JobAttempt.job_id == job.id)
            )
            if job is not None
            else 0
        )
        assets = session.scalars(
            select(MediaAsset)
            .where(MediaAsset.task_id == task.id, MediaAsset.owner_id == render.owner_id)
            .order_by(MediaAsset.created_at, MediaAsset.id)
        ).all()
        task_responses.append(
            MediaTaskResponse(
                id=task.id,
                task_key=task.task_key,
                task_kind=task.task_kind,
                ordinal=task.ordinal,
                status=task.status,
                failure_code=task.failure_code,
                job_status=job.status if job else None,
                attempts=int(attempts or 0),
                assets=[_asset_response(asset) for asset in assets],
            )
        )
    primary = (
        _owned_asset(session, render.primary_asset_id, render.owner_id)
        if render.primary_asset_id
        else None
    )
    metrics = session.scalars(
        select(MediaOperationMetric)
        .where(MediaOperationMetric.render_id == render.id)
        .order_by(MediaOperationMetric.id)
    ).all()
    reviews = session.scalars(
        select(MediaReviewDecision)
        .where(MediaReviewDecision.media_render_id == render.id)
        .order_by(MediaReviewDecision.created_at, MediaReviewDecision.id)
    ).all()
    return MediaRenderResponse(
        id=render.id,
        artifact_version_id=render.artifact_version_id,
        artifact_family=render.artifact_family,
        renderer_profile=render.renderer_profile,
        renderer_version=render.renderer_version,
        render_plan=render.render_plan,
        status=render.status,
        failure_code=render.failure_code,
        created_at=render.created_at,
        completed_at=render.completed_at,
        primary_asset=_asset_response(primary) if primary is not None else None,
        tasks=task_responses,
        metrics=[
            MediaMetricResponse(
                operation_type=item.operation_type,
                elapsed_ms=item.elapsed_ms,
                input_bytes=item.input_bytes,
                output_bytes=item.output_bytes,
                output_duration_ms=item.output_duration_ms,
                tool_version=item.tool_version,
                external_api_cost=item.external_api_cost,
            )
            for item in metrics
        ],
        reviews=[
            MediaReviewResponse(
                reviewer_user_id=item.owner_id,
                primary_asset_hash=item.primary_asset_hash,
                decision=item.decision,
                note=item.note,
                created_at=item.created_at,
            )
            for item in reviews
        ],
        review_copy=(
            "Media approval covers layout, legibility, timing, and media quality for workflow "
            "use. It does not certify factual claims. Evidence review remains separate."
        ),
    )


@router.post(
    "/artifact-versions/{artifact_version_id}/media-renders",
    response_model=MediaRenderResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_media_render(
    artifact_version_id: int,
    body: CreateMediaRenderRequest,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> MediaRenderResponse:
    artifact = session.get(ArtifactVersion, artifact_version_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact version not found")
    try:
        render = create_media_render(
            session,
            user.id,
            artifact,
            scene_durations_ms=body.scene_durations_ms,
            scene_media=[
                {
                    "scene_index": item.scene_index,
                    "visual_asset_id": item.visual_asset_id,
                    "audio_asset_id": item.audio_asset_id,
                }
                for item in body.scene_media
            ],
        )
        session.commit()
    except ValueError as error:
        session.rollback()
        code = str(error)
        raise HTTPException(
            status_code=409 if "rights" in code else 422,
            detail={"code": code, "message": _safe_message(code)},
        ) from None
    except MediaRenderError:
        session.rollback()
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_media_spec", "message": "The media plan is invalid."},
        ) from None
    session.refresh(render)
    return _render_response(session, render)


@router.get("/media-renders/{render_id}", response_model=MediaRenderResponse)
def get_media_render(
    render_id: int,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> MediaRenderResponse:
    render = _owned_render(session, render_id, user.id)
    if render is None:
        raise HTTPException(status_code=404, detail="Media render not found")
    return _render_response(session, render)


@router.get(
    "/artifact-versions/{artifact_version_id}/media-renders",
    response_model=list[MediaRenderResponse],
)
def list_media_renders(
    artifact_version_id: int,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[MediaRenderResponse]:
    rows = session.scalars(
        select(MediaRender)
        .where(
            MediaRender.artifact_version_id == artifact_version_id,
            MediaRender.owner_id == user.id,
        )
        .order_by(MediaRender.created_at.desc(), MediaRender.id.desc())
    ).all()
    return [_render_response(session, row) for row in rows]


@router.post(
    "/media-renders/{render_id}/retry-failed",
    response_model=MediaRenderResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_failed_media_task(
    render_id: int,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> MediaRenderResponse:
    render = _owned_render(session, render_id, user.id)
    if render is None:
        raise HTTPException(status_code=404, detail="Media render not found")
    task = session.scalar(
        select(MediaTask)
        .where(MediaTask.render_id == render.id, MediaTask.status == "failed")
        .order_by(MediaTask.ordinal, MediaTask.id)
    )
    if task is None:
        raise HTTPException(status_code=409, detail={"code": "no_failed_media_task"})
    job = session.scalar(select(Job).where(Job.media_task_id == task.id).order_by(Job.id.desc()))
    if job is None or job.status != "failed":
        raise HTTPException(status_code=409, detail={"code": "media_task_not_retryable"})
    task.status = "pending"
    task.failure_code = None
    task.completed_at = None
    job.status = "queued"
    job.failure_code = None
    job.terminal_at = None
    render.status = "rendering"
    render.failure_code = None
    render.completed_at = None
    session.commit()
    return _render_response(session, render)


@router.patch("/media-renders/{render_id}/review", response_model=MediaRenderResponse)
def review_media(
    render_id: int,
    body: MediaReviewRequest,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> MediaRenderResponse:
    render = _owned_render(session, render_id, user.id)
    if render is None:
        raise HTTPException(status_code=404, detail="Media render not found")
    try:
        review_media_render(session, render, user.id, body.decision, body.note)
        session.commit()
    except ValueError:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "media_render_not_reviewable",
                "message": "This render is not ready for review.",
            },
        ) from None
    return _render_response(session, render)


@router.post("/media-assets/upload", response_model=MediaAssetResponse, status_code=201)
async def upload_scene_asset(
    file: Annotated[UploadFile, File()],
    purpose: Annotated[Literal["scene_visual_upload", "scene_audio_upload"], Form()],
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> MediaAssetResponse:
    filename = file.filename or ""
    suffix = filename.rpartition(".")[2].lower()
    limit = MEDIA_IMAGE_MAX_BYTES if purpose == "scene_visual_upload" else MEDIA_AUDIO_MAX_BYTES
    try:
        content = await file.read(limit + 1)
    finally:
        await file.close()
    if len(content) > limit:
        raise HTTPException(status_code=413, detail={"code": "media_file_too_large"})
    width = height = duration_ms = None
    if purpose == "scene_visual_upload":
        if suffix not in {"png", "jpg", "jpeg"}:
            raise HTTPException(status_code=415, detail={"code": "unsupported_image_format"})
        try:
            width, height = validate_image_bytes(
                content,
                suffix,
                max_dimension=MEDIA_IMAGE_MAX_DIMENSION,
                max_pixels=MEDIA_IMAGE_MAX_PIXELS,
            )
        except MediaRenderError as error:
            raise HTTPException(
                status_code=422 if error.code == "image_dimensions_out_of_range" else 415,
                detail={"code": error.code},
            ) from None
        media_type = "image/png" if suffix == "png" else "image/jpeg"
    else:
        if suffix not in {"wav", "mp3", "m4a"}:
            raise HTTPException(status_code=415, detail={"code": "unsupported_audio_format"})
        try:
            probe = probe_media_bytes(content, suffix, max_duration_ms=MEDIA_AUDIO_MAX_DURATION_MS)
            if probe.has_video or not probe.has_audio:
                raise MediaRenderError("invalid_audio_stream")
            formats = set(probe.format_name.split(","))
            permitted_formats = {
                "wav": {"wav"},
                "mp3": {"mp3"},
                "m4a": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
            }
            if not formats.intersection(permitted_formats[suffix]):
                raise MediaRenderError("audio_container_mismatch")
        except MediaRenderError as error:
            if error.code == "ffprobe_unavailable":
                raise HTTPException(status_code=503, detail={"code": error.code}) from None
            raise HTTPException(status_code=415, detail={"code": "invalid_audio"}) from None
        media_type = {"wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4"}[suffix]
        duration_ms = probe.duration_ms
    store = get_private_asset_store()
    stored_key: str | None = None
    try:
        stored = store.store(content, max_bytes=limit)
        stored_key = stored.storage_key
        asset = MediaAsset(
            owner_id=user.id,
            purpose=purpose,
            media_type=media_type,
            byte_size=stored.byte_size,
            content_hash=stored.content_hash,
            storage_key=stored.storage_key,
            width=width,
            height=height,
            duration_ms=duration_ms,
        )
        session.add(asset)
        session.flush()
        session.add(
            MediaRightsRecord(
                owner_id=user.id,
                media_asset_id=asset.id,
                rights_basis="unknown",
                consent_state="unknown",
                consent_required=False,
            )
        )
        session.commit()
        session.refresh(asset)
        return _asset_response(asset)
    except Exception:
        session.rollback()
        if stored_key is not None:
            try:
                store.delete(stored_key)
            except OSError:
                pass
        raise HTTPException(status_code=500, detail={"code": "media_asset_save_failed"}) from None


@router.get("/media-assets/{asset_id}", response_model=MediaAssetResponse)
def get_media_asset(
    asset_id: int,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> MediaAssetResponse:
    asset = _owned_asset(session, asset_id, user.id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Media asset not found")
    return _asset_response(asset)


@router.get("/media-assets/{asset_id}/rights", response_model=RightsResponse)
def get_media_asset_rights(
    asset_id: int,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> RightsResponse:
    asset = _owned_asset(session, asset_id, user.id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Media asset not found")
    record = _rights_record(session, asset.id)
    if record is None:
        raise HTTPException(status_code=404, detail="Media rights record not found")
    return _rights_response(record)


@router.patch("/media-assets/{asset_id}/rights", response_model=RightsResponse)
def update_media_asset_rights(
    asset_id: int,
    body: RightsUpdateRequest,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> RightsResponse:
    asset = _owned_asset(session, asset_id, user.id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Media asset not found")
    record = _rights_record(session, asset.id)
    if record is None:
        raise HTTPException(status_code=404, detail="Media rights record not found")
    record.rights_basis = body.rights_basis
    record.consent_state = body.consent_state
    record.consent_required = body.consent_required
    record.attribution = body.attribution.strip() if body.attribution else None
    if rights_are_eligible(record):
        record.confirmed_by_user_id = user.id
        record.confirmed_at = utc_now()
    else:
        record.confirmed_by_user_id = None
        record.confirmed_at = None
    session.commit()
    return _rights_response(record)


@router.get("/media-assets/{asset_id}/preview")
def preview_media_asset(
    asset_id: int,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> Response:
    return _media_asset_response(asset_id, user, session, inline=True)


@router.get("/media-assets/{asset_id}/download")
def download_media_asset(
    asset_id: int,
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> Response:
    return _media_asset_response(asset_id, user, session, inline=False)


def _media_asset_response(asset_id: int, user: User, session: Session, *, inline: bool) -> Response:
    asset = _owned_asset(session, asset_id, user.id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Media asset not found")
    max_bytes = MAX_RENDERED_MEDIA_BYTES if asset.render_id is not None else MEDIA_AUDIO_MAX_BYTES
    try:
        content = get_private_asset_store().read(asset.storage_key, max_bytes=max_bytes)
    except AssetStorageError:
        raise HTTPException(status_code=404, detail="Media asset not found") from None
    suffix = {
        "image/svg+xml": "svg",
        "image/png": "png",
        "image/jpeg": "jpg",
        "video/mp4": "mp4",
        "text/vtt": "vtt",
        "audio/wav": "wav",
        "audio/mpeg": "mp3",
        "audio/mp4": "m4a",
    }.get(asset.media_type, "bin")
    disposition = "inline" if inline else "attachment"
    return Response(
        content=content,
        media_type=asset.media_type,
        headers={
            "Content-Disposition": (
                f'{disposition}; filename="axiomweave-{asset.purpose}-{asset.id}.{suffix}"'
            ),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _safe_message(code: str) -> str:
    return {
        "media_input_rights_unresolved": "Confirm the asset rights and applicable consent first.",
        "media_input_not_found": "The selected media asset is unavailable.",
        "scene_duration_out_of_range": "Scene timing is outside supported limits.",
        "video_duration_limit_exceeded": "The video is longer than the supported limit.",
    }.get(code, "The media request could not be created.")
