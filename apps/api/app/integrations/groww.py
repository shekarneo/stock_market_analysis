"""Groww authentication helpers taken from the curl introduction page.

Checksum is SHA-256 of the API secret concatenated with the epoch-second
timestamp. The token URL and the user-margin GET are the only Groww calls.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from urllib.parse import urlencode

from app.integrations.http import (
    GROWW_CANDLES_URL,
    GROWW_LTP_URL,
    GROWW_MARGIN_URL,
    GROWW_ORIGIN,
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
    elif method == "totp":
        t_now = int(now.timestamp())
        body = {"key_type": "totp", "totp": totp_code(secrets["totp_secret"], timestamp=t_now)}
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
        # Handle clock skew (up to +/- 30s) if the current step is rejected
        if result.status_code in {401, 403} or (isinstance(result.body, dict) and result.body.get("status") == "FAILURE"):
            for offset in (-30, 30):
                drift_body = {"key_type": "totp", "totp": totp_code(secrets["totp_secret"], timestamp=t_now + offset)}
                drift_res = caller.send(
                    "POST",
                    GROWW_TOKEN_URL,
                    headers={
                        "Authorization": f"Bearer {secrets['api_key']}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json_body=drift_body,
                    timeout=TIMEOUT,
                )
                if drift_res.status_code == 200 and isinstance(drift_res.body, dict) and drift_res.body.get("status") != "FAILURE":
                    result = drift_res
                    break
        return _token_from_response(result)
    else:
        raise ValueError("access tokens are not exchanged")


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


def option_chain_url(exchange: str, underlying: str, expiry_date: str) -> str:
    from urllib.parse import quote
    return f"{GROWW_ORIGIN}/v1/option-chain/exchange/{quote(exchange)}/underlying/{quote(underlying)}?expiry_date={quote(expiry_date)}"


def read_option_chain(
    caller,
    access_token: str,
    *,
    exchange: str = "NSE",
    underlying: str = "NIFTY",
    expiry_date: str,
) -> HttpResult:
    """GET the live option chain for exchange, underlying, and expiry_date from Groww official API."""
    url = option_chain_url(exchange, underlying, expiry_date)
    return caller.send(
        "GET",
        url,
        headers=_read_headers(access_token),
        json_body=None,
        timeout=15.0,
    )


def _parse_int_metric(val: Any) -> int | None:
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return int(val)
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def normalize_option_chain_response(
    result: HttpResult,
    requested_underlying: str,
    requested_expiry: str,
    retrieved_at: datetime,
) -> dict:
    """Validate, normalize, and extract metrics from Groww option chain response.

    Adheres strictly to Truth in Data: missing or null open interest and volume
    values are never silently replaced with genuine zeros.
    """
    import json
    if result.status_code == 429:
        return {"ok": False, "code": "RATE_LIMITED", "message": "Groww rate-limited the option chain read. It was not retried."}
    if result.status_code in {401, 403}:
        return {"ok": False, "code": "AUTHENTICATION_FAILED", "message": "Groww rejected the access token."}
    if result.status_code >= 500:
        return {"ok": False, "code": "PROVIDER_UNAVAILABLE", "message": "Groww could not serve the option chain read."}
    if result.status_code != 200 or not isinstance(result.body, dict):
        return {"ok": False, "code": "SCHEMA_MISMATCH", "message": "The option chain response was not the documented object."}

    body = result.body
    if body.get("status") != "SUCCESS":
        return {"ok": False, "code": "PROVIDER_ERROR", "message": f"Groww returned status {body.get('status')}."}

    payload = body.get("payload")
    if not isinstance(payload, dict):
        return {"ok": False, "code": "SCHEMA_MISMATCH", "message": "Option chain response payload is missing or invalid."}

    raw_ltp = payload.get("underlying_ltp")
    if raw_ltp is None or isinstance(raw_ltp, bool) or not isinstance(raw_ltp, (int, float)) or raw_ltp <= 0:
        return {"ok": False, "code": "INVALID_UNDERLYING_PRICE", "message": "Option chain payload has no valid positive underlying_ltp."}
    underlying_ltp = float(raw_ltp)

    raw_strikes = payload.get("strikes")
    if not isinstance(raw_strikes, dict) or len(raw_strikes) == 0:
        return {"ok": False, "code": "EMPTY_CHAIN", "message": "Option chain payload contains 0 strikes for the requested expiry."}

    # Contract identity audit: verify trading symbols match requested underlying
    for strike_data in raw_strikes.values():
        if isinstance(strike_data, dict):
            ce = strike_data.get("CE") if isinstance(strike_data.get("CE"), dict) else {}
            pe = strike_data.get("PE") if isinstance(strike_data.get("PE"), dict) else {}
            for sym in (ce.get("trading_symbol"), pe.get("trading_symbol")):
                if sym and isinstance(sym, str) and not sym.upper().startswith(requested_underlying.upper()):
                    return {
                        "ok": False,
                        "code": "CONTRACT_MISMATCH",
                        "message": f"Returned contract symbol '{sym}' does not match requested underlying '{requested_underlying}'.",
                    }

    # Timestamp audit: inspect if provider supplies an observation timestamp
    provider_observed_at: datetime | None = None
    if isinstance(payload.get("timestamp"), (int, float)):
        try:
            provider_observed_at = datetime.fromtimestamp(float(payload["timestamp"]) / 1000.0, tz=timezone.utc)
        except Exception:
            provider_observed_at = None
    elif isinstance(payload.get("observed_at"), str):
        try:
            provider_observed_at = datetime.fromisoformat(payload["observed_at"]).astimezone(timezone.utc)
        except Exception:
            provider_observed_at = None

    total_ce_oi = 0
    total_pe_oi = 0
    total_ce_vol = 0
    total_pe_vol = 0
    valid_ce_oi_count = 0
    missing_ce_oi_count = 0
    valid_pe_oi_count = 0
    missing_pe_oi_count = 0
    valid_ce_vol_count = 0
    missing_ce_vol_count = 0
    valid_pe_vol_count = 0
    missing_pe_vol_count = 0

    valid_strikes: dict[float, dict] = {}

    for strike_str, strike_data in raw_strikes.items():
        if not isinstance(strike_data, dict):
            continue
        try:
            strike_val = float(strike_str)
            if strike_val <= 0:
                continue
        except (ValueError, TypeError):
            continue

        ce = strike_data.get("CE") if isinstance(strike_data.get("CE"), dict) else {}
        pe = strike_data.get("PE") if isinstance(strike_data.get("PE"), dict) else {}

        ce_oi = _parse_int_metric(ce.get("open_interest"))
        pe_oi = _parse_int_metric(pe.get("open_interest"))
        ce_vol = _parse_int_metric(ce.get("volume"))
        pe_vol = _parse_int_metric(pe.get("volume"))

        if ce_oi is not None:
            total_ce_oi += ce_oi
            valid_ce_oi_count += 1
        else:
            missing_ce_oi_count += 1

        if pe_oi is not None:
            total_pe_oi += pe_oi
            valid_pe_oi_count += 1
        else:
            missing_pe_oi_count += 1

        if ce_vol is not None:
            total_ce_vol += ce_vol
            valid_ce_vol_count += 1
        else:
            missing_ce_vol_count += 1

        if pe_vol is not None:
            total_pe_vol += pe_vol
            valid_pe_vol_count += 1
        else:
            missing_pe_vol_count += 1

        valid_strikes[strike_val] = {
            "strike": strike_val,
            "CE": ce,
            "PE": pe,
            "ce_oi": ce_oi,
            "pe_oi": pe_oi,
            "ce_vol": ce_vol,
            "pe_vol": pe_vol,
        }

    if not valid_strikes:
        return {"ok": False, "code": "EMPTY_CHAIN", "message": "No valid numeric strikes found in option chain payload."}

    sorted_strikes = sorted(valid_strikes.keys())
    min_strike = sorted_strikes[0]
    max_strike = sorted_strikes[-1]

    pcr_oi = round(total_pe_oi / total_ce_oi, 4) if total_ce_oi > 0 else None
    pcr_vol = round(total_pe_vol / total_ce_vol, 4) if total_ce_vol > 0 else None

    atm_strike = min(valid_strikes.keys(), key=lambda s: abs(s - underlying_ltp))
    atm_ce = valid_strikes[atm_strike]["CE"]
    atm_pe = valid_strikes[atm_strike]["PE"]

    atm_ce_iv = (atm_ce.get("greeks") or {}).get("iv")
    atm_pe_iv = (atm_pe.get("greeks") or {}).get("iv")
    if atm_ce_iv is not None and atm_pe_iv is not None:
        try:
            atm_iv = round((float(atm_ce_iv) + float(atm_pe_iv)) / 2.0, 2)
        except (ValueError, TypeError):
            atm_iv = None
    elif atm_ce_iv is not None:
        try:
            atm_iv = round(float(atm_ce_iv), 2)
        except (ValueError, TypeError):
            atm_iv = None
    elif atm_pe_iv is not None:
        try:
            atm_iv = round(float(atm_pe_iv), 2)
        except (ValueError, TypeError):
            atm_iv = None
    else:
        atm_iv = None

    # Max Pain calculation skipping missing OI contracts (Truth in Data)
    min_pain = float("inf")
    max_pain_strike = None
    for k in sorted_strikes:
        pain = 0.0
        for s in sorted_strikes:
            s_ce_oi = valid_strikes[s]["ce_oi"]
            s_pe_oi = valid_strikes[s]["pe_oi"]
            if s < k and s_ce_oi is not None:
                pain += s_ce_oi * (k - s)
            elif s > k and s_pe_oi is not None:
                pain += s_pe_oi * (s - k)
        if pain < min_pain:
            min_pain = pain
            max_pain_strike = k

    raw_hash = hashlib.sha256(result.raw if result.raw else json.dumps(body, sort_keys=True).encode()).hexdigest()

    validation_results = {
        "underlying_ltp_valid": True,
        "underlying_in_strike_range": min_strike <= underlying_ltp <= max_strike,
        "strike_count": len(valid_strikes),
        "min_strike": min_strike,
        "max_strike": max_strike,
        "atm_strike": atm_strike,
        "atm_distance": round(abs(atm_strike - underlying_ltp), 2),
        "valid_ce_oi_count": valid_ce_oi_count,
        "missing_ce_oi_count": missing_ce_oi_count,
        "valid_pe_oi_count": valid_pe_oi_count,
        "missing_pe_oi_count": missing_pe_oi_count,
        "valid_ce_vol_count": valid_ce_vol_count,
        "missing_ce_vol_count": missing_ce_vol_count,
        "valid_pe_vol_count": valid_pe_vol_count,
        "missing_pe_vol_count": missing_pe_vol_count,
        "provider_observed_at_supplied": provider_observed_at is not None,
    }

    limitations = [
        "Real-time option chain retrieved from Groww Trading API.",
        "Greeks and open interest are provider telemetry, not independently audited exchange clearing house files.",
        "Provider payload omits exchange broadcast matching timestamp; observation freshness is bounded by retrieval window and session state.",
        "Real trading execution remains disabled.",
    ]
    if missing_ce_oi_count > 0 or missing_pe_oi_count > 0:
        limitations.append(
            f"Truth in Data: {missing_ce_oi_count} CE and {missing_pe_oi_count} PE contracts had missing/null OI and were excluded from PCR/MaxPain without assuming zero."
        )

    # If provider did not supply observation timestamp, observed_at is None
    # to prevent a fresh retrieval timestamp from making an old market observation appear fresh.
    observed_iso = provider_observed_at.isoformat() if provider_observed_at else None

    observation = {
        "instrument": requested_underlying,
        "category": "DERIVATIVES",
        "claim": (
            f"Groww option chain for {requested_underlying} (expiry {requested_expiry}): "
            f"{len(valid_strikes)} strikes, PCR(OI) {pcr_oi if pcr_oi is not None else 'N/A'}, "
            f"ATM IV {atm_iv if atm_iv is not None else 'N/A'}%."
        ),
        "claim_type": "OBSERVATION",
        "source_name": "GET /v1/option-chain",
        "provenance": "PROVIDER",
        "data_class": "UNVERIFIED_PROVIDER_DATA",
        "verification_status": "UNVERIFIED",
        "observed_at": observed_iso,
        "provider_observed_at": observed_iso,
        "retrieved_at": retrieved_at.isoformat(),
        "directional_implication": "UNKNOWN",
        "time_horizon": "INTRADAY",
        "underlying_price": underlying_ltp,
        "expiry": requested_expiry,
        "strike_count": len(valid_strikes),
        "total_ce_oi": total_ce_oi,
        "total_pe_oi": total_pe_oi,
        "pcr_oi": pcr_oi,
        "pcr_volume": pcr_vol,
        "atm_strike": atm_strike,
        "atm_iv": atm_iv,
        "max_pain_strike": max_pain_strike,
        "raw_hash": raw_hash,
        "raw_payload_sha256": raw_hash,
        "validation_results": validation_results,
        "limitations": limitations,
    }

    return {
        "ok": True,
        "observation": observation,
        "underlying_ltp": underlying_ltp,
        "expiry": requested_expiry,
        "strike_count": len(valid_strikes),
        "pcr_oi": pcr_oi,
        "pcr_volume": pcr_vol,
        "atm_strike": atm_strike,
        "atm_iv": atm_iv,
        "max_pain_strike": max_pain_strike,
        "total_ce_oi": total_ce_oi,
        "total_pe_oi": total_pe_oi,
        "raw_hash": raw_hash,
        "validation_results": validation_results,
        "strikes": valid_strikes,
    }


