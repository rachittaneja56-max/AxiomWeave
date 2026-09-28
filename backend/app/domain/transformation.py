from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

SOURCE_TEXT_MAX_LENGTH = 20_000

AudienceText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
ToneText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
LanguageText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
ObjectiveText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
]
StyleText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class OutputType(StrEnum):
    EXECUTIVE_SUMMARY = "executive_summary"
    LINKEDIN_POST = "linkedin_post"
    X_POST = "x_post"
    ADVISORY = "advisory"
    PRESENTATION = "presentation"
    INFOGRAPHIC = "infographic"
    VIDEO_PACKAGE = "video_package"


class TransformationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_text: str = Field(min_length=1)
    output_types: list[OutputType] = Field(min_length=1)
    audience: AudienceText
    tone: ToneText
    language: LanguageText = "English"
    detail_level: Literal["brief", "standard", "detailed"] = "standard"
    objective: ObjectiveText
    style: StyleText

    @field_validator("source_text")
    @classmethod
    def source_must_contain_text(cls, source_text: str) -> str:
        from app.source_versions import normalize_source_text

        return normalize_source_text(source_text)

    @field_validator("output_types")
    @classmethod
    def output_types_must_be_unique(cls, output_types: list[OutputType]) -> list[OutputType]:
        if len(output_types) != len(set(output_types)):
            raise ValueError("Choose each output type only once")
        return output_types


class PreparedTransformationRequest(BaseModel):
    status: Literal["ready"] = "ready"
    request: TransformationRequest


SUPPORTING_CONTEXT_MAX_LENGTH = 5_000
TIER_A_OUTPUT_TYPES = frozenset(
    {
        OutputType.EXECUTIVE_SUMMARY,
        OutputType.LINKEDIN_POST,
        OutputType.ADVISORY,
        OutputType.PRESENTATION,
    }
)


class CreateTransformationRequest(TransformationRequest):
    supporting_context: str = Field(default="", max_length=SUPPORTING_CONTEXT_MAX_LENGTH)

    @field_validator("supporting_context")
    @classmethod
    def blank_context_is_empty(cls, supporting_context: str) -> str:
        return "" if not supporting_context.strip() else supporting_context

    @field_validator("output_types")
    @classmethod
    def only_tier_a_outputs(cls, output_types: list[OutputType]) -> list[OutputType]:
        if any(output_type not in TIER_A_OUTPUT_TYPES for output_type in output_types):
            raise ValueError("Only active Tier-A output types can be saved")
        return output_types
