"""Fernet encryption for integration secrets.

The key is INTEGRATIONS_SECRET_KEY from the environment. This module does not
generate a key and does not read one from the repository.
"""

from __future__ import annotations

import json

from cryptography.fernet import Fernet, InvalidToken

from app.settings import Settings


class SecretBoxError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _fernet(settings: Settings) -> Fernet:
    raw = settings.integrations_secret_key.strip()
    if not raw:
        raise SecretBoxError(
            "SECRET_KEY_UNCONFIGURED",
            "Set INTEGRATIONS_SECRET_KEY to a Fernet key before saving integration credentials.",
        )
    try:
        return Fernet(raw.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise SecretBoxError(
            "SECRET_KEY_INVALID",
            "INTEGRATIONS_SECRET_KEY is not a valid Fernet key.",
        ) from exc


def encrypt_secrets(settings: Settings, secrets: dict) -> str:
    payload = json.dumps(secrets, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _fernet(settings).encrypt(payload).decode("ascii")


def decrypt_secrets(settings: Settings, ciphertext: str) -> dict:
    try:
        raw = _fernet(settings).decrypt(ciphertext.encode("ascii"))
    except InvalidToken as exc:
        raise SecretBoxError(
            "SECRET_KEY_MISMATCH",
            "Stored credentials could not be decrypted with the current key.",
        ) from exc
    loaded = json.loads(raw.decode("utf-8"))
    if not isinstance(loaded, dict):
        raise SecretBoxError("SECRET_PAYLOAD_INVALID", "Stored credentials are not a secret object.")
    return {str(key): value for key, value in loaded.items() if isinstance(value, str)}
