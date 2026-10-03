from collections.abc import Mapping

from sqlalchemy.orm import Session

from app.models import AuditEvent


def record_audit_event(
    session: Session,
    *,
    owner_id: int,
    action_type: str,
    target_type: str,
    target_id: int | str,
    request_id: str | None,
    action_plan_id: int | None = None,
    outcome: str = "succeeded",
    safe_metadata: Mapping[str, object] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        owner_id=owner_id,
        actor_user_id=owner_id,
        action_type=action_type,
        target_type=target_type,
        target_id=str(target_id)[:80],
        action_plan_id=action_plan_id,
        request_id=request_id[:80] if request_id else None,
        outcome=outcome,
        safe_metadata=dict(safe_metadata) if safe_metadata else None,
    )
    session.add(event)
    return event
