from dataclasses import dataclass
from typing import Literal

from app.settings import Settings, get_settings

TaskProfile = Literal[
    "artifact_generation",
    "lineage_analysis",
    "evidence_analysis",
    "consistency_analysis",
    "action_planning",
    "document_ocr",
    "vision_extraction",
    "asr",
]

PROFILE_VERSION = "task-model-policy-v1"


@dataclass(frozen=True, slots=True)
class ProviderPrivacyProfile:
    provider: str
    task_family: str
    external_processing: bool
    storage_setting: str
    retention_note: str
    allowed_sensitivity: str
    configured: bool
    approval_version: str


@dataclass(frozen=True, slots=True)
class ResolvedModelProfile:
    task_profile: TaskProfile
    provider: str | None
    model: str | None
    status: Literal["current_default", "not_configured"]
    privacy: ProviderPrivacyProfile


def resolve_model_profile(
    task_profile: TaskProfile, settings: Settings | None = None
) -> ResolvedModelProfile:
    config = settings or get_settings()
    primary = config.openai_model
    utility = config.openai_utility_model
    selected: str | None
    if task_profile in {"artifact_generation", "lineage_analysis"}:
        selected = primary
    elif task_profile == "evidence_analysis":
        selected = config.openai_evidence_model or primary
    elif task_profile == "consistency_analysis":
        selected = config.openai_consistency_model or primary
    elif task_profile == "action_planning":
        selected = config.openai_action_model or primary
    elif task_profile == "document_ocr":
        selected = config.openai_ocr_model or utility
    else:
        selected = None

    configured = bool(config.openai_api_key and selected)
    if selected is None:
        privacy = ProviderPrivacyProfile(
            provider="none",
            task_family=task_profile,
            external_processing=False,
            storage_setting="disabled",
            retention_note="No provider is configured for this capability.",
            allowed_sensitivity="none",
            configured=False,
            approval_version=PROFILE_VERSION,
        )
        return ResolvedModelProfile(task_profile, None, None, "not_configured", privacy)

    privacy = ProviderPrivacyProfile(
        provider="openai",
        task_family=task_profile,
        external_processing=True,
        storage_setting="responses_store_false",
        retention_note=(
            "Responses API storage is disabled with store=False; provider retention is governed "
            "by the applicable provider terms. No zero-retention claim is made."
        ),
        allowed_sensitivity="user-provided workspace content; restricted content is not eligible",
        configured=configured,
        approval_version=PROFILE_VERSION,
    )
    return ResolvedModelProfile(
        task_profile,
        "openai" if configured else None,
        selected,
        "current_default" if configured else "not_configured",
        privacy,
    )


def provider_profile_allows_source(profile: ResolvedModelProfile, sensitivity_class: str) -> bool:
    if profile.model is None:
        return False
    if not profile.privacy.external_processing:
        return True
    return sensitivity_class in {"public", "internal"}


def current_model_registry(settings: Settings | None = None) -> list[dict[str, object]]:
    profiles: list[dict[str, object]] = []
    tasks: tuple[TaskProfile, ...] = (
        "artifact_generation",
        "lineage_analysis",
        "evidence_analysis",
        "consistency_analysis",
        "action_planning",
        "document_ocr",
        "vision_extraction",
        "asr",
    )
    for task in tasks:
        resolved = resolve_model_profile(task, settings)
        profiles.append(
            {
                "task": task,
                "provider": resolved.provider or "NOT_CONFIGURED",
                "model": resolved.model or "NOT_CONFIGURED",
                "status": resolved.status,
                "privacy": {
                    "external_processing": resolved.privacy.external_processing,
                    "storage_setting": resolved.privacy.storage_setting,
                    "retention_note": resolved.privacy.retention_note,
                    "allowed_sensitivity": resolved.privacy.allowed_sensitivity,
                },
            }
        )
    profiles.extend(
        {
            "task": task,
            "provider": "NOT_CONFIGURED",
            "model": "NOT_CONFIGURED",
            "status": "not_configured",
        }
        for task in ("tts", "image_generation", "video_generation")
    )
    return profiles
