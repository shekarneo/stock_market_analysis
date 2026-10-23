"""Sessions survive a small backward clock step (VM / NTP time sync) but never outlive 12 hours."""

from __future__ import annotations

import time

import pytest
from starlette.requests import Request

from app.auth import SESSION_COOKIE, read_session, start_session
from app.errors import AppError
from app.settings import get_settings


class _Response:
    def __init__(self):
        self.cookies = {}

    def set_cookie(self, key, value, **kwargs):
        self.cookies[key] = value


def _request(token: str) -> Request:
    return Request({"type": "http", "headers": [(b"cookie", f"{SESSION_COOKIE}={token}".encode())]})


def _token(settings) -> str:
    response = _Response()
    start_session(response, settings)
    return response.cookies[SESSION_COOKIE]


def test_small_backward_clock_step_keeps_the_session(monkeypatch):
    settings = get_settings()
    token = _token(settings)
    real = time.time
    monkeypatch.setattr("itsdangerous.timed.time.time", lambda: real() - 30)  # clock stepped back 30 s
    assert read_session(_request(token), settings)["sub"] == "operator"


def test_large_backward_step_and_expiry_are_rejected(monkeypatch):
    settings = get_settings()
    token = _token(settings)
    real = time.time
    monkeypatch.setattr("itsdangerous.timed.time.time", lambda: real() - 3600)  # an hour "in the future"
    with pytest.raises(AppError):
        read_session(_request(token), settings)
    monkeypatch.setattr("itsdangerous.timed.time.time", lambda: real() + 13 * 3600)  # past the 12-hour lifetime
    with pytest.raises(AppError):
        read_session(_request(token), settings)
