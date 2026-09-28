from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    application_instructions: str
    transformation_instructions: str
    source_text: str
    supporting_context: str = ""


@dataclass(frozen=True, slots=True)
class GenerationResult:
    text: str
    provider: str
    model: str


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


class StructuredGenerationProvider(Protocol):
    async def generate_structured[T: BaseModel](
        self, request: GenerationRequest, response_model: type[T]
    ) -> StructuredGenerationResult[T]: ...
