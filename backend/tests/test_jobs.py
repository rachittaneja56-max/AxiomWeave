import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.generation import GenerationProviderError, GenerationRequest, GenerationResult
from app.job_queue import MODEL_IO, add_job_dependency, claim_next_job, enqueue_artifact_job
from app.job_worker import process_one_job
from app.models import (
    ArtifactRun,
    ArtifactVersion,
    ContextManifest,
    Job,
    JobAttempt,
    Source,
    SourceVersion,
    TransformationRun,
    User,
    utc_now,
)
from app.source_versions import SourceAssetInput, create_source_pack_version, create_source_version


class FakeProvider:
    def __init__(self, text: str = "A generated artifact.", fail: bool = False) -> None:
        self.text = text
        self.fail = fail
        self.requests: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.requests.append(request)
        if self.fail:
            raise GenerationProviderError()
        return GenerationResult(self.text, "test-provider", "deterministic")


def _queued_job(
    factory: sessionmaker[Session], source_text: str = "Source V1", output_type: str = "advisory"
) -> tuple[int, int, int]:
    with factory() as session:
        owner = User(username=f"job-owner-{utc_now().timestamp()}", password_hash="!test!")
        session.add(owner)
        session.flush()
        source = Source(owner_id=owner.id, title="Job source")
        session.add(source)
        session.flush()
        source_version = create_source_version(session, source, source_text)
        transformation = TransformationRun(
            owner_id=owner.id,
            source_version_id=source_version.id,
            supporting_context="Supporting context.",
            audience="Reviewers",
            tone="Clear",
            language="English",
            detail_level="standard",
            objective="Inform",
            style="Plain language",
            selected_output_types=[output_type],
        )
        session.add(transformation)
        session.flush()
        artifact_run = ArtifactRun(
            transformation_run_id=transformation.id,
            output_type=output_type,
            status="pending",
        )
        session.add(artifact_run)
        session.flush()
        job = enqueue_artifact_job(session, artifact_run, source_version)
        result = (job.id, artifact_run.id, source_version.id)
        session.commit()
        return result


def _claim_in_thread(
    factory: sessionmaker[Session], barrier: Barrier, worker_id: str
) -> int | None:
    with factory() as session:
        barrier.wait()
        claim = claim_next_job(session, MODEL_IO, worker_id)
        return claim.job_id if claim is not None else None


def test_database_claim_wins_once_for_separate_sqlite_sessions(
    auth_database: tuple[Any, Engine, sessionmaker[Session]],
) -> None:
    _client, _engine, factory = auth_database
    job_id, _artifact_run_id, _source_version_id = _queued_job(factory)
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_claim_in_thread, factory, barrier, "worker-a")
        second = pool.submit(_claim_in_thread, factory, barrier, "worker-b")
        claims = [first.result(), second.result()]
    assert claims.count(job_id) == 1
    assert claims.count(None) == 1
    with factory() as session:
        job = session.get(Job, job_id)
        attempts = list(session.scalars(select(JobAttempt).where(JobAttempt.job_id == job_id)))
        assert job is not None and job.status == "running"
        assert len(attempts) == 1
        assert attempts[0].attempt_number == 1
        assert attempts[0].status == "running"


def test_active_job_uniqueness_is_database_enforced(
    auth_database: tuple[Any, Engine, sessionmaker[Session]],
) -> None:
    _client, _engine, factory = auth_database
    _job_id, artifact_run_id, source_version_id = _queued_job(factory)
    with factory() as session:
        artifact_run = session.get(ArtifactRun, artifact_run_id)
        source_version = session.get(SourceVersion, source_version_id)
        assert artifact_run is not None and source_version is not None
        with pytest.raises(IntegrityError):
            enqueue_artifact_job(session, artifact_run, source_version)
            session.commit()
        session.rollback()


def test_dependency_waits_for_success_and_rejects_cycles(
    auth_database: tuple[Any, Engine, sessionmaker[Session]],
) -> None:
    _client, _engine, factory = auth_database
    first_id, first_run_id, source_id = _queued_job(factory, output_type="advisory")
    second_id, second_run_id, _ = _queued_job(factory, output_type="linkedin_post")
    with factory() as session:
        add_job_dependency(session, second_id, first_id)
        with pytest.raises(ValueError, match="cycle"):
            add_job_dependency(session, first_id, second_id)
        session.commit()

    with factory() as session:
        first_claim = claim_next_job(session, MODEL_IO, "first-worker")
        assert first_claim is not None and first_claim.job_id == first_id
        assert claim_next_job(session, MODEL_IO, "second-worker") is None

    with factory() as session:
        first = session.get(Job, first_id)
        first_run = session.get(ArtifactRun, first_run_id)
        attempt = session.scalar(select(JobAttempt).where(JobAttempt.job_id == first_id))
        assert first is not None and first_run is not None and attempt is not None
        now = utc_now()
        first.status = "succeeded"
        first.worker_id = None
        first.lease_expires_at = None
        first.terminal_at = now
        attempt.status = "succeeded"
        attempt.finished_at = now
        first_run.status = "succeeded"
        session.commit()

    provider = FakeProvider()
    assert asyncio.run(process_one_job(factory, provider, "worker-one")) is True
    assert len(provider.requests) == 1
    assert asyncio.run(process_one_job(factory, provider, "worker-two")) is False

    with factory() as session:
        first = session.get(Job, first_id)
        second = session.get(Job, second_id)
        assert first is not None and first.status == "succeeded"
        assert second is not None and second.status == "succeeded"
        first_run = session.get(ArtifactRun, first_run_id)
        assert first_run is not None and first_run.status == "succeeded"
        second_run = session.get(ArtifactRun, second_run_id)
        assert second_run is not None and second_run.status == "succeeded"
        first_attempt = session.scalar(select(JobAttempt).where(JobAttempt.job_id == first_id))
        assert first_attempt is not None and first_attempt.status == "succeeded"
        assert source_id > 0


def test_failed_dependency_fails_dependents_without_running_them(
    auth_database: tuple[Any, Engine, sessionmaker[Session]],
) -> None:
    _client, _engine, factory = auth_database
    parent_id, _parent_run_id, _source_id = _queued_job(factory, output_type="advisory")
    child_id, child_run_id, _ = _queued_job(factory, output_type="linkedin_post")
    with factory() as session:
        add_job_dependency(session, child_id, parent_id)
        session.commit()

    assert asyncio.run(process_one_job(factory, FakeProvider(fail=True), "worker")) is True
    assert asyncio.run(process_one_job(factory, FakeProvider(), "worker")) is False
    with factory() as session:
        child = session.get(Job, child_id)
        child_run = session.get(ArtifactRun, child_run_id)
        child_attempt = session.scalar(select(JobAttempt).where(JobAttempt.job_id == child_id))
        assert child is not None and child.status == "failed"
        assert child.failure_code == "dependency_failed"
        assert child_run is not None and child_run.status == "failed"
        assert child_attempt is None


def test_stale_lease_fails_job_attempt_and_artifact_run(
    auth_database: tuple[Any, Engine, sessionmaker[Session]],
) -> None:
    _client, _engine, factory = auth_database
    job_id, artifact_run_id, _source_id = _queued_job(factory)
    with factory() as session:
        claim = claim_next_job(session, MODEL_IO, "abandoned-worker", lease_seconds=1)
        assert claim is not None and claim.job_id == job_id
    with factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        job.lease_expires_at = utc_now() - timedelta(seconds=1)
        session.commit()

    with factory() as session:
        assert claim_next_job(session, MODEL_IO, "recovery-worker") is None
    with factory() as session:
        job = session.get(Job, job_id)
        attempt = session.scalar(select(JobAttempt).where(JobAttempt.job_id == job_id))
        artifact_run = session.get(ArtifactRun, artifact_run_id)
        versions = list(
            session.scalars(
                select(ArtifactVersion).where(ArtifactVersion.artifact_run_id == artifact_run_id)
            )
        )
        assert job is not None and job.status == "failed"
        assert job.failure_code == "worker_lease_expired"
        assert attempt is not None and attempt.status == "failed"
        assert attempt.failure_code == "worker_lease_expired"
        assert artifact_run is not None and artifact_run.status == "failed"
        assert versions == []


def test_queued_job_survives_request_session_and_uses_source_snapshot(
    auth_database: tuple[Any, Engine, sessionmaker[Session]],
) -> None:
    _client, _engine, factory = auth_database
    job_id, artifact_run_id, source_version_id = _queued_job(factory, "Exact source V1")
    with factory() as session:
        source_version = session.get(SourceVersion, source_version_id)
        assert source_version is not None
        source = session.get(Source, source_version.source_id)
        assert source is not None
        v2 = create_source_version(
            session,
            source,
            "Different source V2 created after the job was queued.",
            parent_source_version_id=source_version.id,
        )
        session.commit()
        v2_id = v2.id
    provider = FakeProvider()

    assert asyncio.run(process_one_job(factory, provider, "fresh-worker")) is True
    assert provider.requests[0].source_text == "Exact source V1"
    with factory() as session:
        job = session.get(Job, job_id)
        version = session.scalar(
            select(ArtifactVersion).where(ArtifactVersion.artifact_run_id == artifact_run_id)
        )
        assert job is not None and job.status == "succeeded"
        assert job.context_manifest_id is not None
        assert version is not None and version.source_version_id == source_version_id
        assert version.source_version_id != v2_id
        assert version.context_manifest_id == job.context_manifest_id
        assert version.content == "A generated artifact."
        manifest = session.get(ContextManifest, job.context_manifest_id)
        assert manifest is not None
        assert manifest.source_version_id == source_version_id
        assert manifest.route == "R0_FULL_CONTEXT"
        assert manifest.state == "ready"
        assert manifest.estimated_context_units <= manifest.context_budget_units
        manifest.route = "R1_CHANGED_AFTER_QUEUE"
        with pytest.raises(ValueError, match="immutable"):
            session.flush()
        session.rollback()


def test_unconfigured_worker_fails_safely_without_an_artifact_version(
    auth_database: tuple[Any, Engine, sessionmaker[Session]],
) -> None:
    _client, _engine, factory = auth_database
    job_id, artifact_run_id, _source_version_id = _queued_job(factory)

    assert asyncio.run(process_one_job(factory, None, "worker")) is True
    with factory() as session:
        job = session.get(Job, job_id)
        attempt = session.scalar(select(JobAttempt).where(JobAttempt.job_id == job_id))
        versions = list(
            session.scalars(
                select(ArtifactVersion).where(ArtifactVersion.artifact_run_id == artifact_run_id)
            )
        )
        assert job is not None and job.status == "failed"
        assert job.failure_code == "generation_not_configured"
        assert attempt is not None and attempt.failure_code == "generation_not_configured"
        assert versions == []


def test_over_budget_context_is_recorded_and_generation_is_not_silently_truncated(
    auth_database: tuple[Any, Engine, sessionmaker[Session]],
) -> None:
    _client, _engine, factory = auth_database
    job_id, artifact_run_id, _source_version_id = _queued_job(factory, "x" * 20_000)
    provider = FakeProvider()

    assert asyncio.run(process_one_job(factory, provider, "bounded-worker")) is True
    assert provider.requests == []
    with factory() as session:
        job = session.get(Job, job_id)
        manifest = session.get(ContextManifest, job.context_manifest_id if job else None)
        versions = list(
            session.scalars(
                select(ArtifactVersion).where(ArtifactVersion.artifact_run_id == artifact_run_id)
            )
        )
        assert job is not None and job.status == "failed"
        assert job.failure_code == "context_requires_review"
        assert manifest is not None and manifest.state == "needs_review"
        assert "context_over_budget_no_admitted_r1_profile" in manifest.warnings
        assert manifest.estimated_context_units > manifest.context_budget_units
        assert versions == []


def test_partial_source_coverage_remains_visible_in_r0_manifest(
    auth_database: tuple[Any, Engine, sessionmaker[Session]],
) -> None:
    _client, _engine, factory = auth_database
    with factory() as session:
        owner = User(username="partial-context-owner", password_hash="!test!")
        session.add(owner)
        session.flush()
        source_write = create_source_pack_version(
            session,
            owner.id,
            "Partially extracted source remains usable under compatibility policy.",
            asset_input=SourceAssetInput(extraction_coverage="partial"),
        )
        transformation = TransformationRun(
            owner_id=owner.id,
            source_version_id=source_write.source_version.id,
            supporting_context="",
            audience="Readers",
            tone="Clear",
            language="English",
            detail_level="standard",
            objective="Inform",
            style="Plain",
            selected_output_types=["advisory"],
        )
        session.add(transformation)
        session.flush()
        artifact_run = ArtifactRun(
            transformation_run_id=transformation.id,
            output_type="advisory",
            status="pending",
        )
        session.add(artifact_run)
        session.flush()
        job = enqueue_artifact_job(session, artifact_run, source_write.source_version)
        session.commit()
        manifest = session.get(ContextManifest, job.context_manifest_id)
        assert manifest is not None
        assert manifest.state == "ready"
        assert manifest.extraction_coverage == "partial"
        assert any(warning.startswith("partial_extraction:") for warning in manifest.warnings)
