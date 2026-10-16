"""Read-only one-minute Groww candle diagnostic.

This module is separate from the M15 importer. It does not enable an
integration, exchange a token, retry a request, or store trusted candles.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.domain.tables import IntegrationCredential
from app.integrations.crypto import SecretBoxError, decrypt_secrets
from app.integrations.groww import classify_token_expiry, read_historical_candles
from app.integrations.http import CANDLE_QUERY
from app.market.history import HistoryStoreError
from app.market.retrieval import QUARANTINE_SCHEMA, classify_historical_response
from app.security.redact import redact_text
from app.settings import Settings

log = logging.getLogger("imm.market.minute_diagnostic")

DIAGNOSTIC_INTERVAL = "1minute"
NARROW_LIMIT = timedelta(minutes=30)
FIXED_QUERY = {
    "exchange": "NSE",
    "segment": "CASH",
    "groww_symbol": "NSE-NIFTY",
    "candle_interval": DIAGNOSTIC_INTERVAL,
}


def minute_query(start: datetime, end: datetime, parameters: dict | None = None) -> dict[str, str]:
    """Build the only query this diagnostic can send."""
    start = _aware(start, "start")
    end = _aware(end, "end")
    if end <= start:
        raise HistoryStoreError("INVALID_RANGE", "The end must be after the start.")
    if end - start > NARROW_LIMIT:
        raise HistoryStoreError(
            "RANGE_TOO_LONG",
            "The one-minute diagnostic accepts at most 30 minutes. That cap is local and is not the provider's 30-day limit.",
        )
    supplied = dict(parameters or {})
    unknown = set(supplied) - set(CANDLE_QUERY)
    if unknown:
        raise HistoryStoreError("UNSUPPORTED_QUERY", "The diagnostic accepts only the documented candle query fields.")
    for key, expected in FIXED_QUERY.items():
        if key in supplied and supplied[key] != expected:
            raise HistoryStoreError("UNSUPPORTED_QUERY", f"{key} is fixed for this diagnostic.")
    query = {
        **FIXED_QUERY,
        "start_time": _wire_clock(start),
        "end_time": _wire_clock(end),
    }
    for key in ("start_time", "end_time"):
        if key in supplied and supplied[key] != query[key]:
            raise HistoryStoreError("UNSUPPORTED_QUERY", f"{key} must match the supplied range.")
    if set(query) != set(CANDLE_QUERY):
        raise HistoryStoreError("UNSUPPORTED_QUERY", "The candle query fields are incomplete.")
    return query


def run_minute_diagnostic(
    session: Session,
    settings: Settings,
    start: datetime,
    end: datetime,
    *,
    caller,
    quarantine,
    retrieved_at: datetime,
    parameters: dict | None = None,
    one_shot_authorized: bool = False,
) -> dict:
    """Send at most one candle GET when expiry allows it.

    A disabled integration does not send a request and is not enabled by this
    call. An unverifiable or past expiry returns before any token exchange.
    """
    query = minute_query(start, end, parameters)
    retrieved_at = _aware(retrieved_at, "retrieved_at")
    result = _base(query)
    row = session.get(IntegrationCredential, "groww")
    if row is None or not row.ciphertext:
        return _finish(result, "NOT_CONFIGURED", "Groww credentials are not saved. No request was sent.")
    if row.enabled is not True:
        return _finish(
            result,
            "INTEGRATION_DISABLED",
            "Integration disabled: enable Groww from its configuration before a historical diagnostic can run. No request was sent.",
        )
    result["one_shot_authorized"] = one_shot_authorized is True
    result["integration_enabled"] = row.enabled is True
    classified = classify_token_expiry(row.token_expiry, retrieved_at)
    if classified["status"] != "VALID":
        return _finish(result, classified["code"], classified["message"])
    try:
        secrets = decrypt_secrets(settings, row.ciphertext)
    except SecretBoxError as exc:
        return _finish(result, exc.code, exc.__class__.__name__)
    secret_values = [value for value in secrets.values() if isinstance(value, str)]
    token = secrets.get("access_token") or ""
    if not token:
        return _finish(result, "TOKEN_NOT_REUSABLE", "No stored access token is available. No token was exchanged.")
    if quarantine is None:
        return _finish(result, "QUARANTINE_STORE_REQUIRED", "A quarantine store is required. No request was sent.")
    try:
        response = read_historical_candles(caller, token, query)
    except TimeoutError:
        return _finish(result, "PROVIDER_TIMEOUT", "The Groww historical request timed out. It was not retried.", secrets=secret_values)
    except Exception as exc:
        return _finish(result, "PROVIDER_ERROR", redact_text(exc.__class__.__name__, secret_values), secrets=secret_values)
    chunk = classify_historical_response(response, instrument="NIFTY", query=query, retrieved_at=retrieved_at)
    result["network_calls"] = 1
    result["retry"] = False
    result["token_refreshed"] = False
    if chunk["retrieval"]["http_status"] is not None:
        saved = quarantine.write(_record(chunk))
        result["quarantine"] = [
            {
                "quarantine_id": saved["quarantine_id"],
                "checksum": saved["checksum"],
                "raw_body_sha256": saved["raw_body_sha256"],
                "candle_count": saved["candle_count"],
                "candle_interval": saved["candle_interval"],
                "label": saved["label"],
            }
        ]
    return _finish(result, chunk["code"], chunk["message"], secrets=secret_values)


def _record(chunk: dict) -> dict:
    retrieval = chunk["retrieval"]
    return {
        "schema_version": QUARANTINE_SCHEMA,
        "label": "UNVERIFIED_PROVIDER",
        "provider": "groww",
        "instrument": "NIFTY",
        "exchange": chunk["query"]["exchange"],
        "segment": chunk["query"]["segment"],
        "groww_symbol": chunk["query"]["groww_symbol"],
        "interval": DIAGNOSTIC_INTERVAL,
        "candle_interval": chunk["query"]["candle_interval"],
        "requested_start_sent": chunk["query"]["start_time"],
        "requested_end_sent": chunk["query"]["end_time"],
        "retrieved_at": chunk["retrieved_at"],
        "http_status": retrieval["http_status"],
        "provider_status": retrieval["provider_status"],
        "response_start_time": retrieval["response_start_time"],
        "response_end_time": retrieval["response_end_time"],
        "interval_in_minutes": retrieval["interval_in_minutes"],
        "candle_count": retrieval["candle_count"],
        "first_raw_timestamp": retrieval["first_raw_timestamp"],
        "last_raw_timestamp": retrieval["last_raw_timestamp"],
        "raw_candles": chunk.get("raw_candles") or [],
        "raw_body_sha256": retrieval["raw_body_sha256"],
        "numeric_quality": chunk["numeric_quality"],
        "timestamp_timezone": "UNVERIFIED",
        "candle_boundary": "UNVERIFIED",
        "diagnostic": "one-minute",
        "forecast_eligible": False,
        "real_market_data_verified": False,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
    }


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise HistoryStoreError("INVALID_RANGE", f"{field_name} must be timezone-aware. No timezone was assumed.")
    return value


def _wire_clock(value: datetime) -> str:
    """Send the caller's own year, month, day, and clock. Do not convert the zone."""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _base(query: dict[str, str]) -> dict:
    return {
        "ok": False,
        "code": None,
        "message": None,
        "query": query,
        "request_clock": "The caller wall-clock fields were sent without a timezone conversion. The provider timezone is unverified.",
        "session_completion_checked": False,
        "network_calls": 0,
        "retry": False,
        "token_refreshed": False,
        "enabled_changed": False,
        "quarantine": [],
        "candles": [],
        "trusted_dataset_created": False,
        "forecast_eligible": False,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
    }


def _finish(result: dict, code: str, message: str, *, secrets: list[str] | None = None) -> dict:
    result["code"] = code
    result["message"] = redact_text(message, secrets)
    result["ok"] = False
    result["candles"] = []
    result["trusted_dataset_created"] = False
    result["forecast_ready"] = False
    result["paper_approved"] = False
    result["live_approved"] = False
    result["real_market_data_verified"] = False
    result["token_refreshed"] = False
    result["retry"] = False
    log.info("minute diagnostic %s %s", code, result["message"])
    return result
