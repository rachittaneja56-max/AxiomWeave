import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth import require_current_user
from app.database import get_db_session
from app.model_policy import current_model_registry
from app.models import ArtifactRun, Job, MediaRender, MediaTask, TransformationRun, User
from app.private_asset_storage import private_asset_store_is_configured
from app.settings import get_settings

router = APIRouter()
EXPECTED_SCHEMA_REVISION = "a41f028bc9e2"


class HealthResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    database: str
    migration_revision: str | None
    migration_state: str
    private_asset_storage: str
    ffmpeg: bool
    ffprobe: bool
    model_profiles: list[dict[str, object]]
    registration_enabled: bool


class JobOperationsResponse(BaseModel):
    queued: int
    running: int
    failed: int
    stale_leases: int
    oldest_queued_age_seconds: int | None
    by_resource_class: dict[str, dict[str, int]]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=ReadinessResponse)
def readiness(session: Annotated[Session, Depends(get_db_session)]) -> ReadinessResponse:
    settings = get_settings()
    database = "unavailable"
    revision: str | None = None
    migration_state = "unavailable"
    try:
        session.execute(text("SELECT 1"))
        database = session.bind.dialect.name if session.bind is not None else "connected"
        revision = session.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
        migration_state = "current" if revision == EXPECTED_SCHEMA_REVISION else "outdated"
    except Exception:
        session.rollback()
    if not private_asset_store_is_configured():
        storage_state = "missing"
    elif settings.private_asset_backend.strip().lower() == "local":
        asset_dir: Path = settings.private_asset_dir
        asset_parent = asset_dir if asset_dir.exists() else asset_dir.parent
        storage_state = "usable" if asset_parent.exists() and asset_parent.is_dir() else "missing"
        if storage_state == "usable" and not os.access(asset_parent, os.W_OK):
            storage_state = "not_writable"
    else:
        storage_state = "configured"
    ffmpeg_available = shutil.which("ffmpeg") is not None
    ffprobe_available = shutil.which("ffprobe") is not None
    profiles = current_model_registry(settings)
    degraded = (
        database == "unavailable"
        or migration_state != "current"
        or storage_state not in {"usable", "configured"}
    )
    return ReadinessResponse(
        status="degraded" if degraded else "ready",
        database=database,
        migration_revision=str(revision) if revision else None,
        migration_state=migration_state,
        private_asset_storage=storage_state,
        ffmpeg=ffmpeg_available,
        ffprobe=ffprobe_available,
        model_profiles=profiles,
        registration_enabled=settings.allow_registration,
    )


@router.get("/ops/jobs", response_model=JobOperationsResponse)
def job_operations(
    user: Annotated[User, Depends(require_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> JobOperationsResponse:
    artifact_job_ids = (
        select(Job.id)
        .join(ArtifactRun, ArtifactRun.id == Job.artifact_run_id)
        .join(TransformationRun, TransformationRun.id == ArtifactRun.transformation_run_id)
        .where(TransformationRun.owner_id == user.id)
    )
    media_job_ids = (
        select(Job.id)
        .join(MediaTask, MediaTask.id == Job.media_task_id)
        .join(MediaRender, MediaRender.id == MediaTask.render_id)
        .where(MediaRender.owner_id == user.id)
    )
    own_jobs = select(Job).where(Job.id.in_(artifact_job_ids.union(media_job_ids)))
    jobs = session.scalars(own_jobs).all()
    now = datetime.now(UTC)
    state = {name: 0 for name in ("queued", "running", "failed")}
    stale = 0
    oldest: datetime | None = None
    resource: dict[str, dict[str, int]] = {}
    for job in jobs:
        if job.status in state:
            state[job.status] += 1
        if job.status == "queued" and (oldest is None or job.created_at < oldest):
            oldest = job.created_at
        if job.status == "running" and job.lease_expires_at is not None:
            lease_expiry = job.lease_expires_at
            if lease_expiry.tzinfo is None:
                lease_expiry = lease_expiry.replace(tzinfo=UTC)
            if lease_expiry < now:
                stale += 1
        counts = resource.setdefault(job.resource_class, {"queued": 0, "running": 0, "failed": 0})
        if job.status in counts:
            counts[job.status] += 1
    queued_age = None
    if oldest is not None:
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=UTC)
        queued_age = max(0, int((now - oldest).total_seconds()))
    return JobOperationsResponse(
        queued=state["queued"],
        running=state["running"],
        failed=state["failed"],
        stale_leases=stale,
        oldest_queued_age_seconds=queued_age,
        by_resource_class=resource,
    )
