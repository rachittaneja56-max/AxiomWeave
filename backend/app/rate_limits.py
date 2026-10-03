from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.auth import SESSION_COOKIE_NAME, as_utc
from app.database import get_db_session
from app.models import AuthSession, RateLimitBucket, utc_now
from app.settings import get_settings


def _window_floor(now: datetime, seconds: int) -> datetime:
    timestamp = int(now.timestamp())
    return datetime.fromtimestamp(timestamp - timestamp % seconds, UTC)


def consume_rate_limit(
    session: Session,
    *,
    scope: str,
    key: str,
    limit: int,
    window_seconds: int,
    now: datetime | None = None,
) -> tuple[bool, int]:
    current = now or utc_now()
    window = _window_floor(current, window_seconds)
    values = {
        "scope": scope,
        "key_digest": sha256(key.encode("utf-8")).hexdigest(),
        "window_start": window,
        "request_count": 1,
        "updated_at": current,
    }
    bind = session.get_bind()
    engine: Engine = bind.engine if isinstance(bind, Connection) else bind
    dialect_name = engine.dialect.name
    if dialect_name == "sqlite":
        insert = sqlite_insert(RateLimitBucket).values(**values)
    elif dialect_name == "postgresql":
        insert = postgresql_insert(RateLimitBucket).values(**values)
    else:
        raise RuntimeError("Unsupported rate limit database")
    statement = insert.on_conflict_do_update(
        index_elements=["scope", "key_digest", "window_start"],
        set_={
            "request_count": RateLimitBucket.request_count + 1,
            "updated_at": current,
        },
    ).returning(RateLimitBucket.request_count)
    # Keep abuse-control state in its own transaction so a later application rollback
    # cannot erase it and endpoint commit behavior remains independently testable.
    with engine.begin() as connection:
        count: int | None = connection.execute(statement).scalar_one_or_none()
    request_count = int(count or 0)
    return request_count <= limit, max(1, int(window_seconds - (current - window).total_seconds()))


def rate_limit_dependency(
    scope: str, *, limit: int, window_seconds: int = 60, authenticated: bool = True
) -> Callable[..., None]:
    def enforce(
        request: Request,
        session: Annotated[Session, Depends(get_db_session)],
    ) -> None:
        if not get_settings().rate_limit_enabled:
            return
        if authenticated:
            user_id = request_user_id(session, request)
            if user_id is None:
                return
            key = f"user:{user_id}"
        else:
            client_host = request.client.host if request.client else "unknown"
            key = f"ip:{client_host[:100]}"
        allowed, retry_after = consume_rate_limit(
            session,
            scope=scope,
            key=key,
            limit=limit,
            window_seconds=window_seconds,
        )
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "rate_limited",
                    "message": "Too many requests. Please try again shortly.",
                },
                headers={"Retry-After": str(retry_after)},
            )

    return enforce


def request_user_id(session: Session, request: Request) -> int | None:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        return None
    digest = sha256(raw_token.encode("utf-8")).hexdigest()
    auth_session = session.scalar(
        select(AuthSession).where(AuthSession.session_token_digest == digest)
    )
    if (
        auth_session is None
        or auth_session.revoked_at is not None
        or as_utc(auth_session.expires_at) <= utc_now()
    ):
        return None
    return auth_session.user_id
