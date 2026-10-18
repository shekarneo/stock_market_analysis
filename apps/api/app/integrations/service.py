"""Save, clear, and test Groww and OpenAI credentials.

Read responses contain presence flags and the last test. They do not contain
secret values. A saved credential is not a successful connection test.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.tables import IntegrationCredential, utcnow
from app.integrations.crypto import SecretBoxError, decrypt_secrets, encrypt_secrets
from app.integrations.groww import (
    GrowwCallError,
    classify_margin,
    classify_token_expiry,
    exchange_token,
    expiry_deadline,
    read_documented_quote,
    read_margin,
)
from app.integrations.http import HttpxCaller
from app.integrations.openai_client import MODEL_RE
from app.integrations.openai_client import classify as classify_openai
from app.integrations.openai_client import list_models, retrieve_model
from app.security.redact import redact_text
from app.settings import Settings

log = logging.getLogger("imm.integrations")
LABEL_RE = re.compile(r"^[A-Za-z0-9 ._-]{0,80}$")
GROWW_METHODS = {"access_token", "api_key_secret", "totp"}


class IntegrationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def public_status() -> dict:
    return {
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
        "live_trading_enabled": False,
        "orders_placed_by_connection_tests": False,
    }


def ensure_env_credentials_loaded(session: Session, settings: Settings) -> None:
    """Load credentials from root .env and process environment by default into IntegrationCredential storage."""
    from dotenv import dotenv_values
    from app.settings import REPO_ROOT
    import os

    env_vals: dict[str, str] = {}
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for k, v in dotenv_values(env_file).items():
            if v is not None and str(v).strip():
                env_vals[k] = str(v).strip()
    for k, v in os.environ.items():
        if v and v.strip():
            env_vals[k] = v.strip()

    # 1. Groww
    groww_key = env_vals.get("GROWW_TOTP_TOKEN") or env_vals.get("GROWW_API_KEYS") or env_vals.get("GROWW_API_KEY")
    groww_totp = env_vals.get("GROWW_TOTP_SECRET")
    groww_secret = env_vals.get("GROWW_API_SECRET")
    groww_token = env_vals.get("GROWW_ACCESS_TOKEN")

    groww_row = session.get(IntegrationCredential, "groww")
    need_groww_seed = False
    if groww_row is None or not groww_row.ciphertext:
        need_groww_seed = True
    else:
        try:
            decrypt_secrets(settings, groww_row.ciphertext)
        except Exception:
            need_groww_seed = True

    if need_groww_seed:
        if groww_key and groww_totp:
            groww_row = _row(session, "groww")
            groww_row.ciphertext = encrypt_secrets(settings, {"api_key": groww_key, "totp_secret": groww_totp})
            groww_row.auth_method = "totp"
            groww_row.enabled = False
            groww_row.token_expiry = None
            groww_row.derived_access_token = False
            groww_row.updated_at = utcnow()
        elif groww_key and groww_secret:
            groww_row = _row(session, "groww")
            groww_row.ciphertext = encrypt_secrets(settings, {"api_key": groww_key, "api_secret": groww_secret})
            groww_row.auth_method = "api_key_secret"
            groww_row.enabled = False
            groww_row.updated_at = utcnow()
        elif groww_token:
            groww_row = _row(session, "groww")
            groww_row.ciphertext = encrypt_secrets(settings, {"access_token": groww_token})
            groww_row.auth_method = "access_token"
            groww_row.enabled = False
            groww_row.token_expiry = _extract_jwt_expiry(groww_token)
            groww_row.updated_at = utcnow()

    # 2. OpenAI
    openai_key = env_vals.get("OPENAI_API_KEY")
    openai_row = session.get(IntegrationCredential, "openai")
    need_openai_seed = False
    if openai_row is None or not openai_row.ciphertext:
        need_openai_seed = True
    else:
        try:
            decrypt_secrets(settings, openai_row.ciphertext)
        except Exception:
            need_openai_seed = True

    if need_openai_seed and openai_key:
        openai_row = _row(session, "openai")
        openai_row.ciphertext = encrypt_secrets(settings, {"api_key": openai_key})
        openai_row.auth_method = "api_key"
        openai_row.model = openai_row.model or "gpt-4o-mini"
        openai_row.enabled = True
        openai_row.updated_at = utcnow()

    # 3. Gemini
    gemini_key = env_vals.get("GEMINI_API_KEYS") or env_vals.get("GEMINI_API_KEY")
    gemini_row = session.get(IntegrationCredential, "gemini")
    need_gemini_seed = False
    if gemini_row is None or not gemini_row.ciphertext:
        need_gemini_seed = True
    else:
        try:
            decrypt_secrets(settings, gemini_row.ciphertext)
        except Exception:
            need_gemini_seed = True

    if need_gemini_seed and gemini_key:
        gemini_row = _row(session, "gemini")
        gemini_row.ciphertext = encrypt_secrets(settings, {"api_key": gemini_key})
        gemini_row.auth_method = "api_key"
        gemini_row.model = gemini_row.model or "gemini-2.5-flash"
        gemini_row.enabled = True
        gemini_row.updated_at = utcnow()

    # 4. Upstox
    upstox_token = env_vals.get("UPSTOX_ACCESS_TOKEN")
    upstox_row = session.get(IntegrationCredential, "upstox")
    if (upstox_row is None or not upstox_row.ciphertext) and upstox_token:
        upstox_row = _row(session, "upstox")
        upstox_row.ciphertext = encrypt_secrets(settings, {"access_token": upstox_token})
        upstox_row.auth_method = "access_token"
        upstox_row.enabled = True
        upstox_row.updated_at = utcnow()

    # 5. Kite
    kite_key = env_vals.get("KITE_API_KEY")
    kite_token = env_vals.get("KITE_ACCESS_TOKEN")
    kite_row = session.get(IntegrationCredential, "kite")
    if (kite_row is None or not kite_row.ciphertext) and kite_key and kite_token:
        kite_row = _row(session, "kite")
        kite_row.ciphertext = encrypt_secrets(settings, {"api_key": kite_key, "access_token": kite_token})
        kite_row.auth_method = "token"
        kite_row.enabled = True
        kite_row.updated_at = utcnow()

    # 6. Angel One
    angel_key = env_vals.get("ANGELONE_API_KEY")
    angel_code = env_vals.get("ANGELONE_CLIENT_CODE")
    angel_jwt = env_vals.get("ANGELONE_JWT_TOKEN")
    angel_row = session.get(IntegrationCredential, "angelone")
    if (angel_row is None or not angel_row.ciphertext) and angel_key and angel_jwt:
        angel_row = _row(session, "angelone")
        angel_row.ciphertext = encrypt_secrets(settings, {
            "api_key": angel_key,
            "client_code": angel_code or "default",
            "jwt_token": angel_jwt,
        })
        angel_row.auth_method = "jwt"
        angel_row.enabled = True
        angel_row.updated_at = utcnow()

    session.flush()


def read_status(session: Session) -> dict:
    rows = {row.provider: row for row in session.scalars(select(IntegrationCredential))}
    groww = _public_groww(rows.get("groww"))
    summaries = quarantine_summaries()
    one_minute = [item for item in summaries if item.get("candle_interval") == "1minute"]
    groww["historical_candles"] = "quarantined_unverified" if summaries else "not_tested"
    groww["permissions"]["historical_candles"] = groww["historical_candles"]
    groww["one_minute_diagnostic"] = "quarantined_unverified" if one_minute else "not_tested"
    groww["diagnostic_history"] = summaries
    groww["diagnostic_request"] = {
        "exchange": "NSE",
        "segment": "CASH",
        "groww_symbol": "NSE-NIFTY",
        "candle_interval": "1minute",
        "maximum_span_minutes": 30,
        "session_verified": False,
    }
    return {
        "groww": groww,
        "openai": _public_openai(rows.get("openai")),
        "gemini": _public_gemini(rows.get("gemini")),
        "upstox": _public_upstox(rows.get("upstox")),
        "kite": _public_kite(rows.get("kite")),
        "angelone": _public_angelone(rows.get("angelone")),
        "indmoney": _public_indmoney(),
        "nse_official": _public_nse_official(),
        **public_status(),
    }


def quarantine_summaries() -> list[dict]:
    """Read quarantine metadata. Does not rewrite a file or call a provider."""
    from app.market.history import HistoryStoreError, history_store
    from app.market.retrieval import QuarantineStore

    store = QuarantineStore(history_store().root / "quarantine")
    summaries = []
    for quarantine_id in store.list_ids():
        try:
            record = store.read(quarantine_id)
        except HistoryStoreError:
            summaries.append({"quarantine_id": quarantine_id, "readable": False, "trusted_dataset_created": False})
            continue
        summaries.append(
            {
                "quarantine_id": record.get("quarantine_id"),
                "checksum": record.get("checksum"),
                "readable": True,
                "label": record.get("label"),
                "exchange": record.get("exchange"),
                "segment": record.get("segment"),
                "groww_symbol": record.get("groww_symbol"),
                "candle_interval": record.get("candle_interval"),
                "candle_count": record.get("candle_count"),
                "http_status": record.get("http_status"),
                "provider_status": record.get("provider_status"),
                "first_raw_timestamp": record.get("first_raw_timestamp"),
                "last_raw_timestamp": record.get("last_raw_timestamp"),
                "requested_start_sent": record.get("requested_start_sent"),
                "requested_end_sent": record.get("requested_end_sent"),
                "timestamp_timezone": record.get("timestamp_timezone"),
                "candle_boundary": record.get("candle_boundary"),
                "diagnostic": record.get("diagnostic"),
                "trusted_dataset_created": False,
                "real_market_data_verified": False,
            }
        )
    return summaries


def _extract_jwt_expiry(token: str | None) -> str | None:
    if not token or not isinstance(token, str):
        return None
    parts = token.strip().split(".")
    if len(parts) == 3:
        try:
            import base64
            import json
            padded = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
            data = json.loads(base64.urlsafe_b64decode(padded))
            exp = data.get("exp")
            if isinstance(exp, (int, float)):
                return datetime.fromtimestamp(exp, tz=timezone.utc).isoformat()
        except Exception:
            pass
    return None


def save_groww(session: Session, settings: Settings, body: dict) -> dict:
    method = body["method"]
    if method not in GROWW_METHODS:
        raise IntegrationError("UNSUPPORTED_AUTH_METHOD", "Use access_token, api_key_secret, or totp.")
    label = _label(body.get("label") or "")
    row = session.get(IntegrationCredential, "groww")
    existing_secrets = {}
    if row and row.ciphertext:
        try:
            existing_secrets = decrypt_secrets(settings, row.ciphertext)
        except Exception:
            existing_secrets = {}
    secrets = _groww_secrets(method, body, existing_secrets)
    row = _row(session, "groww")
    row.ciphertext = encrypt_secrets(settings, secrets)
    row.auth_method = method
    row.label = label or None
    row.token_expiry = _extract_jwt_expiry(secrets.get("access_token")) if method == "access_token" else None
    row.derived_access_token = False
    row.enabled = bool(body["enabled"]) if "enabled" in body else False
    _clear_test(row)
    row.updated_at = utcnow()
    session.flush()
    return read_status(session)


def save_openai(session: Session, settings: Settings, body: dict) -> dict:
    model = _model(body.get("model") or "")
    row = session.get(IntegrationCredential, "openai")
    existing_secrets = {}
    if row and row.ciphertext:
        try:
            existing_secrets = decrypt_secrets(settings, row.ciphertext)
        except Exception:
            existing_secrets = {}
    api_key = _resolve_secret_field(body.get("api_key"), existing_secrets.get("api_key"), "API key")
    row = _row(session, "openai")
    row.ciphertext = encrypt_secrets(settings, {"api_key": api_key})
    row.model = model
    row.auth_method = "api_key"
    row.label = _label(body.get("label") or "") or None
    if "enabled" in body:
        row.enabled = bool(body["enabled"])
    _clear_test(row)
    row.updated_at = utcnow()
    session.flush()
    return read_status(session)


def disconnect_provider(session: Session, provider: str) -> dict:
    row = session.get(IntegrationCredential, provider)
    if row is None or not row.ciphertext:
        raise IntegrationError("NOT_CONFIGURED", f"Save {provider} credentials before disconnecting.")
    row.enabled = False
    if provider == "groww" and row.derived_access_token:
        row.derived_access_token = False
        row.token_expiry = None
        try:
            from app.settings import get_settings
            secrets = decrypt_secrets(get_settings(), row.ciphertext)
            if "access_token" in secrets:
                secrets.pop("access_token", None)
                row.ciphertext = encrypt_secrets(get_settings(), secrets)
        except Exception:
            pass
    row.last_test_ok = None
    row.last_test_code = "DISCONNECTED"
    row.last_test_message = f"{provider.capitalize()} disconnected. Background usage and synchronization stopped; credentials retained."
    row.updated_at = utcnow()
    session.flush()
    return read_status(session)


def set_groww_enabled(session: Session, enabled: bool, *, confirm: bool) -> dict:
    """Persist Groww enablement only after an explicit confirmation.

    This does not change live trading, call Groww, or refresh a token.
    """
    if confirm is not True:
        raise IntegrationError(
            "CONFIRMATION_REQUIRED",
            "Enabling or disabling Groww needs an explicit confirmation. The setting was not changed.",
        )
    if not enabled:
        return disconnect_provider(session, "groww")
    row = session.get(IntegrationCredential, "groww")
    if row is None or not row.ciphertext:
        raise IntegrationError("NOT_CONFIGURED", "Save Groww credentials before changing integration enablement.")
    row.enabled = True
    row.updated_at = utcnow()
    session.flush()
    return read_status(session)


def set_openai_profile(session: Session, model: str, label: str, *, confirm: bool) -> dict:
    """Store the OpenAI model and label after an explicit confirmation.

    The saved key, enablement, and connection-test record stay as they are.
    This does not call OpenAI.
    """
    if confirm is not True:
        raise IntegrationError(
            "CONFIRMATION_REQUIRED",
            "Saving the OpenAI model needs an explicit confirmation. The setting was not changed.",
        )
    row = session.get(IntegrationCredential, "openai")
    import os
    env_key = os.environ.get("OPENAI_API_KEY")
    if (row is None or not row.ciphertext) and env_key:
        from app.settings import get_settings
        row = _row(session, "openai")
        row.ciphertext = encrypt_secrets(get_settings(), {"api_key": env_key})
        row.auth_method = "api_key"
    if row is None or not row.ciphertext:
        raise IntegrationError("NOT_CONFIGURED", "Save an OpenAI API key before changing the model.")
    row.model = _model(model)
    row.label = _label(label or "") or None
    row.updated_at = utcnow()
    session.flush()
    return read_status(session)


def set_openai_enabled(session: Session, enabled: bool) -> dict:
    if not enabled:
        return disconnect_provider(session, "openai")
    import os
    row = session.get(IntegrationCredential, "openai")
    env_key = os.environ.get("OPENAI_API_KEY")
    if (row is None or not row.ciphertext) and env_key:
        from app.settings import get_settings
        row = _row(session, "openai")
        row.ciphertext = encrypt_secrets(get_settings(), {"api_key": env_key})
        row.auth_method = "api_key"
        row.enabled = True
        row.updated_at = utcnow()
        session.flush()
        return read_status(session)
    if row is None or not row.ciphertext:
        raise IntegrationError("NOT_CONFIGURED", "Save an OpenAI API key before enabling the integration.")
    row.enabled = True
    row.updated_at = utcnow()
    session.flush()
    return read_status(session)


def save_upstox(session: Session, settings: Settings, body: dict) -> dict:
    row = session.get(IntegrationCredential, "upstox")
    existing_secrets = {}
    if row and row.ciphertext:
        try:
            existing_secrets = decrypt_secrets(settings, row.ciphertext)
        except Exception:
            existing_secrets = {}
    access_token = _resolve_secret_field(body.get("access_token"), existing_secrets.get("access_token"), "Access token")
    row = _row(session, "upstox")
    row.ciphertext = encrypt_secrets(settings, {"access_token": access_token})
    row.auth_method = "access_token"
    row.label = _label(body.get("label") or "") or None
    if "enabled" in body:
        row.enabled = bool(body["enabled"])
    _clear_test(row)
    row.updated_at = utcnow()
    session.flush()
    return read_status(session)


def save_kite(session: Session, settings: Settings, body: dict) -> dict:
    row = session.get(IntegrationCredential, "kite")
    existing_secrets = {}
    if row and row.ciphertext:
        try:
            existing_secrets = decrypt_secrets(settings, row.ciphertext)
        except Exception:
            existing_secrets = {}
    api_key = _resolve_secret_field(body.get("api_key"), existing_secrets.get("api_key"), "API key")
    access_token = _resolve_secret_field(body.get("access_token"), existing_secrets.get("access_token"), "Access token")
    row = _row(session, "kite")
    row.ciphertext = encrypt_secrets(settings, {"api_key": api_key, "access_token": access_token})
    row.auth_method = "token"
    row.label = _label(body.get("label") or "") or None
    if "enabled" in body:
        row.enabled = bool(body["enabled"])
    _clear_test(row)
    row.updated_at = utcnow()
    session.flush()
    return read_status(session)


def save_angelone(session: Session, settings: Settings, body: dict) -> dict:
    row = session.get(IntegrationCredential, "angelone")
    existing_secrets = {}
    if row and row.ciphertext:
        try:
            existing_secrets = decrypt_secrets(settings, row.ciphertext)
        except Exception:
            existing_secrets = {}
    api_key = _resolve_secret_field(body.get("api_key"), existing_secrets.get("api_key"), "API key")
    client_code = _resolve_secret_field(body.get("client_code"), existing_secrets.get("client_code"), "Client code")
    jwt_token = _resolve_secret_field(body.get("jwt_token"), existing_secrets.get("jwt_token"), "JWT token")
    row = _row(session, "angelone")
    row.ciphertext = encrypt_secrets(settings, {"api_key": api_key, "client_code": client_code, "jwt_token": jwt_token})
    row.auth_method = "jwt"
    row.label = _label(body.get("label") or "") or None
    if "enabled" in body:
        row.enabled = bool(body["enabled"])
    _clear_test(row)
    row.updated_at = utcnow()
    session.flush()
    return read_status(session)


def save_gemini(session: Session, settings: Settings, body: dict) -> dict:
    row = session.get(IntegrationCredential, "gemini")
    existing_secrets = {}
    if row and row.ciphertext:
        try:
            existing_secrets = decrypt_secrets(settings, row.ciphertext)
        except Exception:
            existing_secrets = {}
    api_key = _resolve_secret_field(body.get("api_key"), existing_secrets.get("api_key"), "API key")
    model = _model(body.get("model") or "gemini-2.5-flash")
    row = _row(session, "gemini")
    row.ciphertext = encrypt_secrets(settings, {"api_key": api_key})
    row.model = model
    row.auth_method = "api_key"
    row.label = _label(body.get("label") or "") or None
    if "enabled" in body:
        row.enabled = bool(body["enabled"])
    _clear_test(row)
    row.updated_at = utcnow()
    session.flush()
    return read_status(session)


def set_provider_enabled(session: Session, provider: str, enabled: bool) -> dict:
    if not enabled:
        return disconnect_provider(session, provider)
    import os
    row = session.get(IntegrationCredential, provider)
    env_key = os.environ.get(f"{provider.upper()}_API_KEY")
    if (row is None or not row.ciphertext) and env_key:
        from app.settings import get_settings
        row = _row(session, provider)
        row.ciphertext = encrypt_secrets(get_settings(), {"api_key": env_key})
        row.auth_method = "api_key"
        row.enabled = True
        row.updated_at = utcnow()
        session.flush()
        return read_status(session)
    if row is None or not row.ciphertext:
        raise IntegrationError("NOT_CONFIGURED", f"Save {provider} credentials before enabling the integration.")
    row.enabled = True
    row.updated_at = utcnow()
    session.flush()
    return read_status(session)


def set_gemini_profile(session: Session, model: str, label: str, *, confirm: bool) -> dict:
    if confirm is not True:
        raise IntegrationError("CONFIRMATION_REQUIRED", "Saving the Gemini model needs an explicit confirmation.")
    row = session.get(IntegrationCredential, "gemini")
    import os
    env_key = os.environ.get("GEMINI_API_KEY")
    if (row is None or not row.ciphertext) and env_key:
        from app.settings import get_settings
        row = _row(session, "gemini")
        row.ciphertext = encrypt_secrets(get_settings(), {"api_key": env_key})
        row.auth_method = "api_key"
    if row is None or not row.ciphertext:
        raise IntegrationError("NOT_CONFIGURED", "Save a Gemini API key before changing the model.")
    row.model = _model(model)
    row.label = _label(label or "") or None
    row.updated_at = utcnow()
    session.flush()
    return read_status(session)


def set_provider_profile(session: Session, provider: str, label: str, *, confirm: bool = True) -> dict:
    row = session.get(IntegrationCredential, provider)
    if row is None or not row.ciphertext:
        raise IntegrationError("NOT_CONFIGURED", f"Save {provider} credentials before updating profile.")
    row.label = _label(label or "") or None
    row.updated_at = utcnow()
    session.flush()
    return read_status(session)


def clear_provider(session: Session, provider: str) -> dict:
    row = session.get(IntegrationCredential, provider)
    if row is not None:
        session.delete(row)
        session.flush()
    return read_status(session)


def run_groww_test(session: Session, settings: Settings, caller=None) -> dict:
    caller = caller or HttpxCaller()
    row = session.get(IntegrationCredential, "groww")
    if row is None or not row.ciphertext:
        return _finish(session, None, False, "NOT_CONFIGURED", "Groww credentials are not saved.", provider="groww")
    try:
        secrets = decrypt_secrets(settings, row.ciphertext)
    except SecretBoxError as exc:
        raise IntegrationError(exc.code, exc.message) from exc
    secret_values = [value for value in secrets.values() if value]
    now = datetime.now(timezone.utc)
    try:
        token, expiry, exchanged = _groww_access_token(caller, row, secrets, now)
        if exchanged:
            _store_derived_token(session, settings, row, secrets, token, expiry)
        result = read_margin(caller, token)
        margin_ok, margin_code, margin_message = classify_margin(result)

        # Stale cached token recovery: if margin returns 401/403 and auth method is TOTP, force re-exchange once
        if not margin_ok and margin_code == "AUTHENTICATION_FAILED" and row.auth_method == "totp" and not exchanged:
            try:
                token, expiry, exchanged = _groww_access_token(caller, row, secrets, now, force_exchange=True)
                _store_derived_token(session, settings, row, secrets, token, expiry)
                result = read_margin(caller, token)
                margin_ok, margin_code, margin_message = classify_margin(result)
            except GrowwCallError as retry_exc:
                margin_ok, margin_code, margin_message = False, retry_exc.code, retry_exc.message

        auth_ok = margin_ok
        market_data_ok = False
        market_data_msg = ""
        if auth_ok:
            try:
                quote_res = read_documented_quote(caller, token)
                from app.market.live_quotes import _normalize_quote
                norm = _normalize_quote(quote_res, now)
                market_data_ok = bool(norm.get("ok"))
                market_data_msg = norm.get("message") or ("Market data quote verified." if market_data_ok else "Quote format rejected.")
            except TimeoutError:
                market_data_ok = False
                market_data_msg = "Market data quote request timed out."
            except Exception as q_exc:
                market_data_ok = False
                market_data_msg = redact_text(q_exc.__class__.__name__, secret_values)

        if auth_ok and market_data_ok:
            ok = True
            code = "CONNECTED"
            message = "Authentication (margin) and market data quote verified successfully."
        elif auth_ok and not market_data_ok:
            ok = False
            code = "MARKET_DATA_REJECTED"
            message = f"Authentication succeeded, but market data quote failed: {market_data_msg}"
        else:
            ok = False
            code = margin_code
            message = margin_message
    except GrowwCallError as exc:
        ok, code, message = False, exc.code, exc.message
    except TimeoutError:
        ok, code, message = False, "TIMEOUT", "The Groww request timed out. It was not retried."
    except Exception as exc:
        ok, code, message = False, "PROVIDER_ERROR", exc.__class__.__name__
    message = redact_text(message, secret_values)
    _safe_log(f"groww connection test {code}", secret_values)
    return _finish(session, row, ok, code, message, provider="groww")


def run_openai_test(session: Session, settings: Settings, caller=None) -> dict:
    caller = caller or HttpxCaller()
    import os
    row = session.get(IntegrationCredential, "openai")
    api_key = ""
    model = (row.model if row and row.model else "gpt-4.1-mini")
    if row and row.ciphertext:
        try:
            secrets = decrypt_secrets(settings, row.ciphertext)
            api_key = secrets.get("api_key") or ""
        except SecretBoxError as exc:
            raise IntegrationError(exc.code, exc.message) from exc
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY", "")

    if not api_key:
        return _finish(session, None, False, "NOT_CONFIGURED", "OpenAI credentials are not saved.", provider="openai")
    if row and not row.enabled and not os.environ.get("OPENAI_API_KEY"):
        return _finish(session, row, False, "INTEGRATION_DISABLED", "OpenAI is disabled. No request was sent.", provider="openai")
    try:
        result = retrieve_model(caller, api_key=api_key, model=model)
        ok, code, message = classify_openai(result, api_key=api_key, model=model)
    except TimeoutError:
        ok, code, message = False, "TIMEOUT", "The OpenAI request timed out. It was not retried."
    except Exception as exc:
        ok, code, message = False, "PROVIDER_ERROR", redact_text(exc.__class__.__name__, [api_key])
    _safe_log(f"openai connection test {code}: {message}", [api_key])
    return _finish(session, row, ok, code, message, provider="openai")


def run_upstox_test(session: Session, settings: Settings, caller=None) -> dict:
    caller = caller or HttpxCaller()
    from app.market.independent_provider import resolve_credentials_safe
    creds, _ = resolve_credentials_safe("upstox")
    row = session.get(IntegrationCredential, "upstox")
    token = (creds or {}).get("access_token")
    if not token and (row is None or not row.ciphertext):
        return _finish(session, None, False, "NOT_CONFIGURED", "Upstox credentials are not saved.", provider="upstox")
    if row and not row.enabled:
        return _finish(session, row, False, "INTEGRATION_DISABLED", "Upstox is disabled. No request was sent.", provider="upstox")
    if not token and row and row.ciphertext:
        try:
            secrets = decrypt_secrets(settings, row.ciphertext)
            token = secrets.get("access_token")
        except SecretBoxError as exc:
            raise IntegrationError(exc.code, exc.message) from exc
    if not token:
        return _finish(session, row, False, "NOT_CONFIGURED", "Upstox access token missing.", provider="upstox")
    try:
        resp = caller.get("https://api.upstox.com/v2/user/profile", headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        ok = getattr(resp, "status_code", 0) == 200
        code = "CONNECTED" if ok else f"HTTP_{getattr(resp, 'status_code', 0)}"
        message = "Upstox connection test succeeded." if ok else f"Upstox profile test failed with status {getattr(resp, 'status_code', 0)}"
    except TimeoutError:
        ok, code, message = False, "TIMEOUT", "The Upstox request timed out. It was not retried."
    except Exception as exc:
        ok, code, message = False, "PROVIDER_ERROR", exc.__class__.__name__
    message = redact_text(message, [token])
    _safe_log(f"upstox connection test {code}", [token])
    return _finish(session, row, ok, code, message, provider="upstox")


def run_kite_test(session: Session, settings: Settings, caller=None) -> dict:
    caller = caller or HttpxCaller()
    from app.market.independent_provider import resolve_credentials_safe
    creds, _ = resolve_credentials_safe("kite")
    row = session.get(IntegrationCredential, "kite")
    api_key = (creds or {}).get("api_key")
    access_token = (creds or {}).get("access_token")
    if (not api_key or not access_token) and (row is None or not row.ciphertext):
        return _finish(session, None, False, "NOT_CONFIGURED", "Kite credentials are not saved.", provider="kite")
    if row and not row.enabled:
        return _finish(session, row, False, "INTEGRATION_DISABLED", "Kite is disabled. No request was sent.", provider="kite")
    if (not api_key or not access_token) and row and row.ciphertext:
        try:
            secrets = decrypt_secrets(settings, row.ciphertext)
            api_key = secrets.get("api_key")
            access_token = secrets.get("access_token")
        except SecretBoxError as exc:
            raise IntegrationError(exc.code, exc.message) from exc
    if not api_key or not access_token:
        return _finish(session, row, False, "NOT_CONFIGURED", "Kite api_key or access_token missing.", provider="kite")
    secrets_to_mask = [api_key, access_token]
    try:
        resp = caller.get(
            "https://api.kite.trade/user/profile",
            headers={"Authorization": f"token {api_key}:{access_token}", "X-Kite-Version": "3", "Accept": "application/json"},
        )
        ok = getattr(resp, "status_code", 0) == 200
        code = "CONNECTED" if ok else f"HTTP_{getattr(resp, 'status_code', 0)}"
        message = "Kite connection test succeeded." if ok else f"Kite profile test failed with status {getattr(resp, 'status_code', 0)}"
    except TimeoutError:
        ok, code, message = False, "TIMEOUT", "The Kite request timed out. It was not retried."
    except Exception as exc:
        ok, code, message = False, "PROVIDER_ERROR", exc.__class__.__name__
    message = redact_text(message, secrets_to_mask)
    _safe_log(f"kite connection test {code}", secrets_to_mask)
    return _finish(session, row, ok, code, message, provider="kite")


def run_angelone_test(session: Session, settings: Settings, caller=None) -> dict:
    caller = caller or HttpxCaller()
    from app.market.independent_provider import resolve_credentials_safe
    creds, _ = resolve_credentials_safe("angelone")
    row = session.get(IntegrationCredential, "angelone")
    api_key = (creds or {}).get("api_key")
    jwt_token = (creds or {}).get("jwt_token")
    if (not api_key or not jwt_token) and (row is None or not row.ciphertext):
        return _finish(session, None, False, "NOT_CONFIGURED", "Angel One credentials are not saved.", provider="angelone")
    if row and not row.enabled:
        return _finish(session, row, False, "INTEGRATION_DISABLED", "Angel One is disabled. No request was sent.", provider="angelone")
    if (not api_key or not jwt_token) and row and row.ciphertext:
        try:
            secrets = decrypt_secrets(settings, row.ciphertext)
            api_key = secrets.get("api_key")
            jwt_token = secrets.get("jwt_token")
        except SecretBoxError as exc:
            raise IntegrationError(exc.code, exc.message) from exc
    if not api_key or not jwt_token:
        return _finish(session, row, False, "NOT_CONFIGURED", "Angel One api_key or jwt_token missing.", provider="angelone")
    secrets_to_mask = [api_key, jwt_token]
    try:
        resp = caller.get(
            "https://apiconnect.angelbroking.com/rest/secure/angelbroking/user/v1/getProfile",
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "X-PrivateKey": api_key,
                "Accept": "application/json",
                "X-UserType": "USER",
                "X-SourceID": "WEB",
            },
        )
        ok = getattr(resp, "status_code", 0) == 200
        code = "CONNECTED" if ok else f"HTTP_{getattr(resp, 'status_code', 0)}"
        message = "Angel One connection test succeeded." if ok else f"Angel One profile test failed with status {getattr(resp, 'status_code', 0)}"
    except TimeoutError:
        ok, code, message = False, "TIMEOUT", "The Angel One request timed out. It was not retried."
    except Exception as exc:
        ok, code, message = False, "PROVIDER_ERROR", exc.__class__.__name__
    message = redact_text(message, secrets_to_mask)
    _safe_log(f"angelone connection test {code}", secrets_to_mask)
    return _finish(session, row, ok, code, message, provider="angelone")


def run_gemini_test(session: Session, settings: Settings, caller=None) -> dict:
    caller = caller or HttpxCaller()
    import os
    env_key = os.environ.get("GEMINI_API_KEY")
    row = session.get(IntegrationCredential, "gemini")
    api_key = env_key
    if not api_key and (row is None or not row.ciphertext):
        return _finish(session, None, False, "NOT_CONFIGURED", "Gemini credentials are not saved.", provider="gemini")
    if row and not row.enabled:
        return _finish(session, row, False, "INTEGRATION_DISABLED", "Gemini is disabled. No request was sent.", provider="gemini")
    if not api_key and row and row.ciphertext:
        try:
            secrets = decrypt_secrets(settings, row.ciphertext)
            api_key = secrets.get("api_key")
        except SecretBoxError as exc:
            raise IntegrationError(exc.code, exc.message) from exc
    model = (row.model if row and row.model else "gemini-2.5-flash")
    if not api_key:
        return _finish(session, row, False, "NOT_CONFIGURED", "Gemini API key is missing.", provider="gemini")
    secrets_to_mask = [api_key]
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
        if hasattr(caller, "get"):
            resp = caller.get(url, headers={"x-goog-api-key": api_key, "Accept": "application/json"})
        else:
            resp = caller.send("GET", url, headers={"x-goog-api-key": api_key, "Accept": "application/json"}, json_body=None, timeout=10.0)
        resp_status = getattr(resp, "status_code", 0)
        ok = resp_status == 200
        body = getattr(resp, "body", {})
        err_detail = ""
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            err_detail = body["error"].get("message") or ""
        if ok:
            code = "CONNECTED"
            message = f"Gemini model lookup succeeded ({model})."
        elif resp_status in {401, 403}:
            code = "AUTHENTICATION_FAILED"
            message = f"Gemini rejected the API key (HTTP {resp_status}): {err_detail}" if err_detail else f"Gemini rejected the API key (HTTP {resp_status})."
        elif resp_status == 404:
            code = "MODEL_UNAVAILABLE"
            message = f"Gemini model '{model}' not found or unavailable (HTTP 404). {err_detail}".strip()
        elif resp_status == 429:
            code = "RATE_LIMITED"
            message = f"Gemini rate limit or quota exceeded (HTTP 429): {err_detail}" if err_detail else "Gemini rate limit or quota exceeded (HTTP 429)."
        elif resp_status >= 500:
            code = "PROVIDER_UNAVAILABLE"
            message = f"Google Generative Language service unavailable (HTTP {resp_status})."
        else:
            code = f"HTTP_{resp_status}"
            message = f"Gemini model lookup failed ({resp_status}): {err_detail}" if err_detail else f"Gemini model lookup failed with status {resp_status}"
    except TimeoutError:
        ok, code, message = False, "TIMEOUT", "The Gemini request timed out. It was not retried."
    except Exception as exc:
        ok, code, message = False, "PROVIDER_ERROR", exc.__class__.__name__
    message = redact_text(message, secrets_to_mask)
    _safe_log(f"gemini connection test {code}", secrets_to_mask)
    return _finish(session, row, ok, code, message, provider="gemini")


def groww_read_token(session: Session, settings: Settings, caller=None) -> str:
    """Reuse the saved Groww token. Exchange once only when the documented rule requires it."""
    caller = caller or HttpxCaller()
    row = session.get(IntegrationCredential, "groww")
    if row is None or not row.ciphertext:
        raise IntegrationError("NOT_CONFIGURED", "Groww credentials are not saved.")
    try:
        secrets = decrypt_secrets(settings, row.ciphertext)
    except SecretBoxError as exc:
        raise IntegrationError(exc.code, exc.message) from exc
    token, expiry, exchanged = _groww_access_token(caller, row, secrets, datetime.now(timezone.utc))
    if exchanged:
        _store_derived_token(session, settings, row, secrets, token, expiry)
    return token


def _store_derived_token(session: Session, settings: Settings, row: IntegrationCredential, secrets: dict, token: str, expiry: str | None) -> None:
    secrets["access_token"] = token
    row.ciphertext = encrypt_secrets(settings, secrets)
    row.token_expiry = expiry
    row.derived_access_token = True
    row.updated_at = utcnow()
    session.flush()


def _groww_access_token(caller, row: IntegrationCredential, secrets: dict, now: datetime, force_exchange: bool = False) -> tuple[str, str | None, bool]:
    """Reuse a token only when its expiry is still in the future.

    An offset-less expiry is Asia/Kolkata. A past or malformed expiry does not
    start a token exchange for api_key_secret.
    For TOTP authentication, an expired token triggers an automatic renewal
    using the stored TOTP secret without requiring manual intervention.
    """
    method = row.auth_method or ""
    existing = secrets.get("access_token") or ""
    if method == "access_token":
        if not existing:
            raise GrowwCallError("NOT_CONFIGURED", "An access token is not saved.")
        if row.token_expiry:
            _require_reusable_expiry(row.token_expiry, now)
        return existing, None, False
    if method == "totp":
        if not force_exchange and row.token_expiry and existing:
            classified = classify_token_expiry(row.token_expiry, now)
            if classified["status"] == "VALID":
                return existing, row.token_expiry, False
            if classified["status"] == "UNVERIFIABLE":
                raise GrowwCallError(classified["code"], classified["message"])
            # When status is EXPIRED, auto-exchange a fresh token using stored TOTP secret
        updated, expiry = exchange_token(caller, secrets, method=method, now=now)
        return updated["access_token"], expiry, True
    if not force_exchange and (row.token_expiry and existing):
        _require_reusable_expiry(row.token_expiry, now)
        return existing, row.token_expiry, False
    updated, expiry = exchange_token(caller, secrets, method=method, now=now)
    return updated["access_token"], expiry, True


def _require_reusable_expiry(value: str, now: datetime) -> None:
    classified = classify_token_expiry(value, now)
    if classified["status"] != "VALID":
        raise GrowwCallError(classified["code"], classified["message"])


def _resolve_secret_field(val: object, existing_val: str | None, name: str) -> str:
    if isinstance(val, str) and ("•" in val or "\u2022" in val):
        if existing_val:
            return existing_val
    if isinstance(val, str) and val.strip():
        return _required(val, name)
    if existing_val:
        return existing_val
    return _required(val, name)


def _groww_secrets(method: str, body: dict, existing_secrets: dict | None = None) -> dict:
    existing_secrets = existing_secrets or {}
    if method == "access_token":
        return {"access_token": _resolve_secret_field(body.get("access_token"), existing_secrets.get("access_token"), "Access token")}
    if method == "api_key_secret":
        return {
            "api_key": _resolve_secret_field(body.get("api_key"), existing_secrets.get("api_key"), "API key"),
            "api_secret": _resolve_secret_field(body.get("api_secret"), existing_secrets.get("api_secret"), "API secret"),
        }
    return {
        "api_key": _resolve_secret_field(body.get("api_key"), existing_secrets.get("api_key"), "API key"),
        "totp_secret": _resolve_secret_field(body.get("totp_secret"), existing_secrets.get("totp_secret"), "TOTP secret"),
    }


def _lifecycle_state(row: IntegrationCredential | None) -> str:
    if row is None or not row.ciphertext:
        return "NOT_CONFIGURED"
    if not row.enabled:
        return "DISCONNECTED"
    now = datetime.now(timezone.utc)
    if row.provider == "groww" and row.auth_method in {"access_token", "api_key_secret"}:
        if row.token_expiry and classify_token_expiry(row.token_expiry, now)["status"] == "EXPIRED":
            return "EXPIRED_OR_REAUTH_REQUIRED"
    if row.last_test_ok is True:
        return "CONNECTED"
    if row.last_test_ok is False:
        return "CONNECTION_FAILED"
    return "CONFIGURED"


def _public_groww(row: IntegrationCredential | None) -> dict:
    flags = _flags(row)
    now = datetime.now(timezone.utc)
    expiry = None if row is None else row.token_expiry
    classified = classify_token_expiry(expiry, now)
    deadline = expiry_deadline(expiry)
    token_saved = bool(flags["access_token_configured"])
    reusable = classified["status"] == "VALID" and token_saved
    auth_verified = bool(row and (row.last_test_ok is True or row.last_test_code == "MARKET_DATA_REJECTED"))
    market_verified = bool(row and row.last_test_ok is True and row.last_test_code == "CONNECTED")
    connected = market_verified
    return {
        "provider": "groww",
        "auth_method": None if row is None else row.auth_method,
        "label": None if row is None else row.label,
        "configured": bool(row and row.ciphertext),
        "enabled": bool(row and row.enabled),
        "lifecycle_state": _lifecycle_state(row),
        **flags,
        "token_expiry": expiry,
        "token_status": {
            "status": classified["status"],
            "reason": classified["reason"],
            "display_ist": None if deadline is None else deadline.strftime("%Y-%m-%d %H:%M:%S IST"),
            "reusable": reusable,
            "refresh": False,
            "generation_required": not reusable,
            "message": classified["message"],
        },
        "token_expiry_note": (
            "The Groww API dashboard resets API keys daily at 6:00 AM IST. "
            "An offset-less expiry is read as Asia/Kolkata. A past expiry does not start a token exchange."
        ),
        "connection_test": "GET /v1/margins/detail/user + /v1/live-data/quote",
        "connectivity": {
            "last_result": "succeeded" if connected else "failed" if row and row.last_test_ok is False else "not_tested",
            "endpoint": "GET /v1/margins/detail/user + /v1/live-data/quote",
            "proves": (
                "The last margin read and market-data quote succeeded at the recorded time."
                if connected
                else "No successful verified connection is recorded."
            ),
            "does_not_prove": "A connection test does not prove historical candle access, order execution, or current charges.",
        },
        "capabilities": {
            "authentication": "verified" if auth_verified else "rejected" if row and row.last_test_ok is False else "not_tested",
            "market_data": "verified" if market_verified else "rejected" if row and row.last_test_ok is False else "not_tested",
            "historical_candles": "unverified",
        },
        "permissions": {
            "read_only_margin": "verified" if auth_verified else "not_tested" if not row or row.last_test_ok is None else "rejected",
            "market_data_quote": "verified" if market_verified else "not_tested" if not row or row.last_test_ok is None else "rejected",
            "historical_candles": "unverified",
            "live_trading": "disabled",
            "charges": "unknown",
            "charges_detail": "No charge schedule is stored. This application does not buy a subscription. A provider request can still be billed by Groww.",
        },
        "orders_used": False,
        "market_session": {
            "authoritative": False,
            "state": "UNKNOWN",
            "detail": "No authoritative exchange calendar is configured. This page does not say whether the market is open.",
        },
        **_test_fields(row),
    }


def _public_openai(row: IntegrationCredential | None) -> dict:
    import os
    env_configured = bool(os.environ.get("OPENAI_API_KEY"))
    configured = bool(row and row.ciphertext) or env_configured
    connected = bool(row and row.last_test_ok is True and row.last_test_code == "CONNECTED")
    lifecycle = _lifecycle_state(row) if row else ("CONFIGURED" if env_configured else "NOT_CONFIGURED")
    return {
        "provider": "openai",
        "enabled": bool(row and row.enabled) or (env_configured and (row is None or row.enabled)),
        "lifecycle_state": lifecycle,
        "model": (row.model if row and row.model else "gpt-4.1-mini"),
        "label": None if row is None else row.label,
        "configured": configured,
        "api_key_configured": configured,
        "connection_test": "GET /v1/models/{model}",
        "connectivity": {
            "endpoint": "GET /v1/models/{model}",
            "does_not_prove": "A model lookup does not request a completion, a forecast, or a broker action.",
        },
        "capabilities": {
            "model_lookup": "verified" if connected else "rejected" if row and row.last_test_ok is False else "not_tested",
        },
        "permissions": {
            "live_trading": "not_applicable",
            "charges": "unknown",
            "charges_detail": "Model-test success does not state the provider price. This page does not request a completion.",
        },
        **_test_fields(row),
    }


def _public_gemini(row: IntegrationCredential | None) -> dict:
    import os
    env_configured = bool(os.environ.get("GEMINI_API_KEY"))
    configured = bool(row and row.ciphertext) or env_configured
    connected = bool(row and row.last_test_ok is True and row.last_test_code == "CONNECTED")
    lifecycle = _lifecycle_state(row) if row else ("CONFIGURED" if env_configured else "NOT_CONFIGURED")
    return {
        "provider": "gemini",
        "enabled": bool(row and row.enabled),
        "lifecycle_state": lifecycle,
        "model": (row.model if row and row.model else "gemini-2.5-flash"),
        "label": None if row is None else row.label,
        "configured": configured,
        "api_key_configured": configured,
        "connection_test": "GET /v1beta/models/{model}",
        "connectivity": {
            "endpoint": "GET /v1beta/models/{model}",
            "does_not_prove": "A model lookup does not request a completion, a forecast, or a broker action.",
        },
        "capabilities": {
            "model_lookup": "verified" if connected else "rejected" if row and row.last_test_ok is False else "not_tested",
        },
        "permissions": {
            "live_trading": "not_applicable",
            "charges": "unknown",
            "charges_detail": "Model-test success does not state the provider price. This page does not request a completion.",
        },
        **_test_fields(row),
    }


def _public_upstox(row: IntegrationCredential | None) -> dict:
    import os
    env_configured = bool(os.environ.get("UPSTOX_ACCESS_TOKEN"))
    configured = bool(row and row.ciphertext) or env_configured
    lifecycle = _lifecycle_state(row) if row else ("CONFIGURED" if env_configured else "NOT_CONFIGURED")
    return {
        "provider": "upstox",
        "enabled": bool(row and row.enabled),
        "lifecycle_state": lifecycle,
        "label": None if row is None else row.label,
        "configured": configured,
        "access_token_configured": configured,
        "connection_test": "GET /v2/user/profile",
        "connectivity": {
            "endpoint": "GET /v2/user/profile",
            "proves": "The last Upstox profile read succeeded at the recorded time." if row and row.last_test_ok else "No successful Upstox read is recorded.",
            "does_not_prove": "A profile check does not prove full historical candle data coverage or order authorization.",
        },
        "permissions": {
            "historical_candles": "verified" if row and row.last_test_ok else "unverified",
            "live_trading": "disabled",
            "charges": "unknown",
        },
        **_test_fields(row),
    }


def _public_kite(row: IntegrationCredential | None) -> dict:
    import os
    env_configured = bool(os.environ.get("KITE_API_KEY") and os.environ.get("KITE_ACCESS_TOKEN"))
    configured = bool(row and row.ciphertext) or env_configured
    lifecycle = _lifecycle_state(row) if row else ("CONFIGURED" if env_configured else "NOT_CONFIGURED")
    return {
        "provider": "kite",
        "enabled": bool(row and row.enabled),
        "lifecycle_state": lifecycle,
        "label": None if row is None else row.label,
        "configured": configured,
        "api_key_configured": configured,
        "access_token_configured": configured,
        "connection_test": "GET /user/profile",
        "connectivity": {
            "endpoint": "GET /user/profile",
            "proves": "The last Kite profile read succeeded at the recorded time." if row and row.last_test_ok else "No successful Kite read is recorded.",
            "does_not_prove": "A profile check does not prove historical candle subscription or order permissions.",
        },
        "permissions": {
            "historical_candles": "verified" if row and row.last_test_ok else "unverified",
            "live_trading": "disabled",
            "charges": "unknown",
        },
        **_test_fields(row),
    }


def _public_angelone(row: IntegrationCredential | None) -> dict:
    import os
    env_configured = bool(os.environ.get("ANGELONE_API_KEY") and os.environ.get("ANGELONE_JWT_TOKEN"))
    configured = bool(row and row.ciphertext) or env_configured
    lifecycle = _lifecycle_state(row) if row else ("CONFIGURED" if env_configured else "NOT_CONFIGURED")
    return {
        "provider": "angelone",
        "enabled": bool(row and row.enabled),
        "lifecycle_state": lifecycle,
        "label": None if row is None else row.label,
        "configured": configured,
        "api_key_configured": configured,
        "client_code_configured": configured,
        "jwt_token_configured": configured,
        "connection_test": "GET /rest/secure/angelbroking/user/v1/getProfile",
        "connectivity": {
            "endpoint": "GET /rest/secure/angelbroking/user/v1/getProfile",
            "proves": "The last Angel One SmartAPI profile read succeeded at the recorded time." if row and row.last_test_ok else "No successful Angel One read is recorded.",
            "does_not_prove": "A profile check does not prove historical candle entitlement.",
        },
        "permissions": {
            "historical_candles": "verified" if row and row.last_test_ok else "unverified",
            "live_trading": "disabled",
            "charges": "unknown",
        },
        **_test_fields(row),
    }


def _public_indmoney() -> dict:
    from app.market.independent_provider import investigate_indmoney_support
    investigation = investigate_indmoney_support()
    return {
        "provider": "indmoney",
        "configured": False,
        "enabled": False,
        "status": investigation["status"],
        "operational": investigation["supported"],
        "finding": investigation["finding"],
        "connection_test": "NONE",
        "permissions": {
            "historical_candles": "blocked",
            "live_trading": "disabled",
        },
    }


def _public_nse_official() -> dict:
    from app.market.independent_provider import investigate_nse_official_support
    investigation = investigate_nse_official_support()
    return {
        "provider": "nse_official",
        "configured": False,
        "enabled": False,
        "status": investigation["status"],
        "operational": investigation["supported"],
        "finding": investigation["finding"],
        "connection_test": "NONE",
        "permissions": {
            "historical_candles": "limited_to_daily_eod",
            "live_trading": "disabled",
        },
    }


def _flags(row: IntegrationCredential | None) -> dict:
    if row is None or not row.auth_method:
        return {
            "api_key_configured": False,
            "api_secret_configured": False,
            "access_token_configured": False,
            "totp_secret_configured": False,
        }
    method = row.auth_method
    return {
        "api_key_configured": method in {"api_key_secret", "totp"},
        "api_secret_configured": method == "api_key_secret",
            "access_token_configured": method == "access_token" or bool(row.derived_access_token),
        "totp_secret_configured": method == "totp",
    }


def _test_fields(row: IntegrationCredential | None) -> dict:
    if row is None:
        return {"last_test_at": None, "last_test_ok": None, "last_test_code": None, "last_test_message": None}
    return {
        "last_test_at": None if row.last_test_at is None else row.last_test_at.isoformat(),
        "last_test_ok": row.last_test_ok,
        "last_test_code": row.last_test_code,
        "last_test_message": row.last_test_message,
    }


def _finish(session: Session, row: IntegrationCredential | None, ok: bool, code: str, message: str, *, provider: str) -> dict:
    if row is not None:
        row.last_test_at = utcnow()
        row.last_test_ok = ok
        row.last_test_code = code
        row.last_test_message = message[:300]
        row.updated_at = utcnow()
        session.flush()
    status = read_status(session)
    status["result"] = {"provider": provider, "ok": ok, "code": code, "message": message}
    return status


def _row(session: Session, provider: str) -> IntegrationCredential:
    row = session.get(IntegrationCredential, provider)
    if row is None:
        row = IntegrationCredential(
            provider=provider,
            enabled=False,
            derived_access_token=False,
            updated_at=utcnow(),
        )
        session.add(row)
    return row


def _clear_test(row: IntegrationCredential) -> None:
    row.last_test_at = None
    row.last_test_ok = None
    row.last_test_code = None
    row.last_test_message = None


def _required(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntegrationError("MISSING_CREDENTIAL", f"{name} is required for this method.")
    if len(value) > 4096:
        raise IntegrationError("INVALID_CREDENTIAL", f"{name} is too long.")
    return value.strip()


def _label(value: str) -> str:
    if not isinstance(value, str) or not LABEL_RE.fullmatch(value):
        raise IntegrationError("INVALID_LABEL", "The label may contain letters, digits, spaces, dots, underscores, and hyphens.")
    return value.strip()


def _model(value: str) -> str:
    if not MODEL_RE.fullmatch(value):
        raise IntegrationError("INVALID_MODEL", "Enter a model id using letters, digits, and . _ : -.")
    return value


def _safe_log(message: str, secrets: list[str]) -> None:
    log.info("%s", redact_text(message, secrets))


DEFAULT_OPENAI_MODELS = [
    {"id": "gpt-4o", "label": "gpt-4o (Omni Flagship · High Intelligence)", "recommended": True},
    {"id": "gpt-4o-mini", "label": "gpt-4o-mini (Fast & Cost Efficient)", "recommended": True},
    {"id": "o1", "label": "o1 (Deep Reasoning & Complex Analysis)", "recommended": True},
    {"id": "o1-mini", "label": "o1-mini (Fast Reasoning)", "recommended": False},
    {"id": "o1-preview", "label": "o1-preview (Advanced Reasoning Preview)", "recommended": False},
    {"id": "gpt-4-turbo", "label": "gpt-4-turbo (High Capability)", "recommended": False},
    {"id": "gpt-4", "label": "gpt-4 (Legacy Baseline)", "recommended": False},
    {"id": "gpt-3.5-turbo", "label": "gpt-3.5-turbo (Legacy Speed)", "recommended": False},
]

DEFAULT_GEMINI_MODELS = [
    {"id": "gemini-2.5-pro", "label": "gemini-2.5-pro (Flagship Reasoning & Code)", "recommended": True},
    {"id": "gemini-2.5-flash", "label": "gemini-2.5-flash (Fast, Highly Capable)", "recommended": True},
    {"id": "gemini-2.0-flash", "label": "gemini-2.0-flash (High-Speed Multimodal)", "recommended": True},
    {"id": "gemini-2.0-flash-lite", "label": "gemini-2.0-flash-lite (Ultra Lightweight)", "recommended": False},
    {"id": "gemini-1.5-pro", "label": "gemini-1.5-pro (Long Context)", "recommended": False},
    {"id": "gemini-1.5-flash", "label": "gemini-1.5-flash (Legacy Fast)", "recommended": False},
    {"id": "gemini-1.5-flash-8b", "label": "gemini-1.5-flash-8b (High Volume / Low Cost)", "recommended": False},
]


def get_available_openai_models(session: Session, settings: Settings, draft_api_key: str | None = None, caller=None) -> dict:
    caller = caller or HttpxCaller()
    api_key = (draft_api_key or "").strip()
    if not api_key or "•" in api_key:
        row = session.get(IntegrationCredential, "openai")
        if row and row.ciphertext:
            try:
                secrets = decrypt_secrets(settings, row.ciphertext)
                api_key = (secrets.get("api_key") or "").strip()
            except Exception:
                pass
    if not api_key:
        import os
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if not api_key:
        return {
            "ok": False,
            "source": "catalog",
            "models": DEFAULT_OPENAI_MODELS,
            "message": "Enter an API key to query live models available on your OpenAI account.",
        }

    try:
        resp = list_models(caller, api_key=api_key)
        status = getattr(resp, "status_code", 0)
        if status != 200:
            return {
                "ok": False,
                "source": "catalog",
                "models": DEFAULT_OPENAI_MODELS,
                "message": f"OpenAI returned HTTP {status}. Showing standard catalog.",
            }
        body = getattr(resp, "body", {})
        data = body.get("data", []) if isinstance(body, dict) else []

        excluded = {"audio", "realtime", "whisper", "tts", "dall-e", "embedding", "transcription", "moderation", "davinci", "babbage", "curie", "ada", "search", "similarity"}
        chat_models = []
        for item in data:
            if not isinstance(item, dict):
                continue
            mid = item.get("id", "")
            if not mid:
                continue
            lowered = mid.lower()
            if any(p in lowered for p in excluded):
                continue
            if lowered.startswith("gpt-") or lowered.startswith("o1") or lowered.startswith("o3") or lowered.startswith("chatgpt"):
                chat_models.append(mid)

        priority = {
            "gpt-4o": 1,
            "gpt-4o-mini": 2,
            "o1": 3,
            "o1-mini": 4,
            "o1-preview": 5,
            "gpt-4-turbo": 6,
            "gpt-4": 7,
            "gpt-3.5-turbo": 8,
        }
        chat_models = list(dict.fromkeys(chat_models))
        chat_models.sort(key=lambda m: (priority.get(m, 99), m))

        result_models = []
        for mid in chat_models:
            is_rec = mid in {"gpt-4o", "gpt-4o-mini", "o1", "o1-mini"}
            desc = "Flagship Omni" if mid == "gpt-4o" else "Fast & Efficient" if mid == "gpt-4o-mini" else "Deep Reasoning" if mid == "o1" else ""
            label = f"{mid} ({desc})" if desc else mid
            result_models.append({"id": mid, "label": label, "recommended": is_rec})

        if not result_models:
            result_models = DEFAULT_OPENAI_MODELS

        return {
            "ok": True,
            "source": "live",
            "models": result_models,
            "message": f"Successfully loaded {len(result_models)} live models from OpenAI API.",
        }
    except Exception as exc:
        return {
            "ok": False,
            "source": "catalog",
            "models": DEFAULT_OPENAI_MODELS,
            "message": f"Error querying OpenAI models: {exc}. Showing standard catalog.",
        }


def get_available_gemini_models(session: Session, settings: Settings, draft_api_key: str | None = None, caller=None) -> dict:
    caller = caller or HttpxCaller()
    api_key = (draft_api_key or "").strip()
    if not api_key or "•" in api_key:
        row = session.get(IntegrationCredential, "gemini")
        if row and row.ciphertext:
            try:
                secrets = decrypt_secrets(settings, row.ciphertext)
                api_key = (secrets.get("api_key") or "").strip()
            except Exception:
                pass
    if not api_key:
        import os
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()

    if not api_key:
        return {
            "ok": False,
            "source": "catalog",
            "models": DEFAULT_GEMINI_MODELS,
            "message": "Enter an API key to query live models available on Google AI.",
        }

    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models"
        if hasattr(caller, "get"):
            resp = caller.get(url, headers={"x-goog-api-key": api_key, "Accept": "application/json"})
        else:
            resp = caller.send("GET", url, headers={"x-goog-api-key": api_key, "Accept": "application/json"}, json_body=None, timeout=10.0)

        status = getattr(resp, "status_code", 0)
        if status != 200:
            return {
                "ok": False,
                "source": "catalog",
                "models": DEFAULT_GEMINI_MODELS,
                "message": f"Google AI returned HTTP {status}. Showing standard catalog.",
            }
        body = getattr(resp, "body", {})
        models_raw = body.get("models", []) if isinstance(body, dict) else []

        parsed_models = []
        for m in models_raw:
            if not isinstance(m, dict):
                continue
            methods = m.get("supportedGenerationMethods", [])
            if "generateContent" not in methods:
                continue
            name = m.get("name", "")
            if name.startswith("models/"):
                mid = name[len("models/"):]
            else:
                mid = name
            if not mid:
                continue
            disp = m.get("displayName") or mid
            parsed_models.append({
                "id": mid,
                "displayName": disp,
            })

        priority = {
            "gemini-2.5-pro": 1,
            "gemini-2.5-flash": 2,
            "gemini-2.0-flash": 3,
            "gemini-2.0-flash-lite": 4,
            "gemini-1.5-pro": 5,
            "gemini-1.5-flash": 6,
            "gemini-1.5-flash-8b": 7,
        }
        parsed_models.sort(key=lambda m: (priority.get(m["id"], 99), m["id"]))

        result_models = []
        for m in parsed_models:
            mid = m["id"]
            is_rec = mid in {"gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"}
            label = f"{mid} ({m['displayName']})" if m["displayName"] and m["displayName"] != mid else mid
            result_models.append({"id": mid, "label": label, "recommended": is_rec})

        if not result_models:
            result_models = DEFAULT_GEMINI_MODELS

        return {
            "ok": True,
            "source": "live",
            "models": result_models,
            "message": f"Successfully loaded {len(result_models)} live models from Google Gemini API.",
        }
    except Exception as exc:
        return {
            "ok": False,
            "source": "catalog",
            "models": DEFAULT_GEMINI_MODELS,
            "message": f"Error querying Gemini models: {exc}. Showing standard catalog.",
        }
