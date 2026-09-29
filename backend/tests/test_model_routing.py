from typing import Any, cast

from app.settings import Settings


def test_generation_revision_and_analysis_use_primary_model(
    monkeypatch: Any,
) -> None:
    captured: list[str] = []

    class ProviderStub:
        def __init__(self, _key: str, model: str) -> None:
            captured.append(model)

    settings = cast(Any, Settings)(openai_api_key="test-key", _env_file=None)
    monkeypatch.setattr("app.api.generation.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.generation.OpenAIGenerationProvider", ProviderStub)
    monkeypatch.setattr("app.api.revisions.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.revisions.OpenAIGenerationProvider", ProviderStub)
    monkeypatch.setattr("app.api.evidence.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.evidence.OpenAIGenerationProvider", ProviderStub)

    from app.api.evidence import get_analysis_provider
    from app.api.generation import get_generation_provider
    from app.api.revisions import get_revision_provider

    get_generation_provider()
    get_analysis_provider()
    get_revision_provider()

    assert captured == ["gpt-6-luna", "gpt-6-luna", "gpt-6-luna"]
