"""Session-protected integration settings. Responses omit secret values."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.auth import read_session, require_csrf
from app.db import get_session_factory
from app.domain.tables import AuditEvent, IntegrationCredential
from app.errors import AppError
from app.integrations.crypto import SecretBoxError
from app.integrations.http import HttpxCaller
from app.integrations.service import (
    IntegrationError,
    clear_provider,
    disconnect_provider,
    get_available_gemini_models,
    get_available_openai_models,
    read_status,
    save_angelone,
    save_gemini,
    save_groww,
    save_kite,
    save_openai,
    save_upstox,
    set_gemini_profile,
    set_groww_enabled,
    set_openai_enabled,
    set_openai_profile,
    set_provider_enabled,
    set_provider_profile,
    run_angelone_test,
    run_gemini_test,
    run_groww_test,
    run_kite_test,
    run_openai_test,
    run_upstox_test,
)
from app.market.history import HistoryStoreError, history_store
from app.market.minute_diagnostic import minute_query, run_minute_diagnostic
from app.market.quarantine_validation import validate_quarantine_payload
from app.market.retrieval import QuarantineStore
from app.market.schemas import IST
from app.settings import Settings, get_settings

router = APIRouter()
_STATUS = {
    "SECRET_KEY_UNCONFIGURED": 503,
    "SECRET_KEY_INVALID": 503,
    "SECRET_KEY_MISMATCH": 503,
}


class GrowwBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["access_token", "api_key_secret", "totp"]
    label: str = ""
    api_key: str | None = None
    api_secret: str | None = None
    access_token: str | None = None
    totp_secret: str | None = None


class ModelsQueryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: str | None = None


class OpenAIBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: str
    model: str
    label: str = ""
    enabled: bool = False


class UpstoxBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_token: str
    label: str = ""
    enabled: bool = False


class KiteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: str
    access_token: str
    label: str = ""
    enabled: bool = False


class AngelOneBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: str
    client_code: str
    jwt_token: str
    label: str = ""
    enabled: bool = False


class GeminiBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: str
    model: str = "gemini-2.5-flash"
    label: str = ""
    enabled: bool = False


class GeminiProfileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    label: str = ""
    confirm: bool = False


class EnabledBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    confirm: bool = False


class OpenAIProfileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    label: str = ""
    confirm: bool = False


class ProfileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = ""
    confirm: bool = False


class GrowwDiagnosticBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exchange: Literal["NSE"]
    segment: Literal["CASH"]
    groww_symbol: Literal["NSE-NIFTY"]
    candle_interval: Literal["1minute"]
    start: datetime
    end: datetime
    confirm: bool = False


def _settings() -> Settings:
    return get_settings()


def get_db() -> Session:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _fail(exc: Exception) -> None:
    if isinstance(exc, (IntegrationError, SecretBoxError)):
        raise AppError(exc.code, exc.message, _STATUS.get(exc.code, 422)) from exc
    raise exc


def _audit(session: Session, actor: str, action: str, entity: str, after: dict) -> None:
    session.add(AuditEvent(actor=actor, action=action, entity=entity, before=None, after=after))


@router.get("/api/integrations")
def get_integrations(request: Request, session: Session = Depends(get_db), settings: Settings = Depends(_settings)) -> dict:
    read_session(request, settings)
    return read_status(session)


@router.put("/api/integrations/groww")
def put_groww(
    body: GrowwBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    try:
        status = save_groww(session, settings, body.model_dump())
    except (IntegrationError, SecretBoxError) as exc:
        _fail(exc)
    _audit(session, principal.get("sub", "operator"), "integrations.groww.save", "groww", {"method": body.method, "configured": True})
    return status


@router.post("/api/integrations/groww/clear")
def post_groww_clear(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    status = clear_provider(session, "groww")
    _audit(session, principal.get("sub", "operator"), "integrations.groww.clear", "groww", {"configured": False})
    return status


@router.post("/api/integrations/groww/disconnect")
def post_groww_disconnect(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    try:
        status = disconnect_provider(session, "groww")
    except IntegrationError as exc:
        _fail(exc)
    _audit(session, principal.get("sub", "operator"), "integrations.groww.disconnect", "groww", {"enabled": False})
    return status


@router.post("/api/integrations/groww/enabled")
def post_groww_enabled(
    body: EnabledBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    before = session.get(IntegrationCredential, "groww")
    enabled_before = None if before is None else before.enabled
    try:
        status = set_groww_enabled(session, body.enabled, confirm=body.confirm)
    except IntegrationError as exc:
        _fail(exc)
    _audit(
        session,
        principal.get("sub", "operator"),
        "integrations.groww.enabled",
        "groww",
        {"enabled": body.enabled, "confirm": True, "live_trading_enabled": False},
    )
    status["live_trading_enabled"] = False
    status["enabled_before"] = enabled_before
    return status


@router.post("/api/integrations/groww/historical-diagnostic")
def post_groww_diagnostic(
    body: GrowwDiagnosticBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> JSONResponse:
    """Run one read-only candle GET only after confirm is true.

    Opening this route without confirm does not call Groww. A confirmed request
    does not change integration enablement or live trading.
    """
    require_csrf(request, settings)
    row = session.get(IntegrationCredential, "groww")
    enabled_before = None if row is None else bool(row.enabled)
    parameters = {
        "exchange": body.exchange,
        "segment": body.segment,
        "groww_symbol": body.groww_symbol,
        "candle_interval": body.candle_interval,
    }
    try:
        query = minute_query(body.start, body.end, parameters)
    except HistoryStoreError as exc:
        return _diagnostic_response(_local_diagnostic(exc.code, f"Request rejected locally before any network call. {exc.message}"), 422)
    if body.confirm is not True:
        preview = _local_diagnostic(
            "CONFIRMATION_REQUIRED",
            "Request rejected locally before any network call. Confirm this exact one-time read-only diagnostic before it can run.",
        )
        preview["query"] = query
        preview["integration_enabled"] = enabled_before
        return _diagnostic_response(preview, 422)
    result = run_minute_diagnostic(
        session,
        settings,
        body.start,
        body.end,
        caller=diagnostic_caller(),
        quarantine=diagnostic_store(),
        retrieved_at=datetime.now(IST),
        parameters=parameters,
        one_shot_authorized=False,
    )
    result["enabled_before"] = enabled_before
    result["enabled_after"] = None if row is None else bool(row.enabled)
    result["live_trading_enabled"] = False
    result["error_origin"] = "local" if result["network_calls"] == 0 else "provider"
    if result["quarantine"]:
        saved = diagnostic_store().read(result["quarantine"][0]["quarantine_id"])
        validation = validate_quarantine_payload(saved)
        result["report"] = {
            "http_status": saved.get("http_status"),
            "provider_status": saved.get("provider_status"),
            "candle_count": saved.get("candle_count"),
            "first_raw_timestamp": saved.get("first_raw_timestamp"),
            "last_raw_timestamp": saved.get("last_raw_timestamp"),
            "requested_start_sent": saved.get("requested_start_sent"),
            "requested_end_sent": saved.get("requested_end_sent"),
            "label": saved.get("label"),
            "trusted_dataset_created": False,
            "real_market_data_verified": False,
            "unresolved": [
                "timestamp timezone",
                "candle start or end",
                "request-boundary inclusivity",
                "session open and close candles",
                "incomplete-candle behaviour",
            ],
            "validation_passed": [item["id"] for item in validation["passed"]],
            "validation_failed": [item["id"] for item in validation["failed"]],
            "validation_undetermined": [item["id"] for item in validation["undetermined"]],
        }
    result["message"] = _diagnostic_message(result["code"], result["message"])
    status = 200 if result["code"] == "CANDLE_BOUNDARY_UNVERIFIED" else 422
    return _diagnostic_response(result, status)


_DIAGNOSTIC_MESSAGES = {
    "TOKEN_EXPIRED": "Token expired: reauthentication is required. No automatic refresh was attempted.",
    "EXPIRY_UNVERIFIABLE": "Token expiry unverifiable: timezone or expiry information is missing. No token was generated.",
    "AUTHENTICATION_FAILED": "Authentication rejected by provider.",
    "CANDLE_BOUNDARY_UNVERIFIED": "Response received but quarantined because timestamp semantics are unverified.",
    "UNSUPPORTED_QUERY": "Endpoint or interval unsupported. The request was rejected locally.",
    "INVALID_RANGE": "Request rejected locally before any network call.",
    "RANGE_TOO_LONG": "Request rejected locally before any network call. The one-minute diagnostic accepts at most 30 minutes.",
}


def _diagnostic_message(code: str, fallback: str) -> str:
    return _DIAGNOSTIC_MESSAGES.get(code, fallback)


def diagnostic_caller():
    return HttpxCaller()


def diagnostic_store() -> QuarantineStore:
    return QuarantineStore(history_store().root / "quarantine")


def _local_diagnostic(code: str, message: str) -> dict:
    return {
        "ok": False,
        "code": code,
        "message": message,
        "error_origin": "local",
        "network_calls": 0,
        "retry": False,
        "token_refreshed": False,
        "enabled_changed": False,
        "live_trading_enabled": False,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
        "trusted_dataset_created": False,
        "candles": [],
        "quarantine": [],
    }


def _diagnostic_response(result: dict, status: int) -> JSONResponse:
    return JSONResponse(status_code=status, content=result)


@router.post("/api/integrations/groww/test")
def post_groww_test(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    require_csrf(request, settings)
    try:
        status = run_groww_test(session, settings)
    except (IntegrationError, SecretBoxError) as exc:
        _fail(exc)
    return _test_response(status)


@router.put("/api/integrations/openai")
def put_openai(
    body: OpenAIBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    try:
        status = save_openai(session, settings, body.model_dump())
    except (IntegrationError, SecretBoxError) as exc:
        _fail(exc)
    _audit(
        session,
        principal.get("sub", "operator"),
        "integrations.openai.save",
        "openai",
        {"model": body.model, "enabled": body.enabled, "configured": True},
    )
    return status


@router.post("/api/integrations/openai/clear")
def post_openai_clear(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    status = clear_provider(session, "openai")
    _audit(session, principal.get("sub", "operator"), "integrations.openai.clear", "openai", {"configured": False})
    return status


@router.post("/api/integrations/openai/disconnect")
def post_openai_disconnect(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    try:
        status = disconnect_provider(session, "openai")
    except IntegrationError as exc:
        _fail(exc)
    _audit(session, principal.get("sub", "operator"), "integrations.openai.disconnect", "openai", {"enabled": False})
    return status


@router.post("/api/integrations/openai/enabled")
def post_openai_enabled(
    body: EnabledBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    if body.confirm is not True:
        raise AppError("CONFIRMATION_REQUIRED", "Changing OpenAI enablement needs an explicit confirmation. The setting was not changed.", 422)
    try:
        status = set_openai_enabled(session, body.enabled)
    except IntegrationError as exc:
        _fail(exc)
    _audit(
        session,
        principal.get("sub", "operator"),
        "integrations.openai.enabled",
        "openai",
        {"enabled": body.enabled},
    )
    return status


@router.post("/api/integrations/openai/profile")
def post_openai_profile(
    body: OpenAIProfileBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    try:
        status = set_openai_profile(session, body.model, body.label, confirm=body.confirm)
    except IntegrationError as exc:
        _fail(exc)
    _audit(
        session,
        principal.get("sub", "operator"),
        "integrations.openai.profile",
        "openai",
        {"model": body.model, "confirm": True},
    )
    return status


@router.post("/api/integrations/openai/test")
def post_openai_test(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    require_csrf(request, settings)
    try:
        status = run_openai_test(session, settings)
    except (IntegrationError, SecretBoxError) as exc:
        _fail(exc)
    return _test_response(status)


@router.post("/api/integrations/openai/models")
def post_openai_models(
    body: ModelsQueryBody = ModelsQueryBody(),
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    return get_available_openai_models(session, settings, draft_api_key=body.api_key)


# ----------------------------------------------------------------------
# UPSTOX ROUTES
# ----------------------------------------------------------------------
@router.put("/api/integrations/upstox")
def put_upstox(
    body: UpstoxBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    try:
        status = save_upstox(session, settings, body.model_dump())
    except (IntegrationError, SecretBoxError) as exc:
        _fail(exc)
    _audit(session, principal.get("sub", "operator"), "integrations.upstox.save", "upstox", {"configured": True})
    return status


@router.post("/api/integrations/upstox/clear")
def post_upstox_clear(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    status = clear_provider(session, "upstox")
    _audit(session, principal.get("sub", "operator"), "integrations.upstox.clear", "upstox", {"configured": False})
    return status


@router.post("/api/integrations/upstox/enabled")
def post_upstox_enabled(
    body: EnabledBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    if body.confirm is not True:
        raise AppError("CONFIRMATION_REQUIRED", "Changing Upstox enablement needs an explicit confirmation.", 422)
    try:
        status = set_provider_enabled(session, "upstox", body.enabled)
    except IntegrationError as exc:
        _fail(exc)
    _audit(session, principal.get("sub", "operator"), "integrations.upstox.enabled", "upstox", {"enabled": body.enabled})
    return status


@router.post("/api/integrations/upstox/profile")
def post_upstox_profile(
    body: ProfileBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    try:
        status = set_provider_profile(session, "upstox", body.label, confirm=body.confirm)
    except IntegrationError as exc:
        _fail(exc)
    _audit(session, principal.get("sub", "operator"), "integrations.upstox.profile", "upstox", {"label": body.label})
    return status


@router.post("/api/integrations/upstox/test")
def post_upstox_test(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    require_csrf(request, settings)
    try:
        status = run_upstox_test(session, settings)
    except (IntegrationError, SecretBoxError) as exc:
        _fail(exc)
    return _test_response(status)


# ----------------------------------------------------------------------
# KITE CONNECT ROUTES
# ----------------------------------------------------------------------
@router.put("/api/integrations/kite")
def put_kite(
    body: KiteBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    try:
        status = save_kite(session, settings, body.model_dump())
    except (IntegrationError, SecretBoxError) as exc:
        _fail(exc)
    _audit(session, principal.get("sub", "operator"), "integrations.kite.save", "kite", {"configured": True})
    return status


@router.post("/api/integrations/kite/profile")
def post_kite_profile(
    body: ProfileBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    try:
        status = set_provider_profile(session, "kite", body.label, confirm=body.confirm)
    except IntegrationError as exc:
        _fail(exc)
    _audit(session, principal.get("sub", "operator"), "integrations.kite.profile", "kite", {"label": body.label})
    return status


@router.post("/api/integrations/kite/clear")
def post_kite_clear(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    status = clear_provider(session, "kite")
    _audit(session, principal.get("sub", "operator"), "integrations.kite.clear", "kite", {"configured": False})
    return status


@router.post("/api/integrations/kite/enabled")
def post_kite_enabled(
    body: EnabledBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    if body.confirm is not True:
        raise AppError("CONFIRMATION_REQUIRED", "Changing Kite enablement needs an explicit confirmation.", 422)
    try:
        status = set_provider_enabled(session, "kite", body.enabled)
    except IntegrationError as exc:
        _fail(exc)
    _audit(session, principal.get("sub", "operator"), "integrations.kite.enabled", "kite", {"enabled": body.enabled})
    return status


@router.post("/api/integrations/kite/test")
def post_kite_test(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    require_csrf(request, settings)
    try:
        status = run_kite_test(session, settings)
    except (IntegrationError, SecretBoxError) as exc:
        _fail(exc)
    return _test_response(status)


# ----------------------------------------------------------------------
# ANGEL ONE SMARTAPI ROUTES
# ----------------------------------------------------------------------
@router.put("/api/integrations/angelone")
def put_angelone(
    body: AngelOneBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    try:
        status = save_angelone(session, settings, body.model_dump())
    except (IntegrationError, SecretBoxError) as exc:
        _fail(exc)
    _audit(session, principal.get("sub", "operator"), "integrations.angelone.save", "angelone", {"configured": True})
    return status


@router.post("/api/integrations/angelone/profile")
def post_angelone_profile(
    body: ProfileBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    try:
        status = set_provider_profile(session, "angelone", body.label, confirm=body.confirm)
    except IntegrationError as exc:
        _fail(exc)
    _audit(session, principal.get("sub", "operator"), "integrations.angelone.profile", "angelone", {"label": body.label})
    return status


@router.post("/api/integrations/angelone/clear")
def post_angelone_clear(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    status = clear_provider(session, "angelone")
    _audit(session, principal.get("sub", "operator"), "integrations.angelone.clear", "angelone", {"configured": False})
    return status


@router.post("/api/integrations/angelone/enabled")
def post_angelone_enabled(
    body: EnabledBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    if body.confirm is not True:
        raise AppError("CONFIRMATION_REQUIRED", "Changing Angel One enablement needs an explicit confirmation.", 422)
    try:
        status = set_provider_enabled(session, "angelone", body.enabled)
    except IntegrationError as exc:
        _fail(exc)
    _audit(session, principal.get("sub", "operator"), "integrations.angelone.enabled", "angelone", {"enabled": body.enabled})
    return status


@router.post("/api/integrations/angelone/test")
def post_angelone_test(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    require_csrf(request, settings)
    try:
        status = run_angelone_test(session, settings)
    except (IntegrationError, SecretBoxError) as exc:
        _fail(exc)
    return _test_response(status)


# ----------------------------------------------------------------------
# GOOGLE GEMINI ROUTES
# ----------------------------------------------------------------------
@router.put("/api/integrations/gemini")
def put_gemini(
    body: GeminiBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    try:
        status = save_gemini(session, settings, body.model_dump())
    except (IntegrationError, SecretBoxError) as exc:
        _fail(exc)
    _audit(session, principal.get("sub", "operator"), "integrations.gemini.save", "gemini", {"configured": True, "model": body.model})
    return status


@router.post("/api/integrations/gemini/clear")
def post_gemini_clear(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    status = clear_provider(session, "gemini")
    _audit(session, principal.get("sub", "operator"), "integrations.gemini.clear", "gemini", {"configured": False})
    return status


@router.post("/api/integrations/gemini/disconnect")
def post_gemini_disconnect(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    try:
        status = disconnect_provider(session, "gemini")
    except IntegrationError as exc:
        _fail(exc)
    _audit(session, principal.get("sub", "operator"), "integrations.gemini.disconnect", "gemini", {"enabled": False})
    return status


@router.post("/api/integrations/{provider}/disconnect")
def post_provider_disconnect(
    provider: str,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    try:
        status = disconnect_provider(session, provider)
    except IntegrationError as exc:
        _fail(exc)
    _audit(session, principal.get("sub", "operator"), f"integrations.{provider}.disconnect", provider, {"enabled": False})
    return status


@router.post("/api/integrations/gemini/enabled")
def post_gemini_enabled(
    body: EnabledBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    if body.confirm is not True:
        raise AppError("CONFIRMATION_REQUIRED", "Changing Gemini enablement needs an explicit confirmation.", 422)
    try:
        status = set_provider_enabled(session, "gemini", body.enabled)
    except IntegrationError as exc:
        _fail(exc)
    _audit(session, principal.get("sub", "operator"), "integrations.gemini.enabled", "gemini", {"enabled": body.enabled})
    return status


@router.post("/api/integrations/gemini/profile")
def post_gemini_profile(
    body: GeminiProfileBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    try:
        status = set_gemini_profile(session, body.model, body.label, confirm=body.confirm)
    except IntegrationError as exc:
        _fail(exc)
    _audit(session, principal.get("sub", "operator"), "integrations.gemini.profile", "gemini", {"model": body.model, "confirm": True})
    return status


@router.post("/api/integrations/gemini/test")
def post_gemini_test(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    require_csrf(request, settings)
    try:
        status = run_gemini_test(session, settings)
    except (IntegrationError, SecretBoxError) as exc:
        _fail(exc)
    return _test_response(status)


@router.post("/api/integrations/gemini/models")
def post_gemini_models(
    body: ModelsQueryBody = ModelsQueryBody(),
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    return get_available_gemini_models(session, settings, draft_api_key=body.api_key)


# ----------------------------------------------------------------------
# INDMONEY & NSE OFFICIAL STATUS
# ----------------------------------------------------------------------
@router.get("/api/integrations/indmoney")
def get_indmoney_status(request: Request, settings: Settings = Depends(_settings)) -> dict:
    read_session(request, settings)
    from app.market.independent_provider import investigate_indmoney_support
    return investigate_indmoney_support()


@router.get("/api/integrations/nse")
def get_nse_status(request: Request, settings: Settings = Depends(_settings)) -> dict:
    read_session(request, settings)
    from app.market.independent_provider import investigate_nse_official_support
    return investigate_nse_official_support()


def _test_response(status: dict) -> JSONResponse:
    ok = bool((status.get("result") or {}).get("ok"))
    return JSONResponse(status_code=200 if ok else 422, content=status)
