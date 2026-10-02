from app.generation import GenerationProvider
from app.openai_provider import OpenAIGenerationProvider
from app.settings import get_settings


def get_generation_provider() -> GenerationProvider | None:
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    return OpenAIGenerationProvider(settings.openai_api_key, settings.openai_model)
