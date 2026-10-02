import asyncio
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.generation import (
    GenerationProviderError,
    GenerationRequest,
    GenerationResult,
)
from app.job_worker import process_one_job
from app.models import ArtifactRun, TransformationRun


class DeterministicGenerationProvider:
    def __init__(
        self,
        result: GenerationResult,
        error: GenerationProviderError | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.requests: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result


class CompletedResponse:
    """Test convenience for assertions that need the state after a separate worker pass."""

    status_code = 200

    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


def _installed_provider(provider: Any | None) -> Any:
    if provider is not None:
        return provider
    from app.api.generation import get_generation_provider
    from app.main import app

    override = app.dependency_overrides.get(get_generation_provider)
    if override is None:
        raise AssertionError("Install a fake generation provider before draining jobs")
    return override()


def drain_jobs(factory: sessionmaker[Session], provider: Any | None = None) -> None:
    installed = _installed_provider(provider)
    for _ in range(100):
        processed = asyncio.run(process_one_job(factory, installed, "test-worker"))
        if not processed:
            return
    raise AssertionError("Worker test helper exceeded its bounded job count")


def run_generation(
    client: TestClient,
    transformation_id: int,
    factory: sessionmaker[Session],
    provider: Any | None = None,
) -> CompletedResponse:
    queued = client.post(f"/api/transformations/{transformation_id}/generate")
    assert queued.status_code == 202
    queued_body = queued.json()
    drain_jobs(factory, provider)
    detail = client.get(f"/api/transformations/{transformation_id}")
    assert detail.status_code == 200
    runs_by_id = {item["artifact_run_id"]: item for item in detail.json()["artifact_runs"]}
    artifacts: list[dict[str, Any]] = []
    for queued_artifact in queued_body["artifacts"]:
        run = runs_by_id[queued_artifact["artifact_run_id"]]
        artifacts.append(
            {
                "artifact_run_id": run["artifact_run_id"],
                "output_type": run["output_type"],
                "status": run["status"],
                "artifact_version": run["versions"][-1] if run["versions"] else None,
            }
        )
    statuses = {item["status"] for item in artifacts}
    batch_status = (
        "running"
        if statuses.intersection({"pending", "running"})
        else "partial_failure"
        if "failed" in statuses
        else "succeeded"
    )
    return CompletedResponse({"status": batch_status, "artifacts": artifacts})


def run_artifact_action(
    client: TestClient,
    artifact_run_id: int,
    action: str,
    factory: sessionmaker[Session],
    provider: Any | None = None,
) -> CompletedResponse:
    if action not in {"retry", "regenerate"}:
        raise ValueError("Unsupported test artifact action")
    queued = client.post(f"/api/artifact-runs/{artifact_run_id}/{action}")
    assert queued.status_code == 202
    drain_jobs(factory, provider)
    with factory() as session:
        transformation_id = session.scalar(
            select(TransformationRun.id)
            .join(ArtifactRun, ArtifactRun.transformation_run_id == TransformationRun.id)
            .where(ArtifactRun.id == artifact_run_id)
        )
    assert transformation_id is not None
    detail = client.get(f"/api/transformations/{transformation_id}")
    assert detail.status_code == 200
    run = next(
        item
        for item in detail.json()["artifact_runs"]
        if item["artifact_run_id"] == artifact_run_id
    )
    latest_version = run["versions"][-1] if run["versions"] else None
    return CompletedResponse(
        {
            "artifact_run_id": artifact_run_id,
            "output_type": run["output_type"],
            "status": run["status"],
            "artifact_version": latest_version,
        }
    )
