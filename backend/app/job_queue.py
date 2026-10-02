from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import Session, aliased

from app.models import ArtifactRun, Job, JobAttempt, JobDependency, SourceVersion, utc_now

MODEL_IO = "model_io"
ARTIFACT_GENERATION = "artifact_generation"
DEFAULT_LEASE_SECONDS = 180


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    job_id: int
    attempt_number: int
    worker_id: str


def enqueue_artifact_job(
    session: Session,
    artifact_run: ArtifactRun,
    source_version: SourceVersion,
    base_artifact_version_id: int | None = None,
) -> Job:
    job = Job(
        artifact_run_id=artifact_run.id,
        source_version_id=source_version.id,
        base_artifact_version_id=base_artifact_version_id,
        job_type=ARTIFACT_GENERATION,
        resource_class=MODEL_IO,
        status="queued",
    )
    session.add(job)
    session.flush()
    return job


def add_job_dependency(session: Session, job_id: int, depends_on_job_id: int) -> JobDependency:
    if job_id == depends_on_job_id:
        raise ValueError("A job cannot depend on itself")
    if session.get(Job, job_id) is None or session.get(Job, depends_on_job_id) is None:
        raise ValueError("Both dependency jobs must exist")

    edges = session.execute(select(JobDependency.job_id, JobDependency.depends_on_job_id)).all()
    parents: dict[int, list[int]] = {}
    for child, parent in edges:
        parents.setdefault(child, []).append(parent)
    pending = [depends_on_job_id]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if current == job_id:
            raise ValueError("Job dependency would create a cycle")
        if current in visited:
            continue
        visited.add(current)
        pending.extend(parents.get(current, ()))

    edge = JobDependency(job_id=job_id, depends_on_job_id=depends_on_job_id)
    session.add(edge)
    session.flush()
    return edge


def _fail_stale_jobs(session: Session, now: datetime) -> None:
    stale_jobs = list(
        session.scalars(
            select(Job).where(
                Job.status == "running",
                Job.lease_expires_at <= now,
            )
        ).all()
    )
    for job in stale_jobs:
        attempts = list(
            session.scalars(
                select(JobAttempt).where(
                    JobAttempt.job_id == job.id, JobAttempt.status == "running"
                )
            ).all()
        )
        for attempt in attempts:
            attempt.status = "failed"
            attempt.failure_code = "worker_lease_expired"
            attempt.finished_at = now
        job.status = "failed"
        job.failure_code = "worker_lease_expired"
        job.worker_id = None
        job.lease_expires_at = None
        job.terminal_at = now
        artifact_run = session.get(ArtifactRun, job.artifact_run_id)
        if artifact_run is not None:
            artifact_run.status = "failed"
    if stale_jobs:
        session.flush()


def _fail_jobs_with_failed_dependencies(session: Session, now: datetime) -> None:
    dependency = aliased(Job)
    failed_dependency_exists = exists(
        select(JobDependency.id)
        .join(dependency, dependency.id == JobDependency.depends_on_job_id)
        .where(JobDependency.job_id == Job.id, dependency.status == "failed")
    )
    while True:
        blocked = list(
            session.scalars(
                select(Job).where(Job.status == "queued", failed_dependency_exists)
            ).all()
        )
        if not blocked:
            return
        for job in blocked:
            job.status = "failed"
            job.failure_code = "dependency_failed"
            job.terminal_at = now
            artifact_run = session.get(ArtifactRun, job.artifact_run_id)
            if artifact_run is not None:
                artifact_run.status = "failed"
        session.flush()


def claim_next_job(
    session: Session,
    resource_class: str,
    worker_id: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> ClaimedJob | None:
    if resource_class != MODEL_IO:
        raise ValueError("Unsupported worker resource class")
    if not worker_id or len(worker_id) > 160:
        raise ValueError("Worker ID must contain 1 to 160 characters")
    if lease_seconds <= 0:
        raise ValueError("Lease duration must be positive")

    connection = session.connection()
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    now = utc_now()
    _fail_stale_jobs(session, now)
    _fail_jobs_with_failed_dependencies(session, now)

    dependency = aliased(Job)
    succeeded_dependency_exists = exists(
        select(dependency.id).where(
            dependency.id == JobDependency.depends_on_job_id,
            dependency.status == "succeeded",
        )
    )
    has_incomplete_dependency = exists(
        select(JobDependency.id).where(
            JobDependency.job_id == Job.id,
            ~succeeded_dependency_exists,
        )
    )
    candidate_id = (
        select(Job.id)
        .where(
            Job.status == "queued",
            Job.resource_class == resource_class,
            ~has_incomplete_dependency,
        )
        .order_by(Job.created_at, Job.id)
        .limit(1)
        .scalar_subquery()
    )
    claimed_id = session.scalar(
        update(Job)
        .where(
            Job.id == candidate_id,
            Job.status == "queued",
            Job.resource_class == resource_class,
        )
        .values(
            status="running",
            worker_id=worker_id,
            claimed_at=now,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
        )
        .returning(Job.id)
    )
    if claimed_id is None:
        session.commit()
        return None

    attempt_number = (
        session.scalar(
            select(func.coalesce(func.max(JobAttempt.attempt_number), 0)).where(
                JobAttempt.job_id == claimed_id
            )
        )
        or 0
    ) + 1
    attempt = JobAttempt(
        job_id=claimed_id,
        attempt_number=attempt_number,
        worker_id=worker_id,
        status="running",
        started_at=now,
    )
    session.add(attempt)
    job = session.get(Job, claimed_id)
    if job is None:
        session.rollback()
        raise RuntimeError("Claimed job disappeared")
    user_run = session.get(ArtifactRun, job.artifact_run_id)
    if user_run is None:
        session.rollback()
        raise RuntimeError("Claimed job has no artifact run")
    user_run.status = "running"
    session.commit()
    return ClaimedJob(claimed_id, attempt_number, worker_id)


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
