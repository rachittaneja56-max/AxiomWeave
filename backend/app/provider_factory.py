from app.generation import GenerationProvider
from app.model_policy import TaskProfile, resolve_model_profile
from app.openai_provider import OpenAIGenerationProvider
from app.settings import get_settings


def get_generation_provider(
    task_profile: TaskProfile = "artifact_generation",
) -> GenerationProvider | None:
    settings = get_settings()
    profile = resolve_model_profile(task_profile, settings)
    if not settings.openai_api_key or profile.model is None:
        return None
    return OpenAIGenerationProvider(settings.openai_api_key, profile.model)
