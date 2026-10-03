"""Versioned output-family contracts shared by generation, review, and analysis."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.domain.transformation import OutputType
from app.presentation import PresentationSpec


class InfographicSectionBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["section"] = "section"
    heading: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=800)]


class InfographicCalloutBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["callout"] = "callout"
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    explanation: str = Field(default="", max_length=400)


class InfographicDataPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    note: str = Field(default="", max_length=300)


class InfographicDataBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["data"] = "data"
    heading: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    rows: list[InfographicDataPoint] = Field(min_length=1, max_length=8)


type InfographicBlock = Annotated[
    InfographicSectionBlock | InfographicCalloutBlock | InfographicDataBlock,
    Field(discriminator="type"),
]


class InfographicSpec(BaseModel):
    """Editable content and layout direction; this is not a rendered image."""

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    subtitle: str = Field(default="", max_length=240)
    key_message: str = Field(default="", max_length=500)
    blocks: list[InfographicBlock] = Field(min_length=1, max_length=12)
    visual_direction: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]


class VideoSceneSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    narration: str = Field(default="", max_length=2_000)
    on_screen_text: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    ] = Field(default_factory=list, max_length=8)
    visual_direction: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]
    transition_notes: str = Field(default="", max_length=240)

    @model_validator(mode="after")
    def scene_has_communication_text(self) -> VideoSceneSpec:
        if not self.narration.strip() and not self.on_screen_text:
            raise ValueError("Each scene needs narration or on-screen text")
        return self


class VideoPackageSpec(BaseModel):
    """Editable production plan; this is not a rendered video."""

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    concept: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
    scenes: list[VideoSceneSpec] = Field(min_length=1, max_length=16)


@dataclass(frozen=True, slots=True)
class ArtifactContract:
    output_type: OutputType
    schema_version: str
    prompt_version: str
    token_budget: int
    instructions: str
    structured_model: type[BaseModel] | None = None


ARTIFACT_CONTRACTS: dict[OutputType, ArtifactContract] = {
    OutputType.EXECUTIVE_SUMMARY: ArtifactContract(
        OutputType.EXECUTIVE_SUMMARY,
        "1",
        "1",
        900,
        "Create an Executive Summary with only source-supported claims.",
    ),
    OutputType.LINKEDIN_POST: ArtifactContract(
        OutputType.LINKEDIN_POST,
        "1",
        "1",
        700,
        "Write a professional post using only source-supported facts. Do not invent statistics, "
        "quotes, dates, hashtags, or claims.",
    ),
    OutputType.X_POST: ArtifactContract(
        OutputType.X_POST,
        "1",
        "2",
        220,
        "Write ONE concise X Post using only source-supported facts. Keep it to a maximum of "
        "280 Unicode code points. Do not fabricate handles, links, quotations, statistics, "
        "dates, or claims. Hashtags are optional and should be used only when clearly useful; "
        "emojis are not required.",
    ),
    OutputType.ADVISORY: ArtifactContract(
        OutputType.ADVISORY,
        "1",
        "1",
        1100,
        "Write a clear, formal advisory using only source-supported facts. Do not invent "
        "statistics, quotes, dates, or claims.",
    ),
    OutputType.PRESENTATION: ArtifactContract(
        OutputType.PRESENTATION,
        "1",
        "1",
        2800,
        "Create a concise presentation and speaker notes. Use only source-supported facts and "
        "follow the required structured presentation schema.",
        PresentationSpec,
    ),
    OutputType.INFOGRAPHIC: ArtifactContract(
        OutputType.INFOGRAPHIC,
        "1",
        "1",
        2200,
        "Create an editable infographic specification, not an image. Use ordered sections, "
        "callouts, and data rows only when supported by the supplied factual context. Never "
        "invent statistics, dates, named entities, quotations, or visual factual claims. Visual "
        "direction is presentation guidance, not evidence. Return the required structured schema.",
        InfographicSpec,
    ),
    OutputType.VIDEO_PACKAGE: ArtifactContract(
        OutputType.VIDEO_PACKAGE,
        "1",
        "1",
        2600,
        "Create an editable video production package, not a rendered video. Provide a concise "
        "concept and ordered scene plan with narration, on-screen text, and visual direction. "
        "Use only source-supported factual claims; do not invent statistics, dates, named "
        "entities, quotations, or visual factual claims. Visual direction is presentation "
        "guidance, not evidence. Return the required structured schema.",
        VideoPackageSpec,
    ),
}


def canonical_json(value: BaseModel) -> str:
    return json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def validate_artifact_content(output_type: OutputType, content: str) -> str:
    """Validate content against its server-selected family contract and canonicalize JSON."""
    if not content.strip():
        raise ValueError("Artifact content cannot be empty")
    contract = ARTIFACT_CONTRACTS[output_type]
    if contract.structured_model is not None:
        return canonical_json(contract.structured_model.model_validate_json(content))
    normalized = content.strip()
    if len(normalized) > 20_000:
        raise ValueError("Artifact content is too long")
    if output_type == OutputType.X_POST and len(normalized) > 280:
        raise ValueError("X Post exceeds 280 Unicode code points")
    return normalized


def artifact_text_projection(output_type: OutputType, content: str) -> str:
    """Return deterministic communication text without exposing structured JSON syntax."""
    contract = ARTIFACT_CONTRACTS[output_type]
    if contract.structured_model is None:
        return content.strip()
    value = contract.structured_model.model_validate_json(content)

    if isinstance(value, PresentationSpec):
        parts = [f"# {value.title}"]
        for index, slide in enumerate(value.slides, 1):
            parts.extend(
                [
                    f"## Slide {index}: {slide.title}",
                    f"Key message: {slide.key_message}",
                    *(f"- {bullet}" for bullet in slide.bullets),
                    f"Visual direction: {slide.visual_recommendation}",
                    f"Speaker notes: {slide.speaker_notes}",
                ]
            )
        return "\n\n".join(parts)

    if isinstance(value, InfographicSpec):
        parts = [f"# {value.title}"]
        if value.subtitle:
            parts.append(value.subtitle)
        if value.key_message:
            parts.append(f"Key message: {value.key_message}")
        for block in value.blocks:
            if isinstance(block, InfographicSectionBlock):
                parts.extend((f"## {block.heading}", block.body))
            elif isinstance(block, InfographicCalloutBlock):
                parts.append(f"{block.label}: {block.value}")
                if block.explanation:
                    parts.append(block.explanation)
            else:
                parts.append(f"## {block.heading}")
                parts.extend(
                    f"{row.label}: {row.value}" + (f" ({row.note})" if row.note else "")
                    for row in block.rows
                )
        parts.append(f"Visual direction: {value.visual_direction}")
        return "\n\n".join(parts)

    if isinstance(value, VideoPackageSpec):
        parts = [f"# {value.title}", f"Concept: {value.concept}"]
        for index, scene in enumerate(value.scenes, 1):
            parts.extend((f"## Scene {index}: {scene.title}",))
            if scene.narration:
                parts.append(f"Narration: {scene.narration}")
            parts.extend(f"On-screen text: {line}" for line in scene.on_screen_text)
            parts.append(f"Visual direction: {scene.visual_direction}")
            if scene.transition_notes:
                parts.append(f"Transition notes: {scene.transition_notes}")
        return "\n\n".join(parts)

    raise ValueError(f"No text projection is defined for {output_type.value}")
