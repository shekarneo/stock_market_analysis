from __future__ import annotations

import logging
import re
from typing import Any

_SECRET_KEYS = {
    "authorization",
    "cookie",
    "password",
    "operator_password",
    "session_secret",
    "api_key",
    "apikey",
    "token",
    "access_token",
    "secret",
    "cursor_api_key",
    "groww_api_token",
    "api_secret",
    "totp_secret",
    "integrations_secret_key",
}

_INLINE = re.compile(
    r"(?i)\b(authorization|api[_-]?key|access[_-]?token|token|password|cookie|secret)"
    r"(\s*[:=]\s*)(\S+)"
)


def redact_text(text: str, secrets: list[str] | None = None) -> str:
    redacted = re.sub(r"(?i)\bbearer\s+(?!%)\S+", "Bearer [REDACTED]", text)
    redacted = re.sub(r"\bsk-[A-Za-z0-9*_\-]{4,}", "[REDACTED]", redacted)
    for secret in secrets or []:
        if secret and len(secret) >= 4:
            redacted = redacted.replace(secret, "[REDACTED]")
    return _INLINE.sub(r"\1\2[REDACTED]", redacted)


def redact_value(value: Any, secrets: list[str] | None = None) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in _SECRET_KEYS:
                cleaned[key] = "[REDACTED]"
            else:
                cleaned[key] = redact_value(item, secrets)
        return cleaned
    if isinstance(value, list):
        return [redact_value(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item, secrets) for item in value)
    if isinstance(value, str):
        return redact_text(value, secrets)
    return value


class RedactFilter(logging.Filter):
    def __init__(self, secrets: list[str] | None = None) -> None:
        super().__init__()
        self.secrets = [item for item in (secrets or []) if item]

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg, self.secrets)
        if isinstance(record.args, dict):
            record.args = redact_value(record.args, self.secrets)
        elif isinstance(record.args, tuple):
            record.args = redact_value(record.args, self.secrets)
        return True
