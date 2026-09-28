from datetime import UTC, datetime
from hashlib import sha256
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    SESSION_COOKIE_NAME,
    auth_error,
    clear_session_cookie,
    create_local_session,
    require_current_user,
    set_session_cookie,
    verify_credential_or_raise,
)
from app.database import get_db_session
from app.models import AuthSession, User
from app.settings import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class GoogleCredentialRequest(BaseModel):
    credential: str = Field(min_length=1, max_length=8192)


class SessionResponse(BaseModel):
    authenticated: bool


@router.post("/google", response_model=SessionResponse)
def google_login(
    body: GoogleCredentialRequest,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
) -> SessionResponse:
    client_id = get_settings().google_client_id
    if not client_id:
        raise auth_error(503, "google_auth_not_configured", "Google sign-in is not configured.")
    subject = verify_credential_or_raise(body.credential, client_id)
    _user, raw_token, expires_at = create_local_session(session, subject)
    set_session_cookie(response, raw_token, expires_at)
    return SessionResponse(authenticated=True)


@router.get("/session", response_model=SessionResponse)
def current_session(_user: Annotated[User, Depends(require_current_user)]) -> SessionResponse:
    return SessionResponse(authenticated=True)


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
    response.status_code = 204
    return response
