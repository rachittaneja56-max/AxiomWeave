import json

import pytest
from pydantic import ValidationError

from app.artifact_contracts import (
    ARTIFACT_CONTRACTS,
    InfographicCalloutBlock,
    InfographicSpec,
    VideoPackageSpec,
    VideoSceneSpec,
    artifact_text_projection,
    validate_artifact_content,
)
from app.domain.transformation import OutputType


def test_every_output_type_has_a_complete_server_owned_contract() -> None:
    assert set(ARTIFACT_CONTRACTS) == set(OutputType)
    for output_type, contract in ARTIFACT_CONTRACTS.items():
        assert contract.output_type == output_type
        assert contract.schema_version == "1"
        assert contract.prompt_version
        assert contract.token_budget > 0
        assert contract.instructions
        if output_type in {
            OutputType.PRESENTATION,
            OutputType.INFOGRAPHIC,
            OutputType.VIDEO_PACKAGE,
        }:
            assert contract.structured_model is not None
        else:
            assert contract.structured_model is None


def test_x_post_contract_counts_unicode_code_points_and_rejects_oversize() -> None:
    assert len(validate_artifact_content(OutputType.X_POST, "🙂" * 280)) == 280
    with pytest.raises(ValueError):
        validate_artifact_content(OutputType.X_POST, "🙂" * 281)


@pytest.mark.parametrize(
    "output_type,content",
    [
        (OutputType.EXECUTIVE_SUMMARY, " \n "),
        (OutputType.LINKEDIN_POST, "x" * 20_001),
        (OutputType.ADVISORY, "\t\n"),
    ],
)
def test_text_families_reject_empty_or_pathologically_oversized_content(
    output_type: OutputType, content: str
) -> None:
    with pytest.raises(ValueError):
        validate_artifact_content(output_type, content)


def test_infographic_spec_is_bounded_and_canonical() -> None:
    spec = InfographicSpec(
        title="Clinic information",
        key_message="The clinic opens on Monday.",
        blocks=[InfographicCalloutBlock(label="Opening", value="Monday")],
        visual_direction="Use a simple calendar illustration.",
    )
    content = spec.model_dump_json()
    canonical = validate_artifact_content(OutputType.INFOGRAPHIC, content)
    assert canonical == json.dumps(
        spec.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    with pytest.raises(ValidationError):
        InfographicSpec.model_validate(
            {
                **spec.model_dump(),
                "arbitrary_scene_graph": {"x": 1},
            }
        )
    projection = artifact_text_projection(OutputType.INFOGRAPHIC, canonical)
    assert "The clinic opens on Monday." in projection
    assert "Monday" in projection
    assert '{"' not in projection
    assert '"blocks"' not in projection


def test_video_package_has_bounded_scenes_and_readable_projection() -> None:
    spec = VideoPackageSpec(
        title="Clinic opening",
        concept="Explain when the clinic opens.",
        scenes=[
            VideoSceneSpec(
                title="Opening day",
                narration="The clinic opens on Monday.",
                on_screen_text=["Opens Monday"],
                visual_direction="Show a simple clinic entrance.",
                transition_notes="Cut to the posted hours.",
            )
        ],
    )
    content = validate_artifact_content(OutputType.VIDEO_PACKAGE, spec.model_dump_json())
    projection = artifact_text_projection(OutputType.VIDEO_PACKAGE, content)
    assert "The clinic opens on Monday." in projection
    assert "Opens Monday" in projection
    assert "Show a simple clinic entrance." in projection
    assert '{"' not in projection
    assert '"scenes"' not in projection
    with pytest.raises(ValidationError):
        VideoSceneSpec(
            title="Empty scene",
            visual_direction="Show a location.",
        )
