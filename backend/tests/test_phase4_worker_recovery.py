import asyncio
from typing import TypeVar, cast

from auth_support import login
from fastapi.testclient import TestClient
from generation_support import run_generation
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.evidence import EvidenceAnalysis
from app.api.generation import get_generation_provider
from app.generation import GenerationRequest, GenerationResult, StructuredGenerationResult
from app.job_worker import run_worker
from app.main import app

T = TypeVar("T", bound=BaseModel)


class FailFirstClaimScanProvider:
    supports_phase4_automatic_claim_scan = True

    def __init__(self) -> None:
        self.scan_attempts = 0

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(text="A community advisory.", provider="fixture", model="test")

    async def generate_structured[TModel: BaseModel](
        self, request: GenerationRequest, response_model: type[TModel]
    ) -> StructuredGenerationResult[TModel]:
        if response_model is not EvidenceAnalysis:
            raise AssertionError(f"Unexpected structured model: {response_model.__name__}")
        self.scan_attempts += 1
        if self.scan_attempts == 1:
            raise RuntimeError("temporary scan failure")
        value: BaseModel = EvidenceAnalysis(proposals=[], analysis_complete=True)
        return StructuredGenerationResult(
            value=cast(TModel, value), provider="fixture", model="test"
        )


def test_worker_restart_resumes_failed_durable_claim_scan(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client, "scan-recovery-owner")
    provider = FailFirstClaimScanProvider()
    app.dependency_overrides[get_generation_provider] = lambda: provider
    saved = client.post(
        "/api/transformations",
        json={
            "source_text": "The library opens at nine in the morning.",
            "output_types": ["advisory"],
            "audience": "visitors",
            "tone": "clear",
            "language": "English",
            "detail_level": "brief",
            "objective": "inform",
            "style": "plain language",
        },
    )
    assert saved.status_code == 200
    transformation_id = saved.json()["transformation_run_id"]
    generated = run_generation(client, transformation_id, factory, provider)
    assert generated.json()["status"] == "succeeded"
    version_id = generated.json()["artifacts"][0]["artifact_version"]["id"]

    failed = client.get(f"/api/artifact-versions/{version_id}/claim-scan").json()
    assert failed["status"] == "failed"
    assert failed["total_batches"] == 1
    assert failed["completed_batches"] == 0
    assert failed["failed_batches"] == 1

    asyncio.run(run_worker(factory, provider, "phase4-recovery-test", once=True))
    recovered = client.get(f"/api/artifact-versions/{version_id}/claim-scan").json()
    assert recovered["status"] == "complete"
    assert recovered["total_batches"] == recovered["completed_batches"] == 1
    assert recovered["failed_batches"] == 0
    assert recovered["batches"][0]["attempt_count"] == 2
    assert provider.scan_attempts == 2
