from typing import Any, cast

import pytest
from auth_support import login
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.generation import get_generation_provider
from app.generation import GenerationProviderError, GenerationRequest, GenerationResult
from app.models import ArtifactRun, ArtifactVersion
from app.settings import Settings


class FixedProvider:
    def __init__(self, text: str = "A concise summary.", fail: bool = False) -> None:
        self.text = text
        self.fail = fail
        self.requests: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.requests.append(request)
        if self.fail:
            raise GenerationProviderError()
        return GenerationResult(text=self.text, provider="test", model="deterministic")


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
        "app.api.generation.get_settings", lambda: cast(Any, Settings)(_env_file=None)
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

    response = client.post(f"/api/transformations/{run_id}/generate")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["artifact_version"]["content"] == "A concise summary."
    assert body["artifact_version"]["provider"] == "test"
    assert body["artifact_version"]["model"] == "deterministic"
    assert body["artifact_version"]["prompt_version"] == "1"
    assert len(body["artifact_version"]["prompt_hash"]) == 64
    assert provider.requests[0].source_text == "A fictional source fact for acceptance testing."
    assert provider.requests[0].supporting_context == "Fictional context kept separate."
    assert provider.requests[0].source_text != provider.requests[0].supporting_context

    duplicate = client.post(f"/api/transformations/{run_id}/generate")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "artifact_run_exists"
    runs = read_artifact_runs(factory)
    versions = read_artifact_versions(factory)
    assert len(runs) == 1
    assert runs[0].status == "succeeded"
    assert len(versions) == 1
    assert versions[0].source_version_id == body["artifact_version"]["source_version_id"]


def test_missing_openai_configuration_fails_run_without_fake_version(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    install_provider(None)
    run_id = save_summary_request(client)

    response = client.post(f"/api/transformations/{run_id}/generate")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "generation_not_configured"
    assert len(read_artifact_runs(factory)) == 1
    assert read_artifact_runs(factory)[0].status == "failed"
    assert read_artifact_versions(factory) == []


def test_provider_failure_marks_run_failed_without_version(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    install_provider(FixedProvider(fail=True))
    run_id = save_summary_request(client)

    response = client.post(f"/api/transformations/{run_id}/generate")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "generation_failed"
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


def test_unselected_output_cannot_be_generated(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, _factory = auth_database
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

    generated = client.post(f"/api/transformations/{run_id}/generate")

    assert generated.status_code == 409
    assert generated.json()["error"]["code"] == "output_not_selected"
