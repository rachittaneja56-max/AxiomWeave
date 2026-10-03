from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import (
    SESSION_COOKIE_NAME,
    as_utc,
    auth_error,
    clear_session_cookie,
    issue_local_session,
    require_current_user,
    set_session_cookie,
)
from app.database import get_db_session
from app.models import AuthSession, LoginThrottle, User, utc_now
from app.passwords import (
    hash_password,
    normalize_username,
    password_hasher,
    password_needs_rehash,
    validate_password,
    verify_dummy_password,
    verify_password,
)
from app.rate_limits import rate_limit_dependency
from app.security import clear_csrf_cookie, set_csrf_cookie
from app.settings import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])
THROTTLE_WINDOW = timedelta(minutes=15)
THROTTLE_DURATION = timedelta(minutes=15)
THROTTLE_THRESHOLD = 8
INVALID_LOGIN = "Invalid username or password."


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=1024)


class AuthResponse(BaseModel):
    authenticated: bool
    username: str


class AuthConfig(BaseModel):
    registration_enabled: bool


def _credentials(body: Credentials) -> tuple[str, str]:
    try:
        username = normalize_username(body.username)
        validate_password(body.password)
    except ValueError as exc:
        raise auth_error(422, "invalid_credentials", str(exc)) from None
    return username, body.password


@router.get("/config", response_model=AuthConfig)
def auth_config() -> AuthConfig:
    return AuthConfig(registration_enabled=get_settings().allow_registration)


@router.post(
    "/register",
    response_model=AuthResponse,
    dependencies=[
        Depends(
            rate_limit_dependency(
                "registration", limit=30, window_seconds=3600, authenticated=False
            )
        )
    ],
)
def register(
    body: Credentials,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
) -> AuthResponse:
    if not get_settings().allow_registration:
        raise auth_error(403, "registration_disabled", "Account creation is currently closed.")
    username, password = _credentials(body)
    user = User(username=username, password_hash=hash_password(password))
    try:
        session.add(user)
        session.flush()
        raw_token, expires_at = issue_local_session(session, user)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise auth_error(409, "username_unavailable", "That username is unavailable.") from None
    set_session_cookie(response, raw_token, expires_at)
    set_csrf_cookie(response)
    return AuthResponse(authenticated=True, username=user.username)


@router.post(
    "/login",
    response_model=AuthResponse,
    dependencies=[
        Depends(rate_limit_dependency("login", limit=60, window_seconds=600, authenticated=False))
    ],
)
def login(
    body: Credentials,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
) -> AuthResponse:
    try:
        username = normalize_username(body.username)
    except ValueError:
        username = body.username.strip().lower()[:64]
    throttle_key = sha256(username.encode("utf-8")).hexdigest()
    now = utc_now()
    throttle = session.get(LoginThrottle, throttle_key)
    if throttle and throttle.blocked_until and as_utc(throttle.blocked_until) > now:
        retry = max(1, int((as_utc(throttle.blocked_until) - now).total_seconds()))
        raise auth_error(
            429,
            "too_many_login_attempts",
            "Too many sign-in attempts. Please try again later.",
            {"Retry-After": str(retry)},
        )

    user = session.scalar(select(User).where(User.username == username))
    if user is None:
        verify_dummy_password(body.password)
        valid = False
    else:
        valid = verify_password(body.password, user.password_hash)

    if not valid:
        if throttle is None:
            throttle = LoginThrottle(
                login_key_digest=throttle_key,
                failed_attempts=0,
                window_started_at=now,
                updated_at=now,
            )
            session.add(throttle)
        elif now - as_utc(throttle.window_started_at) >= THROTTLE_WINDOW:
            throttle.failed_attempts = 0
            throttle.window_started_at = now
            throttle.blocked_until = None
        throttle.failed_attempts += 1
        if throttle.failed_attempts >= THROTTLE_THRESHOLD:
            throttle.blocked_until = now + THROTTLE_DURATION
        throttle.updated_at = now
        session.commit()
        if throttle.blocked_until:
            retry = max(1, int((as_utc(throttle.blocked_until) - now).total_seconds()))
            raise auth_error(
                429,
                "too_many_login_attempts",
                "Too many sign-in attempts. Please try again later.",
                {"Retry-After": str(retry)},
            ) from None
        raise auth_error(401, "invalid_credentials", INVALID_LOGIN)

    assert user is not None
    if throttle:
        session.delete(throttle)
    if password_needs_rehash(user.password_hash):
        user.password_hash = password_hasher.hash(body.password)
    raw_token, expires_at = issue_local_session(session, user)
    session.commit()
    set_session_cookie(response, raw_token, expires_at)
    set_csrf_cookie(response)
    return AuthResponse(authenticated=True, username=user.username)


@router.get("/session", response_model=AuthResponse)
def current_session(user: Annotated[User, Depends(require_current_user)]) -> AuthResponse:
    return AuthResponse(authenticated=True, username=user.username)


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
) -> Response:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token:
        digest = sha256(raw_token.encode("utf-8")).hexdigest()
        auth_session = session.scalar(
            select(AuthSession).where(AuthSession.session_token_digest == digest)
        )
        if auth_session is not None and auth_session.revoked_at is None:
            auth_session.revoked_at = datetime.now(UTC)
            session.commit()
    clear_session_cookie(response)
    clear_csrf_cookie(response)
    response.status_code = 204
    return response
