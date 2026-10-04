import asyncio
import json
from typing import Any, cast

import pytest
from auth_support import login
from fastapi.testclient import TestClient
from generation_support import run_artifact_action, run_generation
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.generation import get_generation_provider
from app.artifact_contracts import (
    InfographicCalloutBlock,
    InfographicSpec,
    VideoPackageSpec,
    VideoSceneSpec,
)
from app.artifact_generators import ARTIFACT_INSTRUCTIONS, OUTPUT_TOKEN_BUDGETS
from app.domain.transformation import OutputType
from app.generation import (
    GenerationProviderError,
    GenerationRequest,
    GenerationResult,
    StructuredGenerationResult,
)
from app.job_worker import process_one_job
from app.models import (
    ArtifactRun,
    ArtifactVersion,
    Job,
    JobAttempt,
    MediaRender,
    MediaTask,
    TransformationRun,
)
from app.presentation import PresentationSpec, SlideSpec
from app.settings import Settings


class FixedProvider:
    def __init__(
        self,
        text: str = "A concise summary.",
        fail: bool = False,
        fail_on_call: int | None = None,
    ) -> None:
        self.text = text
        self.fail = fail
        self.fail_on_call = fail_on_call
        self.requests: list[GenerationRequest] = []

    def _record(self, request: GenerationRequest) -> None:
        self.requests.append(request)
        if self.fail or len(self.requests) == self.fail_on_call:
            raise GenerationProviderError()

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self._record(request)
        return GenerationResult(text=self.text, provider="test", model="deterministic")

    async def generate_structured[T: BaseModel](
        self, request: GenerationRequest, response_model: type[T]
    ) -> StructuredGenerationResult[T]:
        self._record(request)
        if response_model is PresentationSpec:
            value: BaseModel = PresentationSpec(
                title="Fictional briefing",
                slides=[
                    PresentationSlideData.make("Situation"),
                    PresentationSlideData.make("Response"),
                ],
            )
        elif response_model is InfographicSpec:
            value = InfographicSpec(
                title="Fictional infographic",
                blocks=[
                    InfographicCalloutBlock(
                        label="Opening", value="Saturday", explanation="Fictional source."
                    )
                ],
                visual_direction="Use a simple calendar illustration.",
            )
        elif response_model is VideoPackageSpec:
            value = VideoPackageSpec(
                title="Fictional video",
                concept="Show the community center opening.",
                scenes=[
                    VideoSceneSpec(
                        title="Opening day",
                        narration="The center opened on Saturday.",
                        on_screen_text=["Community center"],
                        visual_direction="Show the building entrance.",
                    )
                ],
            )
        else:
            raise AssertionError(f"Unexpected structured family: {response_model.__name__}")
        parsed = response_model.model_validate(value.model_dump())
        return StructuredGenerationResult(value=parsed, provider="test", model="deterministic")


class PresentationSlideData:
    @staticmethod
    def make(title: str) -> SlideSpec:
        return SlideSpec(
            title=title,
            key_message=f"{title} stays within the fictional source.",
            bullets=["Fictional source detail."],
            visual_recommendation="Simple text card.",
            speaker_notes=f"Speaker notes for {title}.",
        )


def save_summary_request(client: TestClient) -> int:
    response = client.post(
        "/api/transformations",
        json={
            "source_text": "A fictional source fact for acceptance testing.",
            "supporting_context": "Fictional context kept separate.",
            "output_types": ["executive_summary"],
            "audience": "reviewers",
            "tone": "clear",
            "language": "English",
            "detail_level": "brief",
            "objective": "inform",
            "style": "plain language",
        },
    )
    assert response.status_code == 200
    return response.json()["transformation_run_id"]


def install_provider(provider: FixedProvider | None) -> None:
    from app.main import app

    app.dependency_overrides[get_generation_provider] = lambda: provider


def test_live_provider_is_not_constructed_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "app.provider_factory.get_settings", lambda: cast(Any, Settings)(_env_file=None)
    )

    assert get_generation_provider() is None


def read_artifact_runs(factory: sessionmaker[Session]) -> list[ArtifactRun]:
    with factory() as session:
        return list(session.scalars(select(ArtifactRun)).all())


def read_artifact_versions(factory: sessionmaker[Session]) -> list[ArtifactVersion]:
    with factory() as session:
        return list(session.scalars(select(ArtifactVersion)).all())


def test_generate_persists_version_provenance_and_prevents_duplicates(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    provider = FixedProvider()
    install_provider(provider)
    run_id = save_summary_request(client)

    response = run_generation(client, run_id, factory, provider)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    artifact = body["artifacts"][0]
    assert artifact["output_type"] == "executive_summary"
    assert artifact["artifact_version"]["content"] == "A concise summary."
    assert artifact["artifact_version"]["provider"] == "test"
    assert artifact["artifact_version"]["model"] == "deterministic"
    assert artifact["artifact_version"]["prompt_version"] == "1"
    assert len(artifact["artifact_version"]["prompt_hash"]) == 64
    assert provider.requests[0].source_text == "A fictional source fact for acceptance testing."
    assert provider.requests[0].supporting_context == "Fictional context kept separate."
    assert provider.requests[0].source_text != provider.requests[0].supporting_context

    duplicate = client.post(f"/api/transformations/{run_id}/generate")
    assert duplicate.status_code == 202
    assert len(provider.requests) == 1
    runs = read_artifact_runs(factory)
    versions = read_artifact_versions(factory)
    assert len(runs) == 1
    assert runs[0].status == "succeeded"
    assert len(versions) == 1
    assert versions[0].source_version_id == artifact["artifact_version"]["source_version_id"]


def test_generate_is_durable_and_returns_before_worker_execution(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    provider = FixedProvider()
    run_id = save_summary_request(client)

    queued = client.post(f"/api/transformations/{run_id}/generate")
    assert queued.status_code == 202
    body = queued.json()
    assert body["status"] == "running"
    assert body["artifacts"][0]["status"] == "pending"
    assert body["artifacts"][0]["artifact_version"] is None
    assert provider.requests == []
    with factory() as session:
        jobs = list(session.scalars(select(Job)))
        assert len(jobs) == 1 and jobs[0].status == "queued"

    duplicate = client.post(f"/api/transformations/{run_id}/generate")
    assert duplicate.status_code == 202
    assert len(provider.requests) == 0
    with factory() as session:
        assert len(list(session.scalars(select(Job)))) == 1

    from generation_support import drain_jobs

    drain_jobs(factory, provider)
    detail = client.get(f"/api/transformations/{run_id}").json()
    assert detail["artifact_runs"][0]["status"] == "succeeded"
    assert len(detail["artifact_runs"][0]["versions"]) == 1
    assert len(provider.requests) == 1


def test_infographic_generation_auto_renders_idempotently_and_survives_media_failure(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.job_worker import run_combined_worker
    from app.media_renderer import MediaRenderError
    from app.media_workflows import ensure_default_infographic_render

    client, _engine, factory = auth_database
    login(client)
    provider = FixedProvider()
    install_provider(provider)
    created = client.post(
        "/api/transformations",
        json={
            "source_text": "A fictional municipal launch in 18 wards.",
            "supporting_context": "",
            "output_types": ["infographic"],
            "audience": "Municipal leadership",
            "tone": "Professional",
            "language": "English",
            "detail_level": "brief",
            "objective": "Explain the launch",
            "style": "Plain language",
        },
    )
    assert created.status_code == 200
    transformation_id = created.json()["transformation_run_id"]
    queued = client.post(f"/api/transformations/{transformation_id}/generate")
    assert queued.status_code == 202

    asyncio.run(run_combined_worker(factory, provider, "combined-infographic-test", once=True))

    with factory() as session:
        transformation = session.get(TransformationRun, transformation_id)
        run = session.scalar(select(ArtifactRun))
        version = session.scalar(select(ArtifactVersion))
        assert run is not None
        model_job = session.scalar(select(Job).where(Job.artifact_run_id == run.id))
        render = session.scalar(select(MediaRender))
        assert transformation is not None and transformation.selected_output_types == [
            "infographic"
        ]
        assert run.status == "succeeded" and run.output_type == "infographic"
        assert version is not None and version.artifact_run_id == run.id
        assert InfographicSpec.model_validate_json(version.content).title == "Fictional infographic"
        assert version.provider == "test" and version.model == "deterministic"
        assert model_job is not None and model_job.resource_class == "model_io"
        assert model_job.status == "succeeded"
        assert render is not None and render.artifact_version_id == version.id
        render_id = render.id
        version_id = version.id
        owner_id = transformation.owner_id
        media_jobs = list(
            session.scalars(select(Job).join(MediaTask, MediaTask.id == Job.media_task_id))
        )
        assert len(media_jobs) == 1
        assert media_jobs[0].resource_class == "media_cpu"
        assert media_jobs[0].status == "queued"

    with factory() as session:
        version = session.get(ArtifactVersion, version_id)
        assert version is not None
        repeated = ensure_default_infographic_render(session, owner_id, version)
        session.commit()
        assert repeated.id == render_id
    with factory() as session:
        version = session.get(ArtifactVersion, version_id)
        assert version is not None
        repeated = ensure_default_infographic_render(session, owner_id, version)
        session.commit()
        assert repeated.id == render_id

    from app import media_workflows

    original_renderer = media_workflows.render_infographic
    fail_once = True

    def render_with_one_failure(spec: InfographicSpec) -> tuple[bytes, bytes, int, int]:
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise MediaRenderError("fixture_render_failure")
        return original_renderer(spec)

    monkeypatch.setattr(media_workflows, "render_infographic", render_with_one_failure)
    asyncio.run(run_combined_worker(factory, provider, "combined-infographic-test", once=True))

    with factory() as session:
        run = session.get(ArtifactRun, queued.json()["artifacts"][0]["artifact_run_id"])
        version = session.get(ArtifactVersion, version_id)
        render = session.get(MediaRender, render_id)
        assert run is not None and run.status == "succeeded"
        assert version is not None and InfographicSpec.model_validate_json(version.content)
        assert render is not None and render.status == "failed"
    failed = client.get(f"/api/media-renders/{render_id}").json()
    assert failed["status"] == "failed"
    retried = client.post(f"/api/media-renders/{render_id}/retry-failed")
    assert retried.status_code == 202

    asyncio.run(run_combined_worker(factory, provider, "combined-infographic-test", once=True))

    ready = client.get(f"/api/media-renders/{render_id}").json()
    assert ready["status"] == "ready_for_review"
    assert ready["primary_asset"]["purpose"] == "infographic_png"
    assets = [asset for task in ready["tasks"] for asset in task["assets"]]
    svg = next(asset for asset in assets if asset["purpose"] == "infographic_svg")
    assert client.get(ready["primary_asset"]["download_url"]).status_code == 200
    assert client.get(svg["download_url"]).status_code == 200
    with factory() as session:
        run = session.get(ArtifactRun, queued.json()["artifacts"][0]["artifact_run_id"])
        version = session.get(ArtifactVersion, version_id)
        media_renders = list(session.scalars(select(MediaRender)))
        media_tasks = list(session.scalars(select(MediaTask)))
        media_jobs = list(
            session.scalars(select(Job).join(MediaTask, MediaTask.id == Job.media_task_id))
        )
        assert run is not None and run.status == "succeeded"
        assert version is not None and version.id == version_id
        assert len(media_renders) == len(media_tasks) == len(media_jobs) == 1
        assert media_jobs[0].resource_class == "media_cpu"
        assert media_jobs[0].status == "succeeded"


def test_queued_source_snapshot_and_regeneration_use_v1_then_v2(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    provider = FixedProvider(text="Generated from the queued snapshot.")
    run_id = save_summary_request(client)
    with factory() as session:
        transformation = session.get(TransformationRun, run_id)
        assert transformation is not None
        source_v1_id = transformation.source_version_id

    queued = client.post(f"/api/transformations/{run_id}/generate")
    assert queued.status_code == 202
    artifact_run_id = queued.json()["artifacts"][0]["artifact_run_id"]
    revision = client.post(
        f"/api/transformations/{run_id}/source-versions",
        json={"source_text": "The current source is V2."},
    )
    assert revision.status_code == 200
    source_v2_id = revision.json()["source_version"]["id"]
    with factory() as session:
        first_job = session.scalar(select(Job).where(Job.artifact_run_id == artifact_run_id))
        assert first_job is not None and first_job.source_version_id == source_v1_id

    assert asyncio.run(process_one_job(factory, provider, "snapshot-worker")) is True
    assert provider.requests[0].source_text == "A fictional source fact for acceptance testing."
    with factory() as session:
        first_version = session.scalar(
            select(ArtifactVersion).where(ArtifactVersion.artifact_run_id == artifact_run_id)
        )
        assert first_version is not None and first_version.source_version_id == source_v1_id

    regenerated = client.post(f"/api/artifact-runs/{artifact_run_id}/regenerate")
    assert regenerated.status_code == 202
    with factory() as session:
        jobs = list(
            session.scalars(
                select(Job).where(Job.artifact_run_id == artifact_run_id).order_by(Job.id)
            )
        )
        assert len(jobs) == 2
        assert jobs[1].source_version_id == source_v2_id
    assert asyncio.run(process_one_job(factory, provider, "snapshot-worker")) is True
    assert provider.requests[1].source_text == "The current source is V2."
    with factory() as session:
        versions = list(
            session.scalars(
                select(ArtifactVersion)
                .where(ArtifactVersion.artifact_run_id == artifact_run_id)
                .order_by(ArtifactVersion.version_number)
            )
        )
        assert [item.source_version_id for item in versions] == [source_v1_id, source_v2_id]


def test_retry_keeps_failed_job_source_snapshot_after_source_revision(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    failing_provider = FixedProvider(fail=True)
    run_id = save_summary_request(client)
    queued = client.post(f"/api/transformations/{run_id}/generate")
    assert queued.status_code == 202
    artifact_run_id = queued.json()["artifacts"][0]["artifact_run_id"]
    with factory() as session:
        first_job = session.scalar(select(Job).where(Job.artifact_run_id == artifact_run_id))
        assert first_job is not None
        first_job_id = first_job.id
        source_v1_id = first_job.source_version_id
    assert asyncio.run(process_one_job(factory, failing_provider, "failed-worker")) is True

    revision = client.post(
        f"/api/transformations/{run_id}/source-versions",
        json={"source_text": "The current source is V2."},
    )
    assert revision.status_code == 200
    provider = FixedProvider(text="Retried from V1.")
    retry = client.post(f"/api/artifact-runs/{artifact_run_id}/retry")
    assert retry.status_code == 202
    with factory() as session:
        retried_job = session.get(Job, first_job_id)
        assert retried_job is not None
        assert retried_job.status == "queued"
        assert retried_job.source_version_id == source_v1_id

    assert asyncio.run(process_one_job(factory, provider, "retry-worker")) is True
    assert provider.requests[0].source_text == "A fictional source fact for acceptance testing."
    with factory() as session:
        version = session.scalar(
            select(ArtifactVersion).where(ArtifactVersion.artifact_run_id == artifact_run_id)
        )
        attempts = list(
            session.scalars(
                select(JobAttempt)
                .where(JobAttempt.job_id == first_job_id)
                .order_by(JobAttempt.attempt_number)
            )
        )
        assert version is not None and version.source_version_id == source_v1_id
        assert [item.status for item in attempts] == ["failed", "succeeded"]


def test_missing_openai_configuration_fails_run_without_fake_version(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    install_provider(None)
    run_id = save_summary_request(client)

    response = run_generation(client, run_id, factory)

    assert response.status_code == 200
    assert response.json()["status"] == "partial_failure"
    assert len(read_artifact_runs(factory)) == 1
    assert read_artifact_runs(factory)[0].status == "failed"
    assert read_artifact_versions(factory) == []


def test_x_post_budget_contract_and_oversize_fails_without_persisting_version(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    assert OutputType.X_POST in ARTIFACT_INSTRUCTIONS
    assert OUTPUT_TOKEN_BUDGETS[OutputType.X_POST] == 220
    provider = FixedProvider(text="😀" * 281)
    install_provider(provider)
    run_id = client.post(
        "/api/transformations",
        json={
            "source_text": "A sourced announcement.",
            "output_types": ["x_post"],
            "audience": "public",
            "tone": "clear",
            "language": "English",
            "detail_level": "brief",
            "objective": "inform",
            "style": "plain",
        },
    ).json()["transformation_run_id"]
    response = run_generation(client, run_id, factory, provider)
    assert response.status_code == 200
    assert response.json()["status"] == "partial_failure"
    assert response.json()["artifacts"][0]["status"] == "failed"
    assert read_artifact_versions(factory) == []


def test_x_post_within_unicode_codepoint_bound_is_persisted(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    provider = FixedProvider(text="😀" * 280)
    install_provider(provider)
    run_id = client.post(
        "/api/transformations",
        json={
            "source_text": "A sourced announcement.",
            "output_types": ["x_post"],
            "audience": "public",
            "tone": "clear",
            "language": "English",
            "detail_level": "brief",
            "objective": "inform",
            "style": "plain",
        },
    ).json()["transformation_run_id"]
    response = run_generation(client, run_id, factory, provider)
    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
    assert len(response.json()["artifacts"][0]["artifact_version"]["content"]) == 280
    assert len(read_artifact_versions(factory)) == 1


def test_x_partial_failure_preserves_sibling_and_retries_x_only(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    failing_provider = FixedProvider(text="A grounded post.", fail_on_call=2)
    install_provider(failing_provider)
    run_id = client.post(
        "/api/transformations",
        json={
            "source_text": "A sourced announcement.",
            "output_types": ["executive_summary", "x_post"],
            "audience": "public",
            "tone": "clear",
            "language": "English",
            "detail_level": "brief",
            "objective": "inform",
            "style": "plain",
        },
    ).json()["transformation_run_id"]

    first = run_generation(client, run_id, factory, failing_provider)
    assert first.json()["status"] == "partial_failure"
    assert [item["status"] for item in first.json()["artifacts"]] == ["succeeded", "failed"]
    runs = read_artifact_runs(factory)
    summary_run, x_run = runs
    assert len(read_artifact_versions(factory)) == 1

    retry_provider = FixedProvider(text="A grounded post.")
    install_provider(retry_provider)
    retried = run_artifact_action(client, x_run.id, "retry", factory, retry_provider)
    assert retried.json()["status"] == "succeeded"
    assert retried.json()["output_type"] == "x_post"
    assert len(retry_provider.requests) == 1
    assert len(read_artifact_versions(factory)) == 2
    assert summary_run.status == "succeeded"


def test_provider_failure_marks_run_failed_without_version(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    install_provider(FixedProvider(fail=True))
    run_id = save_summary_request(client)

    response = run_generation(client, run_id, factory)

    assert response.status_code == 200
    assert response.json()["status"] == "partial_failure"
    assert response.json()["artifacts"][0]["status"] == "failed"
    assert read_artifact_runs(factory)[0].status == "failed"
    assert read_artifact_versions(factory) == []


def test_generation_is_owner_scoped(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client, "owner-one")
    install_provider(FixedProvider())
    run_id = save_summary_request(client)

    login(client, "owner-two")
    response = client.post(f"/api/transformations/{run_id}/generate")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert read_artifact_runs(factory) == []


def test_only_selected_outputs_are_generated(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    install_provider(FixedProvider())
    response = client.post(
        "/api/transformations",
        json={
            "source_text": "A fictional source.",
            "output_types": ["advisory"],
            "audience": "reviewers",
            "tone": "clear",
            "language": "English",
            "detail_level": "brief",
            "objective": "inform",
            "style": "plain language",
        },
    )
    run_id = response.json()["transformation_run_id"]

    generated = run_generation(client, run_id, factory)

    assert generated.status_code == 200
    assert [item["output_type"] for item in generated.json()["artifacts"]] == ["advisory"]


def test_all_seven_families_create_independent_jobs_and_versioned_artifacts(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    provider = FixedProvider()
    install_provider(provider)
    selected = [output_type.value for output_type in OutputType]
    response = client.post(
        "/api/transformations",
        json={
            "source_text": "The fictional clinic opened on Monday.",
            "output_types": selected,
            "audience": "community members",
            "tone": "clear",
            "language": "English",
            "detail_level": "standard",
            "objective": "inform",
            "style": "plain language",
        },
    )
    assert response.status_code == 200

    generated = run_generation(client, response.json()["transformation_run_id"], factory, provider)
    assert generated.status_code == 200
    artifacts = generated.json()["artifacts"]
    assert [item["output_type"] for item in artifacts] == selected
    assert all(item["status"] == "succeeded" for item in artifacts)
    assert len(provider.requests) == 7

    with factory() as session:
        runs = list(session.scalars(select(ArtifactRun)))
        jobs = list(session.scalars(select(Job)))
        versions = list(session.scalars(select(ArtifactVersion)))
        assert len(runs) == 7
        artifact_jobs = [job for job in jobs if job.job_type == "artifact_generation"]
        media_jobs = [job for job in jobs if job.job_type == "media_task"]
        assert len(jobs) == 8
        assert len(artifact_jobs) == 7
        assert len(media_jobs) == 1
        assert media_jobs[0].resource_class == "media_cpu"
        assert media_jobs[0].status == "queued"
        assert len(versions) == 7
        assert {version.artifact_schema_version for version in versions} == {"1"}
        assert all(job.context_manifest_id is not None for job in artifact_jobs)
        assert all(version.context_manifest_id is not None for version in versions)
        assert {version.prompt_version for version in versions} == {
            "1",
            "2",
        }
        assert all(version.prompt_hash and len(version.prompt_hash) == 64 for version in versions)


@pytest.mark.parametrize(
    ("failed_output_type", "failed_model"),
    [
        (OutputType.INFOGRAPHIC, InfographicSpec),
        (OutputType.VIDEO_PACKAGE, VideoPackageSpec),
    ],
)
def test_invalid_structured_family_failure_and_retry_leave_successful_siblings_intact(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
    failed_output_type: OutputType,
    failed_model: type[BaseModel],
) -> None:
    client, _engine, factory = auth_database
    login(client)

    class InvalidInfographicOnceProvider(FixedProvider):
        def __init__(self) -> None:
            super().__init__()
            self.invalid = True

        async def generate_structured[T: BaseModel](
            self, request: GenerationRequest, response_model: type[T]
        ) -> StructuredGenerationResult[T]:
            if response_model is failed_model and self.invalid:
                self._record(request)
                raise ValueError("malformed structured response")
            return await super().generate_structured(request, response_model)

    provider = InvalidInfographicOnceProvider()
    install_provider(provider)
    response = client.post(
        "/api/transformations",
        json={
            "source_text": "The fictional clinic opened on Monday.",
            "output_types": [output_type.value for output_type in OutputType],
            "audience": "community members",
            "tone": "clear",
            "language": "English",
            "detail_level": "standard",
            "objective": "inform",
            "style": "plain language",
        },
    )
    run_id = response.json()["transformation_run_id"]
    generated = run_generation(client, run_id, factory, provider)
    artifacts = generated.json()["artifacts"]
    failed = next(item for item in artifacts if item["output_type"] == failed_output_type.value)
    assert generated.json()["status"] == "partial_failure"
    assert sum(item["status"] == "succeeded" for item in artifacts) == 6
    assert failed["status"] == "failed"
    prior_sibling_versions = {
        item["output_type"]: item["artifact_version"]["id"]
        for item in artifacts
        if item["status"] == "succeeded"
    }
    provider.invalid = False
    retried = run_artifact_action(client, failed["artifact_run_id"], "retry", factory, provider)

    assert retried.status_code == 200
    assert retried.json()["status"] == "succeeded"
    assert len(provider.requests) == 8
    detail = client.get(f"/api/transformations/{run_id}").json()
    for run in detail["artifact_runs"]:
        if run["output_type"] == failed_output_type.value:
            assert len(run["versions"]) == 1
            assert run["versions"][0]["artifact_schema_version"] == "1"
        else:
            assert run["versions"][0]["id"] == prior_sibling_versions[run["output_type"]]


def test_four_output_partial_failure_and_targeted_retry_preserve_successful_siblings(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    provider = FixedProvider(fail_on_call=3)
    install_provider(provider)
    response = client.post(
        "/api/transformations",
        json={
            "source_text": "A fictional city opened a community center on Saturday.",
            "supporting_context": "Use a calm, accessible tone.",
            "output_types": [
                "executive_summary",
                "linkedin_post",
                "advisory",
                "presentation",
            ],
            "audience": "community members",
            "tone": "measured",
            "language": "English",
            "detail_level": "standard",
            "objective": "inform",
            "style": "plain language",
        },
    )
    run_id = response.json()["transformation_run_id"]

    generated = run_generation(client, run_id, factory, provider)

    assert generated.status_code == 200
    body = generated.json()
    assert body["status"] == "partial_failure"
    assert len(provider.requests) == 4
    assert all(
        item.source_text == "A fictional city opened a community center on Saturday."
        and item.supporting_context == "Use a calm, accessible tone."
        and item.source_text != item.supporting_context
        for item in provider.requests
    )
    assert [item["status"] for item in body["artifacts"]] == [
        "succeeded",
        "succeeded",
        "failed",
        "succeeded",
    ]
    presentation = next(item for item in body["artifacts"] if item["output_type"] == "presentation")
    parsed_presentation = PresentationSpec.model_validate(
        json.loads(presentation["artifact_version"]["content"])
    )
    assert parsed_presentation.slides[0].speaker_notes == "Speaker notes for Situation."

    failed = next(item for item in body["artifacts"] if item["status"] == "failed")
    retried = run_artifact_action(client, failed["artifact_run_id"], "retry", factory, provider)

    assert retried.status_code == 200
    assert retried.json()["status"] == "succeeded"
    assert len(provider.requests) == 5
    assert len(read_artifact_runs(factory)) == 4
    assert len(read_artifact_versions(factory)) == 4
    assert all(item.status == "succeeded" for item in read_artifact_runs(factory))


def test_retry_rejects_non_failed_artifact_run(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    install_provider(FixedProvider())
    run_id = save_summary_request(client)
    generated = run_generation(client, run_id, factory).json()
    artifact_run_id = generated["artifacts"][0]["artifact_run_id"]

    retry = client.post(f"/api/artifact-runs/{artifact_run_id}/retry")

    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "artifact_not_failed"


def test_presentation_analysis_failure_does_not_roll_back_text_siblings(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    provider = FixedProvider(fail_on_call=3)
    install_provider(provider)
    response = client.post(
        "/api/transformations",
        json={
            "source_text": "A fictional clinic opened on Monday.",
            "output_types": ["executive_summary", "linkedin_post", "presentation"],
            "audience": "local residents",
            "tone": "clear",
            "language": "English",
            "detail_level": "standard",
            "objective": "inform",
            "style": "plain language",
        },
    )
    run_id = response.json()["transformation_run_id"]

    generated = run_generation(client, run_id, factory, provider)

    assert generated.status_code == 200
    artifacts = generated.json()["artifacts"]
    assert [item["status"] for item in artifacts] == ["succeeded", "succeeded", "failed"]
    assert len(read_artifact_runs(factory)) == 3
    assert len(read_artifact_versions(factory)) == 2
