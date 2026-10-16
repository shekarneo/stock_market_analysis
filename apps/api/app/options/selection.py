"""Choose one contract from a validated chain.

A match is not a trade recommendation. This module does not fetch quotes
and does not rank contracts by expected net.
"""

from __future__ import annotations

from datetime import timedelta

from app.instruments import underlying_list_text
from app.options.pricing import unavailable_decision
from app.options.validation import (
    OPTION_TYPES,
    UNDERLYINGS,
    _error,
    _expiry,
    _finite,
    validate_option_chain,
)

STRIKE_RULES = ("EXACT", "NEAREST_UNDERLYING")


def select_contract(chain: dict, criteria: dict, *, as_of=None, max_age: timedelta | None = None) -> dict:
    """Return one matching contract, or no contract when the match is not unique."""
    result = unavailable_decision()
    result["origin"] = None
    result["matched"] = False
    result["selected"] = None
    result["trade_recommendation"] = False
    if not isinstance(criteria, dict):
        result["errors"] = [_error("INVALID_CRITERIA", "Selection criteria must be an object.")]
        return result
    report = validate_option_chain(chain if isinstance(chain, dict) else {"contracts": None}, as_of=as_of, max_age=max_age)
    if not isinstance(chain, dict):
        result["errors"] = [_error("INVALID_PAYLOAD", "The chain must be an object.")]
        return result
    if not report["ok"] or report["snapshot"] is None:
        result["errors"] = report["errors"]
        result["origin"] = report.get("origin")
        return result
    errors = _criteria_errors(criteria)
    if errors:
        result["errors"] = errors
        result["origin"] = report["origin"]
        return result
    snapshot = report["snapshot"]
    if criteria.get("underlying") != snapshot["underlying"] or criteria.get("expiry") != snapshot["expiry"]:
        result["errors"] = [_error("NO_MATCH", "No contract matches the underlying and expiry.")]
        result["origin"] = report["origin"]
        return result
    rows = [
        row
        for row in snapshot["contracts"]
        if row.get("option_type") == criteria.get("option_type") and row.get("expiry") == criteria.get("expiry")
    ]
    rule = criteria.get("strike_rule") or ("EXACT" if criteria.get("strike") is not None else None)
    if rule == "EXACT":
        target = float(criteria["strike"])
        rows = [row for row in rows if row.get("strike") == target]
    else:
        price = float(snapshot["underlying_price"])
        if rows:
            nearest = min(abs(float(row["strike"]) - price) for row in rows)
            rows = [row for row in rows if abs(float(row["strike"]) - price) == nearest]
    if len(rows) == 0:
        result["errors"] = [_error("NO_MATCH", "No contract matches the criteria.")]
    elif len(rows) > 1:
        result["errors"] = [_error("AMBIGUOUS_MATCH", "More than one contract matches. None was chosen.")]
    else:
        selected = dict(rows[0])
        selected["real_market_data_verified"] = False
        selected["market_observation"] = False
        result["matched"] = True
        result["selected"] = selected
        result["origin"] = selected.get("origin")
    result["origin"] = result.get("origin") or report.get("origin")
    return result


def _criteria_errors(criteria: dict) -> list[dict]:
    errors: list[dict] = []
    if criteria.get("underlying") not in UNDERLYINGS:
        errors.append(_error("INVALID_UNDERLYING", f"The selection underlying must be {underlying_list_text(UNDERLYINGS)}."))
    if criteria.get("option_type") not in OPTION_TYPES:
        errors.append(_error("INVALID_OPTION_TYPE", "The selection option type must be CE or PE."))
    _expiry(criteria.get("expiry"), errors)
    rule = criteria.get("strike_rule")
    strike = criteria.get("strike")
    if rule is None and strike is not None:
        rule = "EXACT"
    if rule is None:
        errors.append(_error("MISSING_STRIKE", "Selection needs an exact strike or the nearest-underlying rule."))
    elif rule not in STRIKE_RULES:
        errors.append(_error("INVALID_STRIKE_RULE", "The strike rule must be EXACT or NEAREST_UNDERLYING."))
    elif rule == "NEAREST_UNDERLYING" and strike is not None:
        errors.append(_error("AMBIGUOUS_CRITERIA", "An exact strike and the nearest-underlying rule cannot both be set."))
    elif rule == "EXACT" and (_finite(strike) is None or float(strike) <= 0):
        errors.append(_error("MISSING_STRIKE", "An exact selection needs a positive strike."))
    return errors
