import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db_session
from app.models import AuthSession, User, utc_now
from app.settings import get_settings

SESSION_COOKIE_NAME = "axiomweave_session"
SESSION_LIFETIME = timedelta(hours=8)


def auth_error(
    status_code: int, code: str, message: str, headers: dict[str, str] | None = None
) -> HTTPException:
    return HTTPException(status_code, detail={"code": code, "message": message}, headers=headers)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def set_session_cookie(response: Response, raw_token: str, expires_at: datetime) -> None:
    settings = get_settings()
    max_age = max(0, int((expires_at - utc_now()).total_seconds()))
    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw_token,
        max_age=max_age,
        expires=expires_at,
        path="/",
        secure=settings.environment.lower() not in {"development", "dev", "local"},
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=settings.environment.lower() not in {"development", "dev", "local"},
        httponly=True,
        samesite="lax",
    )


def require_current_user(
    request: Request, session: Annotated[Session, Depends(get_db_session)]
) -> User:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        raise auth_error(401, "unauthenticated", "Sign in to continue.")

    digest = sha256(raw_token.encode("utf-8")).hexdigest()
    auth_session = session.scalar(
        select(AuthSession).where(AuthSession.session_token_digest == digest)
    )
    if (
        auth_session is None
        or auth_session.revoked_at is not None
        or as_utc(auth_session.expires_at) <= utc_now()
    ):
        raise auth_error(401, "unauthenticated", "Sign in to continue.")

    user = session.get(User, auth_session.user_id)
    if user is None:
        raise auth_error(401, "unauthenticated", "Sign in to continue.")
    return user


def issue_local_session(session: Session, user: User) -> tuple[str, datetime]:
    raw_token = secrets.token_urlsafe(32)
    expires_at = utc_now() + SESSION_LIFETIME
    session.add(
        AuthSession(
            user_id=user.id,
            session_token_digest=sha256(raw_token.encode("utf-8")).hexdigest(),
            expires_at=expires_at,
        )
    )
    session.flush()
    return raw_token, expires_at
