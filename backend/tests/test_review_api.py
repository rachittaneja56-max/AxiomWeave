import json
from typing import TypeVar

import pytest
from auth_support import login
from fastapi.testclient import TestClient
from generation_support import run_artifact_action, run_generation
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.generation import get_generation_provider
from app.artifact_contracts import (
    InfographicCalloutBlock,
    InfographicSpec,
    VideoPackageSpec,
    VideoSceneSpec,
)
from app.generation import (
    GenerationRequest,
    GenerationResult,
    StructuredGenerationResult,
)
from app.models import ArtifactVersion
from app.presentation import PresentationSpec, SlideSpec

T = TypeVar("T", bound=BaseModel)


class ReviewTestProvider:
    def __init__(self, texts: list[str] | None = None) -> None:
        self.texts = texts or ["Generated review draft.", "Regenerated review draft."]
        self.text_number = 0

    async def generate(self, _request: GenerationRequest) -> GenerationResult:
        content = self.texts[min(self.text_number, len(self.texts) - 1)]
        self.text_number += 1
        return GenerationResult(text=content, provider="test", model="deterministic")

    async def generate_structured[TModel: BaseModel](
        self, _request: GenerationRequest, response_model: type[TModel]
    ) -> StructuredGenerationResult[TModel]:
        if response_model is PresentationSpec:
            value: BaseModel = PresentationSpec(
                title="Fictional briefing",
                slides=[
                    SlideSpec(
                        title="Opening",
                        key_message="A fictional opening date.",
                        bullets=["Opened on Saturday."],
                        visual_recommendation="Entrance photo.",
                        speaker_notes="Welcome the attendees.",
                    ),
                    SlideSpec(
                        title="Next steps",
                        key_message="Check posted hours.",
                        bullets=["Visit during opening hours."],
                        visual_recommendation="Hours sign.",
                        speaker_notes="Point to the posted schedule.",
                    ),
                ],
            )
        elif response_model is InfographicSpec:
            value = InfographicSpec(
                title="Fictional infographic",
                blocks=[InfographicCalloutBlock(label="Opening", value="Saturday")],
                visual_direction="Use a simple calendar illustration.",
            )
        elif response_model is VideoPackageSpec:
            value = VideoPackageSpec(
                title="Fictional video package",
                concept="Share a short opening update.",
                scenes=[
                    VideoSceneSpec(
                        title="Opening",
                        narration="The center opened on Saturday.",
                        visual_direction="Show the center entrance.",
                    )
                ],
            )
        else:
            raise AssertionError(f"Unexpected structured family: {response_model.__name__}")
        return StructuredGenerationResult(
            value=response_model.model_validate(value.model_dump()),
            provider="test",
            model="deterministic",
        )


def install_provider(provider: ReviewTestProvider) -> None:
    from app.main import app

    app.dependency_overrides[get_generation_provider] = lambda: provider


def save_transformation(client: TestClient, output_types: list[str]) -> int:
    response = client.post(
        "/api/transformations",
        json={
            "source_text": "The fictional community center opened on Saturday.",
            "supporting_context": "Keep the message accessible.",
            "output_types": output_types,
            "audience": "community members",
            "tone": "clear",
            "language": "English",
            "detail_level": "standard",
            "objective": "inform",
            "style": "plain language",
        },
    )
    assert response.status_code == 200
    return response.json()["transformation_run_id"]


def test_dashboard_and_detail_are_owner_scoped(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, _factory = auth_database
    login(client, "first-owner")
    transformation_id = save_transformation(client, ["executive_summary"])

    dashboard = client.get("/api/transformations")
    assert dashboard.status_code == 200
    assert len(dashboard.json()) == 1
    assert dashboard.json()[0]["status"] == "Draft"
    detail = client.get(f"/api/transformations/{transformation_id}")
    assert detail.status_code == 200
    assert detail.json()["controls"]["audience"] == "community members"
    assert detail.json()["artifact_runs"] == []

    login(client, "second-owner")
    assert client.get("/api/transformations").json() == []
    assert client.get(f"/api/transformations/{transformation_id}").status_code == 404


def test_edit_creates_immutable_version_and_review_state_updates_only_latest(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    install_provider(ReviewTestProvider())
    transformation_id = save_transformation(client, ["executive_summary"])
    generated = run_generation(client, transformation_id, factory).json()
    artifact = generated["artifacts"][0]
    original_content = artifact["artifact_version"]["content"]

    edited = client.post(
        f"/api/artifact-runs/{artifact['artifact_run_id']}/versions",
        json={"content": "Human edited review draft."},
    )

    assert edited.status_code == 200
    assert edited.json()["version_number"] == 2
    assert edited.json()["content"] == "Human edited review draft."
    assert edited.json()["review_status"] == "draft"
    assert edited.json()["provider"] == "human"
    assert edited.json()["model"] == "manual-edit"
    assert edited.json()["prompt_version"] == "manual_edit_v1"
    assert len(edited.json()["prompt_hash"]) == 64
    assert edited.json()["artifact_schema_version"] == "1"
    assert (
        edited.json()["context_manifest_id"] == artifact["artifact_version"]["context_manifest_id"]
    )
    with factory() as session:
        versions = list(session.query(ArtifactVersion).order_by(ArtifactVersion.version_number))
        assert [version.content for version in versions] == [
            original_content,
            "Human edited review draft.",
        ]

    accepted = client.patch(
        f"/api/artifact-versions/{edited.json()['id']}/review",
        json={"review_status": "accepted"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["review_status"] == "accepted"

    old_review = client.patch(
        f"/api/artifact-versions/{artifact['artifact_version']['id']}/review",
        json={"review_status": "rejected"},
    )
    assert old_review.status_code == 409
    detail = client.get(f"/api/transformations/{transformation_id}").json()
    assert len(detail["artifact_runs"][0]["versions"]) == 2
    assert detail["artifact_runs"][0]["versions"][0]["content"] == original_content
    assert detail["artifact_runs"][0]["versions"][1]["review_status"] == "accepted"
    assert detail["status"] == "Complete"

    rejected = client.patch(
        f"/api/artifact-versions/{edited.json()['id']}/review",
        json={"review_status": "rejected"},
    )
    assert rejected.status_code == 200
    assert client.get(f"/api/transformations/{transformation_id}").json()["status"] == (
        "Review Required"
    )


def test_regenerate_creates_next_version_without_overwriting_history(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    install_provider(ReviewTestProvider())
    transformation_id = save_transformation(client, ["executive_summary"])
    first = run_generation(client, transformation_id, factory).json()
    artifact = first["artifacts"][0]

    regenerated = run_artifact_action(client, artifact["artifact_run_id"], "regenerate", factory)

    assert regenerated.status_code == 200
    assert regenerated.json()["artifact_version"]["version_number"] == 2
    assert regenerated.json()["artifact_version"]["content"] == "Regenerated review draft."
    detail = client.get(f"/api/transformations/{transformation_id}").json()
    versions = detail["artifact_runs"][0]["versions"]
    assert [version["content"] for version in versions] == [
        "Generated review draft.",
        "Regenerated review draft.",
    ]


def test_manual_edit_does_not_override_an_active_job_status(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    install_provider(ReviewTestProvider())
    transformation_id = save_transformation(client, ["executive_summary"])
    generated = run_generation(client, transformation_id, factory).json()
    artifact_run_id = generated["artifacts"][0]["artifact_run_id"]

    queued = client.post(f"/api/artifact-runs/{artifact_run_id}/regenerate")
    assert queued.status_code == 202
    assert queued.json()["status"] == "pending"

    edited = client.post(
        f"/api/artifact-runs/{artifact_run_id}/versions",
        json={"content": "Human edited while regeneration is queued."},
    )
    assert edited.status_code == 200
    assert (
        client.get(f"/api/transformations/{transformation_id}").json()["artifact_runs"][0]["status"]
        == "pending"
    )


def test_presentation_edits_are_validated_and_saved_as_new_versions(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    install_provider(ReviewTestProvider())
    transformation_id = save_transformation(client, ["presentation"])
    generated = run_generation(client, transformation_id, factory).json()
    artifact = generated["artifacts"][0]

    invalid = client.post(
        f"/api/artifact-runs/{artifact['artifact_run_id']}/versions",
        json={"content": json.dumps({"title": "Missing slides"})},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_presentation"

    presentation = PresentationSpec(
        title="Edited briefing",
        slides=[
            SlideSpec(
                title="Overview",
                key_message="A verified fictional opening.",
                bullets=["The center opened Saturday."],
                visual_recommendation="Building entrance.",
                speaker_notes="Introduce the center.",
            ),
            SlideSpec(
                title="Visit",
                key_message="Visit during posted hours.",
                bullets=["Check the schedule."],
                visual_recommendation="Hours board.",
                speaker_notes="Close with the schedule.",
            ),
        ],
    )
    edited = client.post(
        f"/api/artifact-runs/{artifact['artifact_run_id']}/versions",
        json={"content": presentation.model_dump_json()},
    )
    assert edited.status_code == 200
    assert edited.json()["version_number"] == 2
    parsed = PresentationSpec.model_validate_json(edited.json()["content"])
    assert parsed.slides[0].speaker_notes == "Introduce the center."


@pytest.mark.parametrize("output_type", ["infographic", "video_package"])
def test_structured_family_edits_validate_and_append_version(
    output_type: str,
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    install_provider(ReviewTestProvider())
    transformation_id = save_transformation(client, [output_type])
    generated = run_generation(client, transformation_id, factory).json()
    artifact = generated["artifacts"][0]
    original = artifact["artifact_version"]

    invalid = client.post(
        f"/api/artifact-runs/{artifact['artifact_run_id']}/versions",
        json={"content": json.dumps({"title": "Malformed specification"})},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == f"invalid_{output_type}"

    if output_type == "infographic":
        edited_value = InfographicSpec(
            title="Edited infographic",
            key_message="An edited key message.",
            blocks=[InfographicCalloutBlock(label="Edited label", value="Edited value")],
            visual_direction="Use a simple calendar illustration.",
        )
    else:
        edited_value = VideoPackageSpec(
            title="Edited package",
            concept="An edited concept.",
            scenes=[
                VideoSceneSpec(
                    title="Edited scene",
                    narration="An edited narration line.",
                    on_screen_text=["Edited screen text"],
                    visual_direction="Show a simple location illustration.",
                )
            ],
        )
    edited = client.post(
        f"/api/artifact-runs/{artifact['artifact_run_id']}/versions",
        json={"content": edited_value.model_dump_json()},
    )

    assert edited.status_code == 200
    result = edited.json()
    assert result["version_number"] == 2
    assert result["artifact_schema_version"] == "1"
    assert result["context_manifest_id"] == original["context_manifest_id"]
    assert result["provider"] == "human"
    assert result["model"] == "manual-edit"
    assert result["prompt_version"] == "manual_edit_v1"
    assert len(result["prompt_hash"]) == 64


@pytest.mark.parametrize(
    ("output_type", "content"),
    [
        ("executive_summary", "Edited, source-grounded summary."),
        ("linkedin_post", "Edited professional post."),
        ("x_post", "🙂" * 280),
        ("advisory", "Edited readable advisory."),
    ],
)
def test_text_family_edits_keep_plain_content_and_schema_metadata(
    output_type: str,
    content: str,
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    install_provider(ReviewTestProvider())
    transformation_id = save_transformation(client, [output_type])
    artifact = run_generation(client, transformation_id, factory).json()["artifacts"][0]
    saved = client.post(
        f"/api/artifact-runs/{artifact['artifact_run_id']}/versions",
        json={"content": content},
    )

    assert saved.status_code == 200
    assert saved.json()["content"] == content
    assert saved.json()["artifact_schema_version"] == "1"
    assert saved.json()["version_number"] == 2


def test_manual_x_post_edit_rejects_more_than_280_unicode_code_points(
    auth_database: tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    client, _engine, factory = auth_database
    login(client)
    install_provider(ReviewTestProvider())
    transformation_id = save_transformation(client, ["x_post"])
    artifact = run_generation(client, transformation_id, factory).json()["artifacts"][0]

    invalid = client.post(
        f"/api/artifact-runs/{artifact['artifact_run_id']}/versions",
        json={"content": "🙂" * 281},
    )

    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_x_post"
