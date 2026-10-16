"""Stored operator account.

One account lives in operator_accounts. Before it exists, the environment
password still signs the operator in, so the desk works on first run. The
password is stored as a salted PBKDF2 hash. Nothing here reads a secret back.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.domain.tables import OperatorAccount
from app.errors import AppError

_ITERATIONS = 240_000
_USERNAME = re.compile(r"^[a-z0-9_.-]{3,64}$")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, expected = stored.split("$", 3)
        rounds = int(iterations)
    except (ValueError, AttributeError):
        return False
    if scheme != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), rounds)
    return hmac.compare_digest(digest.hex(), expected)


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise AppError("WEAK_PASSWORD", "Use at least 8 characters.", 422)
    if len(password) > 256:
        raise AppError("WEAK_PASSWORD", "Use at most 256 characters.", 422)


def validate_username(username: str) -> str:
    cleaned = username.strip().lower()
    if not _USERNAME.match(cleaned):
        raise AppError("INVALID_USERNAME", "Use 3 to 64 lowercase letters, digits, dot, dash, or underscore.", 422)
    return cleaned


def validate_timezone(name: str) -> str:
    cleaned = name.strip() or "Asia/Kolkata"
    try:
        ZoneInfo(cleaned)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise AppError("INVALID_TIMEZONE", "That timezone name is not recognised.", 422) from exc
    return cleaned


def stored_account(session: Session) -> OperatorAccount | None:
    """The stored account, or None when none exists or the table is absent."""
    try:
        return session.execute(select(OperatorAccount).order_by(OperatorAccount.id).limit(1)).scalar_one_or_none()
    except SQLAlchemyError:
        session.rollback()
        return None


def table_available(session: Session) -> bool:
    try:
        return inspect(session.get_bind()).has_table(OperatorAccount.__tablename__)
    except SQLAlchemyError:
        session.rollback()
        return False


def account_status(session: Session) -> dict:
    available = table_available(session)
    row = stored_account(session) if available else None
    return {
        "account_exists": row is not None,
        "signup_open": available and row is None,
        "storage_ready": available,
        "login_source": "database" if row is not None else "environment",
    }


def create_account(session: Session, *, username: str, password: str, display_name: str) -> OperatorAccount:
    if not table_available(session):
        raise AppError(
            "ACCOUNT_STORAGE_MISSING",
            "The database has no operator_accounts table yet. Run `alembic upgrade head` for the API database, then sign up.",
            503,
        )
    if stored_account(session) is not None:
        raise AppError("ACCOUNT_EXISTS", "The operator account already exists. Sign in instead.", 409)
    name = validate_username(username)
    validate_password(password)
    label = " ".join(display_name.split())[:120] or name
    row = OperatorAccount(
        username=name,
        password_hash=hash_password(password),
        display_name=label,
        timezone="Asia/Kolkata",
    )
    session.add(row)
    session.flush()
    return row


def authenticate(session: Session, *, password: str, env_password: str, username: str | None = None) -> dict:
    """Return the actor for a correct password. The stored account wins once it exists."""
    row = stored_account(session)
    if row is not None:
        if username and username.strip().lower() != row.username:
            raise AppError("LOGIN_FAILED", "Incorrect username or password.", 401)
        if not verify_password(password, row.password_hash):
            raise AppError("LOGIN_FAILED", "Incorrect username or password.", 401)
        row.last_login_at = datetime.now(timezone.utc)
        session.flush()
        return {"username": row.username, "display_name": row.display_name, "source": "database"}
    if not env_password:
        raise AppError(
            "LOGIN_UNAVAILABLE",
            "No operator account exists yet. Create one on the signup page, or set OPERATOR_PASSWORD.",
            503,
        )
    if not hmac.compare_digest(password, env_password):
        raise AppError("LOGIN_FAILED", "Incorrect password.", 401)
    return {"username": "operator", "display_name": "Operator", "source": "environment"}


def profile(session: Session) -> dict:
    row = stored_account(session)
    if row is None:
        return {
            "username": "operator",
            "display_name": "Operator",
            "timezone": "Asia/Kolkata",
            "source": "environment",
            "created_at": None,
            "last_login_at": None,
            "stored": False,
        }
    return {
        "username": row.username,
        "display_name": row.display_name,
        "timezone": row.timezone,
        "source": "database",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_login_at": row.last_login_at.isoformat() if row.last_login_at else None,
        "stored": True,
    }


def update_profile(session: Session, *, display_name: str | None, timezone_name: str | None) -> dict:
    row = stored_account(session)
    if row is None:
        raise AppError("ACCOUNT_REQUIRED", "Create the operator account before editing the profile.", 409)
    if display_name is not None:
        label = " ".join(display_name.split())[:120]
        if not label:
            raise AppError("INVALID_DISPLAY_NAME", "The display name cannot be empty.", 422)
        row.display_name = label
    if timezone_name is not None:
        row.timezone = validate_timezone(timezone_name)
    row.updated_at = datetime.now(timezone.utc)
    session.flush()
    return profile(session)


def change_password(session: Session, *, current: str, new: str) -> None:
    row = stored_account(session)
    if row is None:
        raise AppError("ACCOUNT_REQUIRED", "Create the operator account before changing its password.", 409)
    if not verify_password(current, row.password_hash):
        raise AppError("LOGIN_FAILED", "The current password is incorrect.", 401)
    validate_password(new)
    row.password_hash = hash_password(new)
    row.updated_at = datetime.now(timezone.utc)
    session.flush()
