import json
import logging
import re
import secrets
import time
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import RequestResponseEndpoint

from app.settings import get_settings

logger = logging.getLogger("axiomweave.request")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
CSRF_COOKIE_NAME = "axiomweave_csrf"
CSRF_HEADER_NAME = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def set_csrf_cookie(response: Response) -> str:
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        path="/",
        secure=get_settings().environment.lower() not in {"development", "dev", "local"},
        httponly=False,
        samesite="lax",
    )
    return token


def clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(
        CSRF_COOKIE_NAME,
        path="/",
        secure=get_settings().environment.lower() not in {"development", "dev", "local"},
        httponly=False,
        samesite="lax",
    )


def _origin(value: str | None) -> str | None:
    if not value or len(value) > 512:
        return None
    try:
        parsed = urlsplit(value)
        # Accessing `port` validates malformed numeric ports that otherwise look valid.
        _ = parsed.port
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def allowed_origins() -> set[str]:
    configured = get_settings().allowed_frontend_origins
    return {
        origin for item in configured.split(",") if (origin := _origin(item.strip())) is not None
    }


def install_security_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def secure_request_boundary(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        supplied_id = request.headers.get("x-request-id", "")
        request_id = supplied_id if REQUEST_ID_PATTERN.fullmatch(supplied_id) else uuid4().hex
        request.state.request_id = request_id
        method = request.method.upper()
        request_origin_header = request.headers.get("origin")
        request_origin = _origin(request_origin_header)
        if method not in SAFE_METHODS and request_origin_header is not None:
            same_origin = _origin(str(request.base_url))
            if request_origin is None or (
                request_origin != same_origin and request_origin not in allowed_origins()
            ):
                response = JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "code": "unsafe_origin",
                            "message": "Request origin is not allowed.",
                        }
                    },
                )
                return _secure_headers(response, request_id)
            if not request.url.path.endswith(("/auth/login", "/auth/register")):
                cookie = request.cookies.get(CSRF_COOKIE_NAME, "")
                supplied_token = request.headers.get(CSRF_HEADER_NAME, "")
                if (
                    not cookie
                    or not supplied_token
                    or not secrets.compare_digest(cookie, supplied_token)
                ):
                    response = JSONResponse(
                        status_code=403,
                        content={
                            "error": {
                                "code": "csrf_failed",
                                "message": "Request could not be verified.",
                            }
                        },
                    )
                    return _secure_headers(response, request_id)

        started = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception as error:
            logger.error(
                json.dumps(
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "level": "error",
                        "request_id": request_id,
                        "route": request.url.path[:200],
                        "result": "unhandled_error",
                        "exception_type": type(error).__name__[:80],
                    },
                    separators=(",", ":"),
                )
            )
            raise
        duration_ms = round((time.perf_counter() - started) * 1000)
        logger.info(
            json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "level": "info",
                    "request_id": request_id,
                    "route": request.url.path[:200],
                    "method": method,
                    "result": "success" if response.status_code < 400 else "error",
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                },
                separators=(",", ":"),
            )
        )
        return _secure_headers(response, request_id)


def _secure_headers(response: Response, request_id: str) -> Response:
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    return response
