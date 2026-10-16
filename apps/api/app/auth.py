from __future__ import annotations

import hmac
import secrets

from fastapi import Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.errors import AppError
from app.settings import Settings

SESSION_COOKIE = "imm_session"
CSRF_COOKIE = "imm_csrf"


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt="imm-session")


def login(password: str, response: Response, settings: Settings) -> None:
    if not settings.operator_password:
        raise AppError(
            "LOGIN_UNAVAILABLE",
            "Set OPERATOR_PASSWORD before signing in. Groww credentials are not required.",
            503,
        )
    if not hmac.compare_digest(password, settings.operator_password):
        raise AppError("LOGIN_FAILED", "Incorrect password.", 401)
    start_session(response, settings)


def start_session(response: Response, settings: Settings, *, username: str = "operator") -> None:
    """Set the signed session cookie. The subject stays "operator" for every existing check."""
    csrf = secrets.token_urlsafe(32)
    token = _serializer(settings).dumps({"sub": "operator", "csrf": csrf, "username": username})
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", path="/")
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, samesite="lax", path="/")


def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def read_session(request: Request, settings: Settings) -> dict:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        raise AppError("UNAUTHENTICATED", "Sign in required.", 401)
    try:
        payload = _serializer(settings).loads(raw, max_age=60 * 60 * 12)
    except BadSignature as exc:
        raise AppError("UNAUTHENTICATED", "Sign in required.", 401) from exc
    if payload.get("sub") != "operator":
        raise AppError("UNAUTHENTICATED", "Sign in required.", 401)
    return payload


def require_csrf(request: Request, settings: Settings) -> dict:
    payload = read_session(request, settings)
    header = request.headers.get("x-csrf-token")
    cookie = request.cookies.get(CSRF_COOKIE)
    expected = payload.get("csrf")
    if not header or not cookie or not expected:
        raise AppError("CSRF_FAILED", "CSRF token missing.", 403)
    if not hmac.compare_digest(header, cookie) or not hmac.compare_digest(header, expected):
        raise AppError("CSRF_FAILED", "CSRF token invalid.", 403)
    return payload
