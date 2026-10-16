"""Validate CE/PE inputs without pricing them.

A structurally valid quote is not a Groww premium and is not a trade.
Vendor-greek and Black-76 valuation stay unavailable until the options spec's
preconditions exist. This module does not read the network or a quarantine file.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from pathlib import Path

from app.instruments import OPTION_UNDERLYINGS, underlying_list_text

ORIGINS = ("UNVERIFIED_MARKET_INPUT", "SYNTHETIC_FIXTURE", "CALCULATED")
UNDERLYINGS = OPTION_UNDERLYINGS
OPTION_TYPES = ("CE", "PE")
GREEKS = ("delta", "gamma", "theta", "vega")
CHAIN_SCHEMA = "m8-chain-1"
_CHAIN_FIELDS = ("underlying", "expiry", "underlying_price", "quote_timestamp")
PRICING_BLOCKERS = (
    "Vendor theta's time unit is unverified, so MODELLED_VENDOR_GREEKS stays off.",
    "Exercise style is not verified on a contract specification, so MODELLED_BLACK76 stays off.",
    "No verified matching future is configured, so the index level is not used as the forward.",
    "No enabled rate source is configured, so a supplied rate does not start pricing.",
)


def validate_option_inputs(payload: dict, *, as_of: datetime | None = None, max_age: timedelta | None = None) -> dict:
    """Check one candidate. Never returns a calculated premium or expected net."""
    errors: list[dict] = []
    if not isinstance(payload, dict):
        errors.append(_error("INVALID_PAYLOAD", "The candidate must be an object."))
        return _result(errors, origin=None, accepted={})
    origin = payload.get("origin")
    if origin not in ORIGINS:
        errors.append(_error("INVALID_ORIGIN", "Origin must be an unverified market input, a synthetic fixture, or a calculated value."))
    elif origin == "CALCULATED":
        errors.append(_error("CALCULATED_NOT_A_QUOTE", "A calculated value cannot be supplied as a quote."))
    if payload.get("matches_broker_premium") is True or payload.get("real_market_data_verified") is True:
        errors.append(_error("VERIFICATION_REFUSED", "This check cannot mark a quote as a verified broker premium."))
    if payload.get("underlying") not in UNDERLYINGS:
        errors.append(_error("INVALID_UNDERLYING", f"The underlying must be {underlying_list_text(UNDERLYINGS)}."))
    if payload.get("option_type") not in OPTION_TYPES:
        errors.append(_error("INVALID_OPTION_TYPE", "The option type must be CE or PE."))
    _positive(payload.get("strike"), "strike", "INVALID_STRIKE", errors)
    _positive(payload.get("underlying_price"), "underlying_price", "INVALID_UNDERLYING_PRICE", errors)
    expiry = _expiry(payload.get("expiry"), errors)
    quote_at = _quote_time(payload.get("quote_timestamp"), errors)
    if expiry is not None and quote_at is not None and expiry < quote_at.date():
        errors.append(_error("EXPIRED", "The expiry date is before the quote date."))
    if as_of is not None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            errors.append(_error("INVALID_AS_OF", "as_of must be timezone-aware."))
        elif quote_at is not None and as_of - quote_at > (max_age if max_age is not None else _option_quote_max_age()):
            errors.append(_error("STALE_QUOTE", "The quote is older than the configured option block limit."))
    bid = _positive(payload.get("bid"), "bid", "INVALID_BID", errors)
    ask = _positive(payload.get("ask"), "ask", "INVALID_ASK", errors)
    if bid is not None and ask is not None and ask < bid:
        errors.append(_error("INVALID_SPREAD", "The ask is below the bid."))
    if "premium" in payload and payload.get("premium") is not None:
        premium = _positive(payload.get("premium"), "premium", "INVALID_PREMIUM", errors)
        if premium is not None and ask is not None and premium != ask:
            errors.append(_error("PREMIUM_NOT_ASK", "Entry premium must be the ask. Last price was not copied into it."))
    elif payload.get("ltp") is not None and ask is None:
        errors.append(_error("MISSING_ASK", "Last price is display-only and was not used as the premium."))
    ltp = _optional_positive_value(payload.get("ltp"), "ltp", "INVALID_LTP", errors)
    _optional_positive(payload.get("lot_size"), "lot_size", errors)
    _optional_positive(payload.get("tick_size"), "tick_size", errors)
    greeks = _greeks(payload.get("greeks"), errors)
    volatility = _volatility(payload.get("volatility"), errors)
    rate = _rate(payload.get("interest_rate"), errors)
    accepted = {
        "origin": origin if origin in ORIGINS else None,
        "underlying": payload.get("underlying") if payload.get("underlying") in UNDERLYINGS else None,
        "option_type": payload.get("option_type") if payload.get("option_type") in OPTION_TYPES else None,
        "strike": _accepted_number(payload.get("strike")),
        "expiry": None if expiry is None else expiry.isoformat(),
        "underlying_price": _accepted_number(payload.get("underlying_price")),
        "bid": bid,
        "ask": ask,
        "ltp": ltp,
        "premium": None,
        "quote_timestamp": None if quote_at is None else quote_at.isoformat(),
        **_identifiers(payload, errors),
        "lot_size": _accepted_number(payload.get("lot_size")) if payload.get("lot_size") is not None else None,
        "tick_size": _accepted_number(payload.get("tick_size")) if payload.get("tick_size") is not None else None,
        "volume": _non_negative(payload.get("volume"), "volume", errors),
        "open_interest": _non_negative(payload.get("open_interest"), "open_interest", errors),
        "open_interest_change": _optional_finite_value(payload.get("open_interest_change"), "open_interest_change", errors),
        "greeks": greeks,
        "volatility": volatility,
        "interest_rate": rate,
    }
    return _result(errors, origin=origin if origin in ORIGINS else None, accepted=accepted)


def validate_option_chain(payload: dict, *, as_of: datetime | None = None, max_age: timedelta | None = None) -> dict:
    """Check one chain snapshot. Does not price a contract or read a forecast."""
    if not isinstance(payload, dict):
        return _chain_result([], None, None, [ _error("INVALID_PAYLOAD", "The chain must be an object.") ])
    errors: list[dict] = []
    origin = payload.get("origin")
    if origin not in ORIGINS:
        errors.append(_error("INVALID_ORIGIN", "The chain origin must be explicit."))
    elif origin == "CALCULATED":
        errors.append(_error("CALCULATED_NOT_A_QUOTE", "A calculated value cannot be supplied as a chain quote."))
    if payload.get("real_market_data_verified") is True or payload.get("matches_broker_premium") is True:
        errors.append(_error("VERIFICATION_REFUSED", "A chain snapshot cannot be marked as a verified broker premium."))
    if payload.get("exchange") is not None:
        errors.append(_error("EXCHANGE_UNVERIFIED", "The options spec does not define chain exchange metadata. The supplied value was not stored."))
    _identifiers(payload, errors)
    _optional_positive(payload.get("lot_size"), "lot_size", errors)
    _optional_positive(payload.get("tick_size"), "tick_size", errors)
    if payload.get("underlying") not in UNDERLYINGS:
        errors.append(_error("INVALID_UNDERLYING", f"The chain underlying must be {underlying_list_text(UNDERLYINGS)}."))
    _expiry(payload.get("expiry"), errors)
    _positive(payload.get("underlying_price"), "underlying_price", "INVALID_UNDERLYING_PRICE", errors)
    _quote_time(payload.get("quote_timestamp"), errors)
    if "retrieved_at" in payload and payload.get("retrieved_at") is not None:
        _quote_time_named(payload.get("retrieved_at"), "retrieved_at", "INVALID_RETRIEVED_AT", errors)
    contracts = payload.get("contracts")
    reports: list[dict] = []
    if not isinstance(contracts, list):
        errors.append(_error("INVALID_CHAIN", "The chain contracts field must be a list."))
    elif len(contracts) == 0:
        errors.append(_error("EMPTY_CHAIN", "The chain has no contracts."))
    else:
        seen: set[tuple[object, object]] = set()
        for index, contract in enumerate(contracts):
            if not isinstance(contract, dict):
                errors.append(_indexed("INVALID_PAYLOAD", "A contract must be an object.", index))
                continue
            errors.extend(_chain_mismatches(payload, contract, index))
            child = _child_payload(payload, contract)
            report = validate_option_inputs(child, as_of=as_of, max_age=max_age)
            report["index"] = index
            reports.append(report)
            for item in report["errors"]:
                errors.append(_indexed(item["code"], item["detail"], index))
            identity = (contract.get("strike"), contract.get("option_type"))
            if identity in seen:
                errors.append(_indexed("DUPLICATE_CONTRACT", "The same strike and option type appears twice. It was not merged.", index))
            seen.add(identity)
    snapshot = _snapshot(payload, reports) if not errors else None
    return _chain_result(reports, origin if origin in ORIGINS else None, snapshot, errors)


def _chain_mismatches(chain: dict, contract: dict, index: int) -> list[dict]:
    errors = []
    contract_origin = contract.get("origin")
    chain_origin = chain.get("origin")
    if contract_origin in ORIGINS and chain_origin in ORIGINS and contract_origin != chain_origin:
        errors.append(_indexed("MIXED_PROVENANCE", "A contract origin differs from the chain origin.", index))
    for field in _CHAIN_FIELDS:
        if field not in contract or contract.get(field) is None:
            continue
        if chain.get(field) is not None and contract.get(field) != chain.get(field):
            errors.append(_indexed("INCONSISTENT_CHAIN", f"The contract {field} differs from the chain.", index))
    return errors


def _child_payload(chain: dict, contract: dict) -> dict:
    child = dict(contract)
    for field in _CHAIN_FIELDS:
        if child.get(field) is None and chain.get(field) is not None:
            child[field] = chain[field]
    return child


def _snapshot(payload: dict, reports: list[dict]) -> dict:
    return {
        "schema_version": CHAIN_SCHEMA,
        "origin": payload.get("origin"),
        "underlying": payload.get("underlying"),
        "expiry": payload.get("expiry"),
        "underlying_price": payload.get("underlying_price"),
        "quote_timestamp": payload.get("quote_timestamp"),
        "retrieved_at": payload.get("retrieved_at"),
        "trading_symbol": payload.get("trading_symbol") if isinstance(payload.get("trading_symbol"), str) else None,
        "groww_symbol": payload.get("groww_symbol") if isinstance(payload.get("groww_symbol"), str) else None,
        "broker_symbol": payload.get("broker_symbol") if isinstance(payload.get("broker_symbol"), str) else None,
        "lot_size": payload.get("lot_size") if isinstance(payload.get("lot_size"), (int, float)) and not isinstance(payload.get("lot_size"), bool) else None,
        "tick_size": payload.get("tick_size") if isinstance(payload.get("tick_size"), (int, float)) and not isinstance(payload.get("tick_size"), bool) else None,
        "contracts": [item["accepted"] for item in reports],
        "pricing_status": "UNAVAILABLE",
        "expected_net": None,
        "decision": "NO_TRADE",
        "decision_reason": "NO_APPROVED_FORECAST",
        "forecast_accepted": False,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
    }


def _chain_result(reports: list[dict], origin: str | None, snapshot: dict | None, errors: list[dict]) -> dict:
    return {
        "ok": not errors,
        "errors": errors,
        "origin": origin,
        "contracts": reports,
        "snapshot": snapshot,
        "pricing": {
            "method": None,
            "status": "UNAVAILABLE",
            "premium": None,
            "expected_net": None,
            "matches_broker_premium": False,
            "blockers": list(PRICING_BLOCKERS),
        },
        "forecast_accepted": False,
        "decision": "NO_TRADE",
        "decision_reason": "NO_APPROVED_FORECAST",
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
    }


def _indexed(code: str, detail: str, index: int) -> dict:
    return {"code": code, "detail": detail, "index": index}


def option_eligibility_seconds(config=None) -> int:
    """Option-quote eligibility age. This does not read the risk or execution quote-age settings."""
    if config is None:
        config = _defaults()
    return int(config.freshness.option_block_seconds)


def _option_quote_max_age() -> timedelta:
    return timedelta(seconds=option_eligibility_seconds())


def _defaults():
    from app.config.loader import load_defaults
    from app.settings import REPO_ROOT

    return load_defaults(Path(REPO_ROOT / "config" / "defaults.yaml"))


def _identifiers(payload: dict, errors: list[dict]) -> dict:
    trading = _symbol(payload.get("trading_symbol"), "trading_symbol", errors)
    groww = _symbol(payload.get("groww_symbol"), "groww_symbol", errors)
    broker = _symbol(payload.get("broker_symbol"), "broker_symbol", errors)
    if trading is not None and broker is not None and trading != broker:
        errors.append(_error("SYMBOL_MISMATCH", "broker_symbol must match trading_symbol when both are supplied. Neither value was rewritten."))
    return {"trading_symbol": trading, "groww_symbol": groww, "broker_symbol": broker}


def _quote_time_named(value: object, name: str, code: str, errors: list[dict]) -> datetime | None:
    parsed = _quote_time(value, [])
    if parsed is None:
        errors.append(_error(code, f"{name} must be timezone-aware ISO-8601 text. An offset was not inferred."))
        return None
    return parsed


def _result(errors: list[dict], *, origin: str | None, accepted: dict) -> dict:
    return {
        "ok": not errors,
        "errors": errors,
        "origin": origin,
        "accepted": accepted,
        "pricing": {
            "method": None,
            "status": "UNAVAILABLE",
            "premium": None,
            "expected_net": None,
            "matches_broker_premium": False,
            "blockers": list(PRICING_BLOCKERS),
        },
        "decision": "NO_TRADE",
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
    }


def _error(code: str, detail: str) -> dict:
    return {"code": code, "detail": detail}


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return float(value)


def _optional_positive_value(value: object, name: str, code: str, errors: list[dict]) -> float | None:
    if value is None:
        return None
    return _positive(value, name, code, errors)


def _non_negative(value: object, name: str, errors: list[dict]) -> float | None:
    if value is None:
        return None
    number = _finite(value)
    if number is None or number < 0:
        errors.append(_error("INVALID_SIZE", f"{name} must be a non-negative finite number or null. It was not replaced with zero."))
        return None
    return number


def _optional_finite_value(value: object, name: str, errors: list[dict]) -> float | None:
    if value is None:
        return None
    number = _finite(value)
    if number is None:
        errors.append(_error("INVALID_SIZE", f"{name} must be a finite number or null."))
        return None
    return number


def _symbol(value: object, name: str, errors: list[dict]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        errors.append(_error("INVALID_SYMBOL", f"{name} must be text when it is supplied. An identifier was not invented."))
        return None
    return value


def _positive(value: object, name: str, code: str, errors: list[dict]) -> float | None:
    number = _finite(value)
    if number is None or number <= 0:
        errors.append(_error(code, f"{name} must be a positive finite number."))
        return None
    return number


def _optional_positive(value: object, name: str, errors: list[dict]) -> None:
    if value is None:
        return
    if _finite(value) is None or float(value) <= 0:
        errors.append(_error("INVALID_CONTRACT_SIZE", f"{name} must be a positive finite number when it is supplied."))


def _accepted_number(value: object) -> float | None:
    number = _finite(value)
    if number is None or number <= 0:
        return None
    return number


def _expiry(value: object, errors: list[dict]) -> date | None:
    if not isinstance(value, str) or len(value) != 10:
        errors.append(_error("INVALID_EXPIRY", "Expiry must be a calendar date, YYYY-MM-DD. A weekday name is not an expiry."))
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(_error("INVALID_EXPIRY", "Expiry must be a real calendar date."))
        return None


def _quote_time(value: object, errors: list[dict]) -> datetime | None:
    if not isinstance(value, str):
        errors.append(_error("INVALID_QUOTE_TIME", "The quote timestamp must be timezone-aware ISO-8601 text."))
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        errors.append(_error("INVALID_QUOTE_TIME", "The quote timestamp must be timezone-aware ISO-8601 text."))
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        errors.append(_error("INVALID_QUOTE_TIME", "The quote timestamp has no timezone offset."))
        return None
    return parsed


def _greeks(value: object, errors: list[dict]) -> dict:
    if value is None:
        return {name: None for name in GREEKS}
    if not isinstance(value, dict):
        errors.append(_error("INVALID_GREEKS", "Greeks must be an object. Missing greeks stay null."))
        return {name: None for name in GREEKS}
    stored = {}
    for name in GREEKS:
        item = value.get(name)
        if item is None:
            stored[name] = None
            continue
        number = _finite(item)
        if number is None:
            errors.append(_error("INVALID_GREEKS", f"{name} must be a finite number or null."))
            stored[name] = None
        else:
            stored[name] = number
    return stored


def _volatility(value: object, errors: list[dict]) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        errors.append(_error("INVALID_VOLATILITY", "Volatility needs a number and an explicit scale."))
        return None
    scale = value.get("scale")
    number = _finite(value.get("value"))
    if scale not in {"PERCENT", "DECIMAL"} or number is None or number <= 0:
        errors.append(_error("INVALID_VOLATILITY", "Volatility must be a positive finite number with scale PERCENT or DECIMAL."))
        return None
    if scale == "PERCENT" and number > 500:
        errors.append(_error("INVALID_VOLATILITY", "A percent volatility above 500 was rejected. It was not converted."))
        return None
    if scale == "DECIMAL" and number > 5:
        errors.append(_error("INVALID_VOLATILITY", "A decimal volatility above 5 was rejected. It was not converted."))
        return None
    return {"value": number, "scale": scale}


def _rate(value: object, errors: list[dict]) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        errors.append(_error("INVALID_RATE", "An interest rate needs a finite annual decimal, a unit, and a configured source."))
        return None
    number = _finite(value.get("value"))
    if value.get("unit") != "ANNUAL_DECIMAL" or value.get("source") != "CONFIGURED_INPUT" or number is None:
        errors.append(_error("INVALID_RATE", "An interest rate must be a finite ANNUAL_DECIMAL from CONFIGURED_INPUT."))
        return None
    return {"value": number, "unit": "ANNUAL_DECIMAL", "source": "CONFIGURED_INPUT"}
