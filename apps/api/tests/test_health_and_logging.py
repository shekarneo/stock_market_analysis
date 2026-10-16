from __future__ import annotations

import logging

from app.logging_config import JsonFormatter
from app.risk.ledger import kill_switch_report
from app.security.redact import RedactFilter, redact_text
from app.settings import get_settings


def test_health_reports_paper_without_groww(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["process"] is True
    assert body["database"] is True
    assert body["mode"] == "PAPER"
    assert body["live_trading_enabled"] is False
    assert body["live_order_server_flag"] is False
    assert body["kill_switch"] is False
    assert kill_switch_report(None) is None
    assert "groww" not in response.text.lower()


def test_login_does_not_require_groww_credentials(client):
    denied = client.get("/api/config")
    assert denied.status_code == 401
    signed_in = client.post("/api/session/login", json={"password": "test-password"})
    assert signed_in.status_code == 200


def test_redacts_secrets_from_log_lines():
    settings = get_settings()
    buffer: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            buffer.append(JsonFormatter().format(record))

    handler = Capture()
    handler.addFilter(RedactFilter(secrets=[settings.session_secret, settings.operator_password]))
    logger = logging.getLogger("imm-redact-test")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.info("authorization: Bearer %s", settings.session_secret)
    rendered = "\n".join(buffer)
    assert settings.session_secret not in rendered
    assert "[REDACTED]" in rendered
    assert redact_text("token=test-session-secret", [settings.session_secret]) == "token=[REDACTED]"
    masked = redact_text("Incorrect API key provided: sk-desk-*********mple.")
    assert "sk-" not in masked
