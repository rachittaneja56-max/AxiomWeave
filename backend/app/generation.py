from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    application_instructions: str
    transformation_instructions: str
    source_text: str
    supporting_context: str = ""
    artifact_content: str = ""
    prior_source_text: str = ""
    changed_source_material: str = ""
    max_output_tokens: int = 1100
    reasoning_effort: str = "low"


@dataclass(frozen=True, slots=True)
class GenerationResult:
    text: str
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_state: str = "disabled"


class GenerationProviderError(Exception):
    """A safe, provider-neutral error for a failed generation operation."""

    def __init__(self) -> None:
        super().__init__("Generation provider operation failed")


class GenerationProvider(Protocol):
    async def generate(self, request: GenerationRequest) -> GenerationResult: ...


T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class StructuredGenerationResult[T: BaseModel]:
    value: T
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_state: str = "disabled"


class StructuredGenerationProvider(Protocol):
    async def generate_structured[T: BaseModel](
        self, request: GenerationRequest, response_model: type[T]
    ) -> StructuredGenerationResult[T]: ...
