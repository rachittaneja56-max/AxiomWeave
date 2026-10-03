from datetime import datetime
from hashlib import sha256

from sqlalchemy.orm import Session

from app.model_policy import PROFILE_VERSION
from app.models import ModelUsageRecord


def prompt_fingerprint(*parts: str) -> str:
    return sha256("\n\0".join(parts).encode("utf-8")).hexdigest()


def record_model_usage(
    session: Session,
    *,
    owner_id: int | None,
    task_profile: str,
    provider: str,
    model: str,
    prompt_hash: str,
    started_at: datetime,
    completed_at: datetime,
    latency_ms: int,
    result_state: str,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_state: str = "disabled",
    error_class: str | None = None,
    job_id: int | None = None,
    artifact_version_id: int | None = None,
    action_plan_id: int | None = None,
) -> ModelUsageRecord:
    row = ModelUsageRecord(
        owner_id=owner_id,
        job_id=job_id,
        artifact_version_id=artifact_version_id,
        action_plan_id=action_plan_id,
        task_profile=task_profile,
        provider=provider[:48],
        model=model[:120],
        profile_version=PROFILE_VERSION,
        prompt_hash=prompt_hash,
        started_at=started_at,
        completed_at=completed_at,
        latency_ms=max(0, latency_ms),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        result_state=result_state,
        cache_state=cache_state[:24],
        error_class=error_class[:80] if error_class else None,
    )
    session.add(row)
    return row
