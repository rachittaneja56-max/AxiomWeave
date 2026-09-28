from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    application_instructions: str
    transformation_instructions: str
    source_text: str


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
