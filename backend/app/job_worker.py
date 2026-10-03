import asyncio
import json
import socket
from argparse import ArgumentParser
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.artifact_generators import (
    build_artifact_request,
    build_targeted_update_request,
    generate_artifact,
    generate_targeted_update,
)
from app.context_planning import ContextPlanNeedsReview, context_text_from_manifest
from app.database import create_database_engine, create_session_factory
from app.domain.transformation import OutputType
from app.executive_summary import ExecutiveSummaryGenerationError
from app.generation import GenerationProvider, GenerationProviderError
from app.job_queue import (
    DEFAULT_LEASE_SECONDS,
    MODEL_IO,
    ClaimedJob,
    claim_next_job,
    normalize_utc,
)
from app.models import (
    ArtifactRun,
    ArtifactVersion,
    ContextManifest,
    Job,
    JobAttempt,
    SourceVersion,
    TransformationRun,
    utc_now,
)
from app.provider_factory import get_generation_provider
from app.settings import get_settings
from app.source_revisions import diff_source_versions

DEFAULT_POLL_SECONDS = 1.0


def _record_failure(
    session_factory: sessionmaker[Session], claim: ClaimedJob, failure_code: str
) -> None:
    with session_factory() as session:
        job = session.scalar(select(Job).where(Job.id == claim.job_id).with_for_update())
        if job is None or job.status != "running" or job.worker_id != claim.worker_id:
            session.rollback()
            return
        attempt = session.scalar(
            select(JobAttempt).where(
                JobAttempt.job_id == claim.job_id,
                JobAttempt.attempt_number == claim.attempt_number,
                JobAttempt.status == "running",
            )
        )
        if attempt is None:
            session.rollback()
            return
        now = utc_now()
        if job.lease_expires_at is not None and normalize_utc(job.lease_expires_at) <= now:
            failure_code = "worker_lease_expired"
        job.status = "failed"
        job.failure_code = failure_code
        job.worker_id = None
        job.lease_expires_at = None
        job.terminal_at = now
        attempt.status = "failed"
        attempt.failure_code = failure_code
        attempt.finished_at = now
        artifact_run = session.get(ArtifactRun, job.artifact_run_id)
        if artifact_run is not None:
            artifact_run.status = "failed"
        session.commit()


def _persist_success(
    session_factory: sessionmaker[Session],
    claim: ClaimedJob,
    content: str,
    provider_name: str,
    model_name: str,
    prompt_version: str,
    prompt_hash: str,
) -> bool:
    try:
        with session_factory() as session:
            job = session.scalar(select(Job).where(Job.id == claim.job_id).with_for_update())
            if job is None or job.status != "running" or job.worker_id != claim.worker_id:
                session.rollback()
                return False
            attempt = session.scalar(
                select(JobAttempt).where(
                    JobAttempt.job_id == claim.job_id,
                    JobAttempt.attempt_number == claim.attempt_number,
                    JobAttempt.status == "running",
                )
            )
            artifact_run = session.get(ArtifactRun, job.artifact_run_id)
            if attempt is None or artifact_run is None:
                session.rollback()
                return False
            now = utc_now()
            if job.lease_expires_at is not None and normalize_utc(job.lease_expires_at) <= now:
                job.status = "failed"
                job.failure_code = "worker_lease_expired"
                job.worker_id = None
                job.lease_expires_at = None
                job.terminal_at = now
                attempt.status = "failed"
                attempt.failure_code = "worker_lease_expired"
                attempt.finished_at = now
                artifact_run.status = "failed"
                session.commit()
                return False

            latest_version_number = session.scalar(
                select(func.max(ArtifactVersion.version_number)).where(
                    ArtifactVersion.artifact_run_id == artifact_run.id
                )
            )
            session.add(
                ArtifactVersion(
                    artifact_run_id=artifact_run.id,
                    version_number=(latest_version_number or 0) + 1,
                    source_version_id=job.source_version_id,
                    context_manifest_id=job.context_manifest_id,
                    content=content,
                    provider=provider_name,
                    model=model_name,
                    prompt_version=prompt_version,
                    prompt_hash=prompt_hash,
                )
            )
            attempt.status = "succeeded"
            attempt.finished_at = now
            job.status = "succeeded"
            job.worker_id = None
            job.lease_expires_at = None
            job.terminal_at = now
            artifact_run.status = "succeeded"
            session.commit()
            return True
    except Exception:
        _record_failure(session_factory, claim, "persistence_failed")
        return False


def _artifact_inputs(
    session_factory: sessionmaker[Session], claim: ClaimedJob
) -> tuple[
    ArtifactRun,
    TransformationRun,
    SourceVersion,
    ArtifactVersion | None,
    SourceVersion | None,
    str | None,
    str,
]:
    with session_factory() as session:
        job = session.get(Job, claim.job_id)
        if job is None or job.status != "running" or job.worker_id != claim.worker_id:
            raise RuntimeError("Claimed job is no longer running")
        artifact_run = session.get(ArtifactRun, job.artifact_run_id)
        transformation = (
            session.get(TransformationRun, artifact_run.transformation_run_id)
            if artifact_run is not None
            else None
        )
        source_version = session.get(SourceVersion, job.source_version_id)
        if artifact_run is None or transformation is None or source_version is None:
            raise RuntimeError("Claimed job input is unavailable")
        if job.context_manifest_id is None:
            # Compatibility for jobs that were already persisted before this migration.
            context_source_text = source_version.source_text
        else:
            manifest = session.get(ContextManifest, job.context_manifest_id)
            if manifest is None or manifest.owner_id != transformation.owner_id:
                raise RuntimeError("Claimed job context manifest is unavailable")
            context_source_text = context_text_from_manifest(session, manifest)
        base_version = (
            session.get(ArtifactVersion, job.base_artifact_version_id)
            if job.base_artifact_version_id is not None
            else None
        )
        if job.base_artifact_version_id is not None and base_version is None:
            raise RuntimeError("Targeted update base artifact is unavailable")
        if base_version is not None and base_version.artifact_run_id != artifact_run.id:
            raise RuntimeError("Targeted update base artifact does not belong to this run")
        prior_source = (
            session.get(SourceVersion, base_version.source_version_id)
            if base_version is not None
            else None
        )
        changed_material = None
        if base_version is not None:
            if prior_source is None:
                raise RuntimeError("Targeted update prior source is unavailable")
            changes = diff_source_versions(session, prior_source, source_version)
            changed_material = json.dumps(
                [
                    {
                        "change_type": item.change_type,
                        "locator": item.locator,
                        "old_text": item.old_text,
                        "new_text": item.new_text,
                    }
                    for item in changes
                ],
                ensure_ascii=False,
            )
        return (
            artifact_run,
            transformation,
            source_version,
            base_version,
            prior_source,
            changed_material,
            context_source_text,
        )


async def process_one_job(
    session_factory: sessionmaker[Session],
    provider: GenerationProvider | None,
    worker_id: str,
    resource_class: str = MODEL_IO,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> bool:
    with session_factory() as session:
        claim = claim_next_job(session, resource_class, worker_id, lease_seconds)
    if claim is None:
        return False
    if provider is None:
        _record_failure(session_factory, claim, "generation_not_configured")
        return True

    try:
        (
            artifact_run,
            transformation,
            _source_version,
            base_version,
            prior_source,
            changed_material,
            context_source_text,
        ) = _artifact_inputs(session_factory, claim)
        output_type = OutputType(artifact_run.output_type)
        if base_version is None:
            request = build_artifact_request(transformation, context_source_text, output_type)
            draft = await generate_artifact(
                provider,
                request,
                transformation.supporting_context,
                output_type,
            )
        else:
            if prior_source is None or changed_material is None:
                raise RuntimeError("Targeted update inputs are incomplete")
            request = build_targeted_update_request(
                transformation,
                output_type,
                context_source_text,
                prior_source.source_text,
                changed_material,
                base_version.content,
            )
            draft = await generate_targeted_update(provider, request, output_type)
    except ContextPlanNeedsReview:
        _record_failure(session_factory, claim, "context_requires_review")
        return True
    except (ValueError, TypeError, ExecutiveSummaryGenerationError):
        _record_failure(session_factory, claim, "invalid_output")
        return True
    except GenerationProviderError:
        _record_failure(session_factory, claim, "generation_failed")
        return True
    except Exception:
        _record_failure(session_factory, claim, "generation_failed")
        return True

    _persist_success(
        session_factory,
        claim,
        draft.content,
        draft.provider,
        draft.model,
        draft.prompt_version,
        draft.prompt_hash,
    )
    return True


async def run_worker(
    session_factory: sessionmaker[Session],
    provider: GenerationProvider | None,
    worker_id: str,
    once: bool = False,
) -> None:
    while True:
        processed = await process_one_job(session_factory, provider, worker_id)
        if once:
            return
        if not processed:
            await asyncio.sleep(DEFAULT_POLL_SECONDS)


def _worker_id() -> str:
    return f"{socket.gethostname()}:{uuid4().hex[:12]}"


def main() -> None:
    parser = ArgumentParser(description="Run one bounded AxiomWeave model I/O worker")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job")
    args = parser.parse_args()
    engine = create_database_engine(get_settings().database_url)
    session_factory = create_session_factory(engine)
    try:
        asyncio.run(run_worker(session_factory, get_generation_provider(), _worker_id(), args.once))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
