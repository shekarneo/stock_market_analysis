"""Groww authentication helpers taken from the curl introduction page.

Checksum is SHA-256 of the API secret concatenated with the epoch-second
timestamp. The token URL and the user-margin GET are the only Groww calls.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime
from zoneinfo import ZoneInfo

from urllib.parse import urlencode

from app.integrations.http import (
    GROWW_CANDLES_URL,
    GROWW_LTP_URL,
    GROWW_MARGIN_URL,
    GROWW_QUOTE_URL,
    GROWW_TOKEN_URL,
    LTP_PARAMS,
    QUOTE_PARAMS,
    HttpResult,
)

TIMEOUT = 10.0
KOLKATA = ZoneInfo("Asia/Kolkata")


def checksum(secret: str, timestamp: str) -> str:
    digest = hashlib.sha256()
    digest.update(f"{secret}{timestamp}".encode("utf-8"))
    return digest.hexdigest()


def totp_code(secret: str, *, timestamp: int) -> str:
    cleaned = "".join(secret.split()).upper()
    padding = "=" * ((8 - len(cleaned) % 8) % 8)
    try:
        key = base64.b32decode(cleaned + padding, casefold=True)
    except Exception as exc:
        raise ValueError("TOTP secret is not base32") from exc
    counter = int(timestamp // 30).to_bytes(8, "big")
    digest = hmac.new(key, counter, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return str(binary % 1_000_000).zfill(6)


def classify_token_expiry(value: str | None, now: datetime) -> dict:
    """Classify a stored expiry without refreshing a token.

    An offset-less expiry is Asia/Kolkata wall time. The Groww API dashboard
    resets API keys daily at 6:00 AM IST. A timezone-aware expiry keeps its
    own offset. Both are compared with the current Asia/Kolkata time.
    """
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        return _expiry("UNVERIFIABLE", "UNKNOWN_TIMEZONE", "The comparison clock has no timezone. No token was refreshed.")
    if value is None or value == "":
        return _expiry("UNVERIFIABLE", "MISSING", "No token expiry is stored. No token was refreshed.")
    if not isinstance(value, str):
        return _expiry("UNVERIFIABLE", "MALFORMED", "The token expiry is not text. No token was refreshed.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return _expiry("UNVERIFIABLE", "MALFORMED", "The token expiry is not ISO-8601. No token was refreshed.")
    offset_less = parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None
    if offset_less:
        parsed = parsed.replace(tzinfo=KOLKATA)
    if parsed.astimezone(KOLKATA) <= now.astimezone(KOLKATA):
        if offset_less:
            return _expiry(
                "EXPIRED",
                "ASIA_KOLKATA",
                "The offset-less token expiry is read as Asia/Kolkata and is at or before the current Asia/Kolkata time. No token was refreshed.",
            )
        return _expiry("EXPIRED", "PAST", "The timezone-aware token expiry is at or before the current Asia/Kolkata time. No token was refreshed.")
    if offset_less:
        return _expiry(
            "VALID",
            "ASIA_KOLKATA",
            "The offset-less token expiry is read as Asia/Kolkata and is after the current Asia/Kolkata time. No token was refreshed.",
        )
    return _expiry("VALID", "FUTURE", "The timezone-aware token expiry is after the current Asia/Kolkata time. No token was refreshed.")


def expiry_deadline(value: str | None) -> datetime | None:
    """Return the expiry instant in Asia/Kolkata, or None when it cannot be read."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        parsed = parsed.replace(tzinfo=KOLKATA)
    return parsed.astimezone(KOLKATA)


def expiry_is_past(value: str | None, now: datetime) -> bool:
    """True when classify_token_expiry returns EXPIRED. This does not refresh a token."""
    return classify_token_expiry(value, now)["status"] == "EXPIRED"


def _expiry(status: str, reason: str, message: str) -> dict:
    return {
        "status": status,
        "code": "TOKEN_EXPIRED" if status == "EXPIRED" else "EXPIRY_UNVERIFIABLE" if status == "UNVERIFIABLE" else "TOKEN_UNEXPIRED",
        "reason": reason,
        "refresh": False,
        "message": message,
    }


def exchange_token(caller, secrets: dict, *, method: str, now: datetime) -> tuple[dict, str | None]:
    timestamp = str(int(now.timestamp()))
    if method == "api_key_secret":
        body = {
            "key_type": "approval",
            "checksum": checksum(secrets["api_secret"], timestamp),
            "timestamp": timestamp,
        }
    elif method == "totp":
        body = {"key_type": "totp", "totp": totp_code(secrets["totp_secret"], timestamp=int(now.timestamp()))}
    else:
        raise ValueError("access tokens are not exchanged")
    result = caller.send(
        "POST",
        GROWW_TOKEN_URL,
        headers={
            "Authorization": f"Bearer {secrets['api_key']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json_body=body,
        timeout=TIMEOUT,
    )
    return _token_from_response(result)


def historical_candles_url(params: dict[str, str]) -> str:
    return GROWW_CANDLES_URL + "?" + urlencode(params)


def read_documented_quote(caller, access_token: str) -> HttpResult:
    """GET the documented NIFTY cash quote. The query cannot be changed by the caller."""
    return caller.send(
        "GET",
        GROWW_QUOTE_URL + "?" + urlencode(QUOTE_PARAMS),
        headers=_read_headers(access_token),
        json_body=None,
        timeout=TIMEOUT,
    )


def read_documented_ltp(caller, access_token: str) -> HttpResult:
    """GET the documented BSE_SENSEX LTP. The query cannot be changed by the caller."""
    return caller.send(
        "GET",
        GROWW_LTP_URL + "?" + urlencode(LTP_PARAMS),
        headers=_read_headers(access_token),
        json_body=None,
        timeout=TIMEOUT,
    )


def read_mcx_quote(caller, access_token: str, trading_symbol: str = "CRUDEOILM19OCT26FUT") -> HttpResult:
    """GET the live MCX commodity quote from Groww official API."""
    params = {"exchange": "MCX", "segment": "COMMODITY", "trading_symbol": trading_symbol}
    return caller.send(
        "GET",
        GROWW_QUOTE_URL + "?" + urlencode(params),
        headers=_read_headers(access_token),
        json_body=None,
        timeout=TIMEOUT,
    )


def _read_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "X-API-VERSION": "1.0",
    }


def read_historical_candles(caller, access_token: str, params: dict[str, str]) -> HttpResult:
    return caller.send(
        "GET",
        historical_candles_url(params),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "X-API-VERSION": "1.0",
        },
        json_body=None,
        timeout=15.0,
    )


def read_margin(caller, access_token: str) -> HttpResult:
    return caller.send(
        "GET",
        GROWW_MARGIN_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "X-API-VERSION": "1.0",
        },
        json_body=None,
        timeout=TIMEOUT,
    )


def _token_from_response(result: HttpResult) -> tuple[dict, str | None]:
    if result.status_code == 429:
        raise GrowwCallError("RATE_LIMITED", "Groww rate-limited the token request. It was not retried.")
    if result.status_code in {401, 403}:
        raise GrowwCallError("AUTHENTICATION_FAILED", "Groww rejected the credentials.")
    body = result.body or {}
    if body.get("status") == "FAILURE":
        raise GrowwCallError("AUTHENTICATION_FAILED", "Groww rejected the credentials.")
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else body
    token = payload.get("token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise GrowwCallError("SCHEMA_MISMATCH", "The token response did not include a token.")
    if payload.get("isActive") is False:
        raise GrowwCallError("AUTHENTICATION_FAILED", "Groww returned an inactive access token.")
    expiry = payload.get("expiry")
    return {"access_token": token}, expiry if isinstance(expiry, str) else None


def classify_margin(result: HttpResult) -> tuple[bool, str, str]:
    if result.status_code == 429:
        return False, "RATE_LIMITED", "Groww rate-limited the margin read. It was not retried."
    if result.status_code in {401, 403}:
        return False, "AUTHENTICATION_FAILED", "Groww rejected the access token."
    body = result.body or {}
    if result.status_code >= 500:
        return False, "PROVIDER_UNAVAILABLE", "Groww could not serve the margin read."
    if body.get("status") == "FAILURE":
        return False, "PROVIDER_ERROR", "Groww rejected the request."
    if result.status_code == 200 and body.get("status") == "SUCCESS":
        return True, "CONNECTED", "The read-only margin request succeeded. No order was sent."
    return False, "SCHEMA_MISMATCH", "The margin response did not match the documented success envelope."


class GrowwCallError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
