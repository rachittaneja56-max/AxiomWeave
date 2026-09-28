from app.generation import (
    GenerationProviderError,
    GenerationRequest,
    GenerationResult,
)


class DeterministicGenerationProvider:
    def __init__(
        self,
        result: GenerationResult,
        error: GenerationProviderError | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.requests: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result
