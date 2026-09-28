from pydantic import BaseModel, ConfigDict, Field


class SlideSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    key_message: str = Field(min_length=1, max_length=280)
    bullets: list[str] = Field(min_length=1, max_length=6)
    visual_recommendation: str = Field(min_length=1, max_length=500)
    speaker_notes: str = Field(min_length=1, max_length=2_000)


class PresentationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    slides: list[SlideSpec] = Field(min_length=2, max_length=12)
