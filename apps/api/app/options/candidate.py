"""Local option-candidate fixture. Identity is not a quote or a trade.

Supplied fields stay supplied. Omitted fields stay missing. An index last
price is not copied into the premium, and expected net stays null.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.execution.paper import PAPER_TRADING_ACTIVE
from app.instruments import OPTION_UNDERLYINGS, underlying_list_text
from app.options.proposal import build_research_proposal
from app.options.validation import _error, _expiry, _optional_positive, _positive, _quote_time, option_eligibility_seconds

SCHEMA = "options-candidate-1"
UNDERLYINGS = OPTION_UNDERLYINGS
OPTION_TYPES = ("CE", "PE")
_IDENTITY_FIELDS = (
    "underlying",
    "exchange",
    "segment",
    "expiry",
    "strike",
    "option_type",
    "trading_symbol",
    "instrument_id",
    "lot_size",
    "tick_size",
)


def assess_option_candidate(fixture: dict, *, decision: dict, as_of: datetime) -> dict:
    """Assess one explicit fixture. A failed check returns no tradable candidate."""
    errors = _validate(fixture)
    if errors:
        return _refused(errors)
    identity = {field: fixture.get(field) for field in _IDENTITY_FIELDS}
    proposal = build_research_proposal(None, {key: value for key, value in identity.items() if value is not None and key not in {"exchange", "segment"}})
    quote = _quote(fixture, as_of)
    evidence = _evidence(fixture, decision, quote)
    blockers = _blockers(identity, evidence, decision)
    return {
        "ok": True,
        "schema_version": SCHEMA,
        "provenance": "EXPLICIT_LOCAL_FIXTURE",
        "tradable": False,
        "listed": None,
        "decision": "NO_TRADE",
        "executable": False,
        "order_connected": False,
        "expected_net": None,
        "expected_return": None,
        "paper_trading_active": PAPER_TRADING_ACTIVE,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
        "live_trading_enabled": False,
        "broker_called": False,
        "quarantine_promoted": False,
        "fixture": identity,
        "identity": [_identity_row(field, identity.get(field)) for field in _IDENTITY_FIELDS],
        "evidence": evidence,
        "blockers": blockers,
        "proposal": {
            "schema_version": proposal.get("schema_version"),
            "decision": proposal.get("decision"),
            "expected_net": None,
            "quote_premium": None,
        },
        "decision_record": {
            "schema_version": decision.get("schema_version"),
            "decision": decision.get("decision"),
            "underlying": decision.get("underlying"),
            "model_ids": [row.get("model_id") for row in (decision.get("forecast_research") or {}).get("models") or [] if isinstance(row, dict)],
            "holdout_ids": list((decision.get("forecast_research") or {}).get("holdout_ids") or []),
            "walk_forward_ids": list((decision.get("forecast_research") or {}).get("walk_forward_ids") or []),
        },
        "errors": [],
    }


def _refused(errors: list[dict]) -> dict:
    return {
        "ok": False,
        "schema_version": SCHEMA,
        "decision": "NO_TRADE",
        "tradable": False,
        "listed": None,
        "expected_net": None,
        "expected_return": None,
        "paper_trading_active": False,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
        "live_trading_enabled": False,
        "broker_called": False,
        "errors": errors,
    }


def _validate(fixture: dict) -> list[dict]:
    errors: list[dict] = []
    if not isinstance(fixture, dict):
        return [_error("INVALID_PAYLOAD", "The candidate fixture must be an object.")]
    if fixture.get("provenance") != "EXPLICIT_LOCAL_FIXTURE":
        errors.append(_error("INVALID_PROVENANCE", "Provenance must be EXPLICIT_LOCAL_FIXTURE. A fixture is not a broker listing."))
    underlying = fixture.get("underlying")
    if underlying is not None and underlying not in UNDERLYINGS:
        errors.append(_error("INVALID_UNDERLYING", f"Underlying must be {underlying_list_text(UNDERLYINGS)} when it is supplied."))
    option_type = fixture.get("option_type")
    if option_type is not None and option_type not in OPTION_TYPES:
        errors.append(_error("INVALID_OPTION_TYPE", "Option type must be CE or PE when it is supplied."))
    if fixture.get("expiry") is not None:
        _expiry(fixture.get("expiry"), errors)
    if fixture.get("strike") is not None:
        _positive(fixture.get("strike"), "strike", "INVALID_STRIKE", errors)
    for name in ("lot_size", "tick_size"):
        _optional_positive(fixture.get(name), name, errors)
    for name in ("exchange", "segment", "trading_symbol", "instrument_id"):
        value = fixture.get(name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            errors.append(_error("INVALID_TEXT", f"{name} must be non-empty text when it is supplied."))
    if fixture.get("quote_timestamp") is not None:
        _quote_time(fixture.get("quote_timestamp"), errors)
    for name in ("bid", "ask", "premium"):
        if fixture.get(name) is not None:
            _positive(fixture.get(name), name, f"INVALID_{name.upper()}", errors)
    if fixture.get("premium") is not None and fixture.get("premium") != fixture.get("ask"):
        errors.append(_error("PREMIUM_NOT_ASK", "A supplied premium must equal the supplied ask. It was not copied from another price."))
    errors.extend(_conflicts(fixture))
    return errors


def _conflicts(fixture: dict) -> list[dict]:
    errors = []
    symbol = fixture.get("trading_symbol")
    instrument = fixture.get("instrument_id")
    if isinstance(symbol, str) and isinstance(instrument, str) and symbol != instrument:
        errors.append(_error("CONFLICTING_IDENTITY", "trading_symbol and instrument_id disagree. Neither value was rewritten."))
    option_type = fixture.get("option_type")
    underlying = fixture.get("underlying")
    for value in (symbol, instrument):
        if not isinstance(value, str):
            continue
        if option_type in OPTION_TYPES and (value.endswith("CE") or value.endswith("PE")) and not value.endswith(option_type):
            errors.append(_error("CONFLICTING_IDENTITY", "The symbol option type disagrees with option_type. Neither value was rewritten."))
        mentioned = _mentioned_underlying(value)
        if underlying in UNDERLYINGS and mentioned is not None and mentioned != underlying:
            errors.append(_error("CONFLICTING_IDENTITY", "The symbol underlying disagrees with underlying. Neither value was rewritten."))
    return errors


def _mentioned_underlying(value: str) -> str | None:
    # BANKNIFTY is out of scope but still detected, so its symbols are not read as NIFTY.
    if "BANKNIFTY" in value:
        return "BANKNIFTY"
    if "CRUDEOILMINI" in value or "CRUDEMINI" in value or "CRUDEOILM" in value:
        return "CRUDEOILMINI"
    if "SENSEX" in value:
        return "SENSEX"
    if "NIFTY" in value:
        return "NIFTY"
    return None


def _identity_row(field: str, value: object) -> dict:
    supplied = value is not None
    verified = False
    reason = None
    if field in {"exchange", "segment"} and supplied:
        reason = "NO_CONTRACT_MASTER"
    elif field in {"lot_size", "tick_size"} and supplied:
        reason = "LOT_TICK_UNVERIFIED"
    elif field == "expiry" and supplied:
        reason = "CALENDAR_NOT_CONFIGURED"
    elif field == "underlying" and value == "SENSEX":
        reason = "UNDERLYING_NOT_IN_OPTION_ALLOW_LIST"
    return {
        "field": field,
        "status": "supplied" if supplied else "missing",
        "value": value,
        "verified": verified,
        "reason": reason,
    }


def _quote(fixture: dict, as_of: datetime) -> dict:
    bid = fixture.get("bid")
    ask = fixture.get("ask")
    stamp = fixture.get("quote_timestamp")
    if bid is None and ask is None and stamp is None:
        return {"status": "missing", "freshness": "missing", "verified": False, "bid": None, "ask": None, "premium": None, "quote_timestamp": None, "reason": "MISSING_OPTION_QUOTE"}
    freshness = "missing" if stamp is None else _freshness(stamp, as_of)
    status = "stale" if freshness == "stale" else "unverified"
    reason = "STALE_QUOTE" if freshness == "stale" else "QUOTE_UNVERIFIED"
    if stamp is None:
        reason = "MISSING_QUOTE_TIMESTAMP"
    return {
        "status": status,
        "freshness": freshness,
        "verified": False,
        "bid": bid,
        "ask": ask,
        "premium": None,
        "quote_timestamp": stamp,
        "reason": reason,
    }


def _freshness(stamp: str, as_of: datetime) -> str:
    parsed = _quote_time(stamp, [])
    if parsed is None or as_of.tzinfo is None or as_of.utcoffset() is None:
        return "unverified"
    limit = timedelta(seconds=option_eligibility_seconds())
    if as_of.astimezone(timezone.utc) - parsed.astimezone(timezone.utc) > limit:
        return "stale"
    return "unverified"


def _evidence(fixture: dict, decision: dict, quote: dict) -> list[dict]:
    market = decision.get("market") if isinstance(decision.get("market"), dict) else {}
    research = decision.get("forecast_research") if isinstance(decision.get("forecast_research"), dict) else {}
    return [
        {"name": "contract_master", "status": "unavailable", "verified": False, "value": None, "reason": "NO_CONTRACT_MASTER"},
        {"name": "option_quote", **quote, "used_as_expected_net": False},
        {
            "name": "index_observation",
            "status": market.get("status") or "missing",
            "verified": False,
            "data_class": market.get("data_class"),
            "last_price": market.get("last_price"),
            "used_as_option_premium": False,
            "reason": "INDEX_PRICE_IS_NOT_AN_OPTION_PREMIUM",
        },
        {"name": "lot_tick_verification", "status": "unavailable", "verified": False, "value": None, "reason": "LOT_TICK_UNVERIFIED"},
        {"name": "expiry_calendar", "status": "unavailable", "verified": False, "value": None, "reason": "CALENDAR_NOT_CONFIGURED"},
        {"name": "charges", "status": "unavailable", "verified": False, "value": None, "reason": "CHARGES_UNVERIFIED"},
        {
            "name": "forecast",
            "status": "unavailable",
            "verified": False,
            "value": None,
            "expected_return": None,
            "approved_forecast_count": research.get("approved_forecast_count") or 0,
            "reason": "NO_APPROVED_FORECAST",
        },
        {"name": "risk_capital", "status": "unavailable", "verified": False, "value": None, "reason": "MISSING_RISK_CAPITAL"},
        {"name": "broker_funds", "status": "unavailable", "verified": False, "value": None, "reason": "BROKER_FUNDS_NOT_READ"},
        {"name": "reconciliation", "status": "unavailable", "verified": False, "value": None, "reason": "RECONCILIATION_UNAVAILABLE"},
        {"name": "execution", "status": "unavailable", "verified": False, "value": None, "reason": "PAPER_TRADING_DISABLED"},
    ]


def _blockers(identity: dict, evidence: list[dict], decision: dict) -> list[dict]:
    rows = [{"code": "TRADABILITY_NOT_ESTABLISHED", "detail": "A local fixture does not establish that the contract is listed or tradable."}]
    for field, code in (
        ("expiry", "MISSING_EXPIRY"),
        ("strike", "MISSING_STRIKE"),
        ("option_type", "MISSING_OPTION_TYPE"),
        ("underlying", "MISSING_UNDERLYING"),
    ):
        if identity.get(field) is None:
            rows.append({"code": code, "detail": f"{field} was not supplied."})
    if identity.get("underlying") == "SENSEX":
        rows.append({"code": "UNDERLYING_NOT_IN_OPTION_ALLOW_LIST", "detail": "SENSEX is not on the configured option allow-list."})
    for item in evidence:
        if item.get("reason"):
            rows.append({"code": item["reason"], "detail": item["name"]})
    for item in decision.get("missing_inputs", {}).get("risk") or []:
        if isinstance(item, dict) and item.get("code"):
            rows.append({"code": item["code"], "detail": "research_status"})
    return _unique(rows)


def _unique(rows: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for row in rows:
        if row["code"] in seen:
            continue
        seen.add(row["code"])
        result.append(row)
    return result
