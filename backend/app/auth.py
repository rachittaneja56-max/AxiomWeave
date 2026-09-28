import secrets
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Annotated, Any, cast

from fastapi import Depends, HTTPException, Request, Response
from google.auth import exceptions as google_auth_exceptions
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db_session
from app.models import AuthSession, User, utc_now
from app.settings import get_settings

SESSION_COOKIE_NAME = "axiomweave_session"
SESSION_LIFETIME = timedelta(hours=8)


def auth_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code, detail={"code": code, "message": message})


def verify_google_credential(credential: str, client_id: str) -> Mapping[str, object]:
    verifier = cast(Any, id_token).verify_oauth2_token
    claims: Mapping[str, Any] = verifier(credential, google_requests.Request(), client_id)
    return cast(Mapping[str, object], claims)


def _utc(value: datetime) -> datetime:
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
        or _utc(auth_session.expires_at) <= utc_now()
    ):
        raise auth_error(401, "unauthenticated", "Sign in to continue.")

    user = session.get(User, auth_session.user_id)
    if user is None:
        raise auth_error(401, "unauthenticated", "Sign in to continue.")
    return user


def create_local_session(session: Session, subject: str) -> tuple[User, str, datetime]:
    user = session.scalar(select(User).where(User.google_subject == subject))
    if user is None:
        user = User(google_subject=subject)
        session.add(user)
        session.flush()

    raw_token = secrets.token_urlsafe(32)
    expires_at = utc_now() + SESSION_LIFETIME
    session.add(
        AuthSession(
            user_id=user.id,
            session_token_digest=sha256(raw_token.encode("utf-8")).hexdigest(),
            expires_at=expires_at,
        )
    )
    session.commit()
    return user, raw_token, expires_at


def verify_credential_or_raise(credential: str, client_id: str) -> str:
    try:
        claims = verify_google_credential(credential, client_id)
    except (ValueError, google_auth_exceptions.GoogleAuthError):
        raise auth_error(
            401, "invalid_google_credential", "Google sign-in could not be verified."
        ) from None

    subject = claims.get("sub")
    audience = claims.get("aud")
    if not isinstance(subject, str) or not subject or audience != client_id:
        raise auth_error(401, "invalid_google_credential", "Google sign-in could not be verified.")
    return subject
