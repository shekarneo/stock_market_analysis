"""Read-only Groww quote and LTP for the two documented symbols.

The curl live-data page documents last_trade_time as epoch milliseconds and
names trading_symbol NIFTY plus exchange symbol BSE_SENSEX. A successful
HTTP response is stored as unverified provider data. It does not verify
candle timestamps, and it does not set a market-data approval flag.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.integrations.groww import classify_token_expiry, read_documented_ltp, read_documented_quote
from app.market.timestamp_contract import contract as timestamp_contract
from app.security.redact import redact_text
from app.settings import REPO_ROOT

READ_PATH = REPO_ROOT / "var" / "market" / "live_reads" / "latest.json"


def stored_observations(path: Path | None = None) -> list[dict]:
    record = load_read(path)
    if not record:
        record = {}
    obs = list(record.get("observations") or [])
    insts = {o.get("instrument") for o in obs if o.get("instrument")}
    if record.get("commodities") or record.get("global_indices") or record.get("sectoral_indices"):
        try:
            from app.market.groww_market_snapshot import build_groww_market_observations
            extra = build_groww_market_observations(
                record.get("commodities") or [],
                record.get("global_indices") or [],
                record.get("sectoral_indices") or [],
            )
            for o in extra:
                if o.get("instrument") and o["instrument"] not in insts:
                    insts.add(o["instrument"])
                    obs.append(o)
        except Exception:
            pass
    if path is None:
        try:
            from app.market.macro_series import get_macro_observations
            for o in get_macro_observations():
                if o.get("instrument") and o["instrument"] not in insts:
                    insts.add(o["instrument"])
                    obs.append(o)
        except Exception:
            pass
        try:
            from app.market.groww_options import load_stored_option_chain_observation
            chain_obs = load_stored_option_chain_observation()
            if chain_obs and not any(o.get("category") == "DERIVATIVES" for o in obs):
                obs.append(chain_obs)
        except Exception:
            pass
    return obs


def load_read(path: Path | None = None) -> dict | None:
    target = path or READ_PATH
    if not target.is_file():
        return None
    try:
        body = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(body, dict):
        return None
    return body


def save_read(record: dict, path: Path | None = None) -> None:
    target = path or READ_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, separators=(",", ":")))
    temporary.replace(target)


def _extract_jwt_expiry(token: str) -> str | None:
    if not token or not isinstance(token, str):
        return None
    parts = token.strip().split(".")
    if len(parts) == 3:
        try:
            import base64
            padded = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
            data = json.loads(base64.urlsafe_b64decode(padded))
            exp = data.get("exp")
            if isinstance(exp, (int, float)):
                return datetime.fromtimestamp(exp, tz=timezone.utc).isoformat()
        except Exception:
            pass
    return None


def run_live_read(session, settings, *, caller, retrieved_at: datetime, path: Path | None = None) -> dict:
    """Send the documented quote, then the documented LTP, when a stored token is still valid.

    This does not exchange a token, enable the integration, or read candles.
    """
    retrieved_at = _aware(retrieved_at)
    base = {
        "status": "NOT_READ",
        "network_calls": 0,
        "token_refreshed": False,
        "candles_requested": False,
        "timestamp_contract": {
            "candle_mapping_allowed": timestamp_contract()["mapping_allowed"],
            "quote_last_trade_time": "epoch_milliseconds",
        },
        "real_market_data_verified": False,
        "quotes": [],
        "observations": [],
        "errors": [],
    }
    from app.domain.tables import IntegrationCredential
    from app.integrations.crypto import SecretBoxError, decrypt_secrets

    row = session.get(IntegrationCredential, "groww")
    if row is None or not row.ciphertext:
        return _done(base, "NOT_CONFIGURED", "Groww credentials are not saved. No request was sent.")
    if row.enabled is not True:
        return _done(base, "INTEGRATION_DISABLED", "Groww is disabled. No request was sent.")
    
    expiry = row.token_expiry
    if not expiry and row.ciphertext:
        try:
            secrets_temp = decrypt_secrets(settings, row.ciphertext)
            token_temp = secrets_temp.get("access_token") or ""
            jwt_exp = _extract_jwt_expiry(token_temp)
            if jwt_exp:
                expiry = jwt_exp
                row.token_expiry = jwt_exp
                session.flush()
        except Exception:
            pass

    classified = classify_token_expiry(expiry, retrieved_at)
    if classified["status"] != "VALID":
        if row.auth_method == "totp":
            try:
                from app.integrations.service import groww_read_token
                token = groww_read_token(session, settings, caller=caller)
                session.refresh(row)
                expiry = row.token_expiry
                classified = classify_token_expiry(expiry, retrieved_at)
            except Exception as renew_exc:
                return _done(base, "TOKEN_EXPIRED", f"Groww TOTP auto-renewal failed: {renew_exc}")
        if classified["status"] != "VALID":
            return _done(base, classified["code"], classified["message"])
    try:
        secrets = decrypt_secrets(settings, row.ciphertext)
    except SecretBoxError as exc:
        return _done(base, exc.code, exc.__class__.__name__)
    secret_values = [value for value in secrets.values() if isinstance(value, str)]
    token = secrets.get("access_token") or ""
    if not token:
        if row.auth_method == "totp":
            try:
                from app.integrations.service import groww_read_token
                token = groww_read_token(session, settings, caller=caller)
                secrets = decrypt_secrets(settings, row.ciphertext)
                secret_values = [value for value in secrets.values() if isinstance(value, str)]
            except Exception as renew_exc:
                return _done(base, "TOKEN_NOT_REUSABLE", f"Groww TOTP token acquisition failed: {renew_exc}")
        else:
            return _done(base, "TOKEN_NOT_REUSABLE", "No stored access token is available. No token was exchanged.")
    try:
        quote_response = read_documented_quote(caller, token)
    except TimeoutError:
        return _done(base, "PROVIDER_TIMEOUT", "The Groww quote request timed out. It was not retried.", secrets=secret_values, calls=1)
    except Exception as exc:
        return _done(base, "PROVIDER_ERROR", redact_text(exc.__class__.__name__, secret_values), secrets=secret_values, calls=1)
    base["network_calls"] = 1
    quote = _normalize_quote(quote_response, retrieved_at)
    if quote.get("ok"):
        base["quotes"].append(quote["quote"])
    else:
        # If token was rejected and method is TOTP, retry once with a fresh token
        if quote["code"] == "AUTHENTICATION_FAILED" and row.auth_method == "totp":
            try:
                from app.integrations.service import _groww_access_token, _store_derived_token
                token, expiry, exchanged = _groww_access_token(caller, row, secrets, retrieved_at, force_exchange=True)
                _store_derived_token(session, settings, row, secrets, token, expiry)
                quote_response = read_documented_quote(caller, token)
                quote = _normalize_quote(quote_response, retrieved_at)
                if quote.get("ok"):
                    base["quotes"].append(quote["quote"])
                else:
                    base["errors"].append({"instrument": "NIFTY", "code": quote["code"], "message": quote["message"]})
                    return _done(base, quote["code"], quote["message"], secrets=secret_values, calls=2)
            except Exception:
                base["errors"].append({"instrument": "NIFTY", "code": quote["code"], "message": quote["message"]})
                return _done(base, quote["code"], quote["message"], secrets=secret_values, calls=1)
        else:
            base["errors"].append({"instrument": "NIFTY", "code": quote["code"], "message": quote["message"]})
            if quote["code"] in {"AUTHENTICATION_FAILED", "RATE_LIMITED"}:
                return _done(base, quote["code"], quote["message"], secrets=secret_values, calls=1)
    try:
        ltp_response = read_documented_ltp(caller, token)
    except TimeoutError:
        return _persist(base, "PROVIDER_TIMEOUT", "The Groww LTP request timed out. It was not retried.", path, secrets=secret_values, calls=2)
    except Exception as exc:
        return _persist(base, "PROVIDER_ERROR", redact_text(exc.__class__.__name__, secret_values), path, secrets=secret_values, calls=2)
    base["network_calls"] = 2
    ltp = _normalize_ltp(ltp_response, retrieved_at)
    if ltp.get("ok"):
        base["quotes"].append(ltp["quote"])
    else:
        base["errors"].append({"instrument": "SENSEX", "code": ltp["code"], "message": ltp["message"]})
    if not base["quotes"]:
        code = base["errors"][0]["code"] if base["errors"] else "SCHEMA_MISMATCH"
        return _done(base, code, "No documented quote or LTP could be read.", secrets=secret_values, calls=2)
    base["observations"] = [_observation(item) for item in base["quotes"]]
    code = "READ" if not base["errors"] else "PARTIAL"
    message = "The documented NIFTY quote and BSE_SENSEX LTP were stored as unverified provider data."
    if base["errors"]:
        message = "Part of the documented read was stored. The failed instrument was not filled in."
    return _persist(base, code, message, path, secrets=secret_values, calls=2)


def _persist(base, code, message, path, *, secrets, calls) -> dict:
    if base["quotes"]:
        record = _done(base, code, message, secrets=secrets, calls=calls)
        existing = load_read(path) or {}
        for key in ("commodities", "global_indices", "sectoral_indices"):
            if key in existing and key not in record:
                record[key] = existing[key]
        if "observations" in existing and "observations" in record:
            insts = {o.get("instrument") for o in record["observations"]}
            for o in existing["observations"]:
                if o.get("instrument") and o["instrument"] not in insts:
                    insts.add(o["instrument"])
                    record["observations"].append(o)
        save_read(record, path)
        return record
    return _done(base, code, message, secrets=secrets, calls=calls)


def _normalize_quote(result, retrieved_at: datetime) -> dict:
    failed = _http_failure(result, "quote")
    if failed:
        return failed
    payload = _payload(result.body)
    raw_price = payload.get("last_price") if payload.get("last_price") is not None else payload.get("ltp")
    price = _number(raw_price)
    stamp = payload.get("last_trade_time")
    if price is None:
        return {"ok": False, "code": "SCHEMA_MISMATCH", "message": "The quote is missing a numeric last_price."}
    if isinstance(stamp, int) and not isinstance(stamp, bool):
        event = datetime.fromtimestamp(stamp / 1000, tz=timezone.utc).isoformat()
        time_limitation = "last_trade_time is documented as epoch milliseconds. The price is not a verified market print."
    else:
        event = retrieved_at.astimezone(timezone.utc).isoformat()
        time_limitation = "last_trade_time was null; retrieved_at timestamp used as quote time."
    ohlc, notes = _ohlc(payload.get("ohlc"))
    return {
        "ok": True,
        "quote": {
            "instrument": "NIFTY",
            "last_price": price,
            "ohlc": ohlc,
            "event_timestamp": event,
            "retrieved_at": retrieved_at.astimezone(timezone.utc).isoformat(),
            "source": "GET /v1/live-data/quote",
            "query": "exchange=NSE&segment=CASH&trading_symbol=NIFTY",
            "data_class": "UNVERIFIED_PROVIDER_DATA",
            "verification_status": "UNVERIFIED",
            "limitations": [
                time_limitation,
                "This index quote is not an option premium.",
                *notes,
            ],
        },
    }


def _normalize_ltp(result, retrieved_at: datetime) -> dict:
    failed = _http_failure(result, "LTP")
    if failed:
        return failed
    payload = _payload(result.body)
    price = _number(payload.get("BSE_SENSEX"))
    if price is None:
        return {"ok": False, "code": "SCHEMA_MISMATCH", "message": "The LTP payload has no numeric BSE_SENSEX value."}
    return {
        "ok": True,
        "quote": {
            "instrument": "SENSEX",
            "last_price": price,
            "ohlc": None,
            "event_timestamp": None,
            "retrieved_at": retrieved_at.astimezone(timezone.utc).isoformat(),
            "source": "GET /v1/live-data/ltp",
            "query": "segment=CASH&exchange_symbols=BSE_SENSEX",
            "data_class": "UNVERIFIED_PROVIDER_DATA",
            "verification_status": "UNVERIFIED",
            "limitations": ["The LTP response has no trade timestamp, so freshness is unknown."],
        },
    }


def _ohlc(value) -> tuple[dict | None, list[str]]:
    if isinstance(value, str):
        return None, ["The ohlc field was text and was not parsed into prices."]
    if not isinstance(value, dict):
        return None, ["No ohlc object was returned."]
    parsed = {}
    for name in ("open", "high", "low", "close"):
        number = _number(value.get(name))
        if number is None:
            return None, ["The ohlc object was incomplete and was not used."]
        parsed[name] = number
    return parsed, []


def _observation(quote: dict) -> dict:
    return {
        "instrument": quote["instrument"],
        "category": "INDIAN_MARKET",
        "claim": f"Groww reported last_price {quote['last_price']} for {quote['instrument']}. Direction was not inferred.",
        "claim_type": "OBSERVATION",
        "source_name": quote["source"],
        "provenance": "PROVIDER",
        "last_price": quote["last_price"],
        "ohlc": quote.get("ohlc"),
        "observed_at": quote.get("event_timestamp") or quote.get("retrieved_at"),
        "published_at": None,
        "retrieved_at": quote["retrieved_at"],
        "directional_implication": "UNKNOWN",
        "time_horizon": "INTRADAY",
    }


def _payload(body: dict) -> dict:
    payload = body.get("payload")
    return payload if isinstance(payload, dict) else body


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _http_failure(result, label: str) -> dict | None:
    if result.status_code == 429:
        return {"ok": False, "code": "RATE_LIMITED", "message": f"Groww rate-limited the {label} read. It was not retried."}
    if result.status_code in {401, 403}:
        return {"ok": False, "code": "AUTHENTICATION_FAILED", "message": "Groww rejected the access token."}
    if result.status_code >= 500:
        return {"ok": False, "code": "PROVIDER_UNAVAILABLE", "message": f"Groww could not serve the {label} read."}
    if result.status_code != 200 or not isinstance(result.body, dict):
        return {"ok": False, "code": "SCHEMA_MISMATCH", "message": f"The {label} response was not the documented object."}
    if result.body.get("status") == "FAILURE":
        return {"ok": False, "code": "PROVIDER_ERROR", "message": f"Groww rejected the {label} request."}
    return None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("retrieved_at must be timezone-aware")
    return value.astimezone(timezone.utc)


def _done(base: dict, code: str, message: str, *, secrets: list[str] | None = None, calls: int | None = None) -> dict:
    body = dict(base)
    if calls is not None:
        body["network_calls"] = calls
    body["status"] = code
    body["code"] = code
    body["message"] = redact_text(message, secrets)
    body["real_market_data_verified"] = False
    return body
