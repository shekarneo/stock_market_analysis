"""Expected-net checks and research ranking.

The options spec defines expected net as the probability-weighted sum of
scenario nets on the zero-volatility-stress slice. This module calculates
that sum only from explicit scenario nets. It does not turn a direction
probability into a premium, and it does not fill missing charges with zero.
Production pricing stays unavailable, so a candidate's expected net stays null.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from app.options.pricing import price_contract
from app.options.validation import validate_option_inputs

APPROVED_FORECAST_STATES = frozenset({"APPROVED_FOR_PAPER", "APPROVED_FOR_LIVE"})
SCENARIOS = ("up", "range", "down")
_FLAGS = {
    "forecast_ready": False,
    "paper_approved": False,
    "live_approved": False,
    "real_market_data_verified": False,
    "trade_recommendation": False,
}


def combine_scenario_nets(probabilities: dict, nets: dict) -> dict:
    """sum_k p_k * net_k. The inputs are explicit. The result is not a quote."""
    result = _blocked()
    result["formula"] = "PROBABILITY_WEIGHTED_NET"
    if not isinstance(probabilities, dict) or not isinstance(nets, dict):
        result["reasons"] = ["INVALID_SCENARIOS"]
        return result
    weights = []
    values = []
    for name in SCENARIOS:
        weight = _finite(probabilities.get(name))
        value = _finite(nets.get(name))
        if weight is None or value is None or weight < 0 or weight > 1:
            result["reasons"] = ["INVALID_SCENARIOS"]
            return result
        weights.append(weight)
        values.append(value)
    if abs(sum(weights) - 1) > 0.01:
        result["reasons"] = ["INVALID_PROBABILITIES"]
        return result
    result["status"] = "CALCULATED"
    result["origin"] = "CALCULATED"
    result["usable_as_quote"] = False
    result["production_enabled"] = False
    result["expected_net"] = sum(weight * value for weight, value in zip(weights, values))
    result["unit"] = "CURRENCY_OF_ASK_AND_CHARGES"
    result["reasons"] = []
    return result


def evaluate_expected_value(
    forecast: dict | None,
    contract: dict | None,
    costs: dict | None = None,
    *,
    task_horizon: str | None = None,
    as_of: datetime | None = None,
    max_age: timedelta | None = None,
) -> dict:
    """Decide whether a candidate can carry an expected net. It currently cannot."""
    result = _blocked()
    reasons: list[str] = []
    if not isinstance(contract, dict):
        reasons.append("INVALID_CONTRACT")
        result["reasons"] = reasons
        return result
    reasons.extend(_provenance_reasons(contract))
    reasons.extend(_forecast_reasons(forecast, task_horizon))
    quote = validate_option_inputs(contract, as_of=as_of, max_age=max_age)
    if not quote["ok"]:
        reasons.extend(item["code"] for item in quote["errors"])
    else:
        result["quoted_ask"] = quote["accepted"]["ask"]
    if contract.get("lot_size") is None:
        reasons.append("MISSING_LOT_SIZE")
    reasons.extend(_charge_reasons(costs))
    for method in ("MODELLED_VENDOR_GREEKS", "MODELLED_BLACK76"):
        priced = price_contract(contract, method)
        if priced["enabled"] is not True or priced["premium"] is not None:
            reasons.append(f"PRICING_UNAVAILABLE:{method}")
        for name in priced["missing"]:
            reasons.append(f"MISSING_PRICING_INPUT:{method}:{name}")
        if method == "MODELLED_BLACK76" and "matching_future:ABSENT" in priced["unverified"]:
            reasons.append("MISSING_FORWARD")
    if "r_up" not in (forecast or {}) or "r_range" not in (forecast or {}) or "r_down" not in (forecast or {}):
        if "MISSING_CLASS_CONDITIONAL_RETURNS" not in reasons and isinstance(forecast, dict):
            reasons.append("MISSING_CLASS_CONDITIONAL_RETURNS")
    result["reasons"] = list(dict.fromkeys(reasons))
    result["modelled_value"] = None
    result["gross_expected"] = None
    result["charges"] = None
    result["expected_net"] = None
    result["decision"] = "NO_TRADE"
    return result


def rank_candidates(candidates: list[dict]) -> dict:
    """Order explicit research rows. An unavailable candidate is not a trade."""
    result = _blocked()
    result["ordered"] = []
    result["rejected"] = []
    if not isinstance(candidates, list):
        result["reasons"] = ["INVALID_CANDIDATES"]
        return result
    seen: dict[tuple, int] = {}
    identities = [_identity(row) if isinstance(row, dict) else None for row in candidates]
    for identity in identities:
        if identity is not None:
            seen[identity] = seen.get(identity, 0) + 1
    eligible = []
    for index, row in enumerate(candidates):
        if not isinstance(row, dict):
            result["rejected"].append({"index": index, "reasons": ["INVALID_CONTRACT"]})
            continue
        reasons = []
        identity = identities[index]
        if seen.get(identity, 0) > 1:
            reasons.append("DUPLICATE_CONTRACT")
        if row.get("calculation_status") != "EXPLICIT_TEST_INPUT" or _finite(row.get("expected_net")) is None:
            reasons.append("EXPECTED_NET_UNAVAILABLE")
        if row.get("origin") in {"SYNTHETIC_FIXTURE", "UNVERIFIED_PROVIDER"} or row.get("label") in {
            "SYNTHETIC_FIXTURE",
            "UNVERIFIED_PROVIDER",
        }:
            reasons.append("PROVENANCE_NOT_TRADABLE")
        if reasons:
            result["rejected"].append({"index": index, "reasons": reasons})
            continue
        eligible.append(row)
    eligible.sort(key=_sort_key)
    result["ordered"] = [
        {
            "underlying": row.get("underlying"),
            "expiry": row.get("expiry"),
            "strike": row.get("strike"),
            "option_type": row.get("option_type"),
            "expected_net": row.get("expected_net"),
            "trade_recommendation": False,
        }
        for row in eligible
    ]
    result["reasons"] = [] if eligible else ["NO_ELIGIBLE_CANDIDATE"]
    result["decision"] = "NO_TRADE"
    return result


def _forecast_reasons(forecast: dict | None, task_horizon: str | None) -> list[str]:
    if not isinstance(forecast, dict):
        return ["MISSING_FORECAST"]
    reasons = []
    if task_horizon is None:
        reasons.append("MISSING_HORIZON")
    elif forecast.get("horizon") != task_horizon:
        reasons.append("HORIZON_MISMATCH")
    if forecast.get("is_qualitative") is True:
        reasons.append("QUALITATIVE_FORECAST")
    state = forecast.get("promotion_state")
    if state not in APPROVED_FORECAST_STATES:
        reasons.append("FORECAST_NOT_APPROVED")
    if state == "APPROVED_FOR_RESEARCH":
        reasons.append("RESEARCH_SELECTION_NOT_APPROVAL")
    for name in ("r_up", "r_range", "r_down"):
        if _finite(forecast.get(name)) is None:
            reasons.append("MISSING_CLASS_CONDITIONAL_RETURNS")
            break
    if forecast.get("p_up") is not None and _finite(forecast.get("r_up")) is None:
        reasons.append("DIRECTION_PROBABILITY_NOT_A_PRICE_FORECAST")
    return list(dict.fromkeys(reasons))


def _provenance_reasons(contract: dict) -> list[str]:
    reasons = []
    if contract.get("origin") == "SYNTHETIC_FIXTURE" or contract.get("label") == "SYNTHETIC_FIXTURE":
        reasons.append("SYNTHETIC_NOT_A_MARKET_OBSERVATION")
    if contract.get("origin") == "CALCULATED":
        reasons.append("CALCULATED_NOT_A_QUOTE")
    if (
        contract.get("quarantine_id")
        or contract.get("label") == "UNVERIFIED_PROVIDER"
        or contract.get("data_category") == "UNVERIFIED_PROVIDER"
    ):
        reasons.append("QUARANTINE_REJECTED")
    return reasons


def _charge_reasons(costs: dict | None) -> list[str]:
    if not isinstance(costs, dict) or costs.get("charges") is None:
        return ["MISSING_CHARGES"]
    # No charge schedule is configured. A caller-supplied source name is not one.
    return ["CHARGES_UNVERIFIED"]


def _identity(row: dict) -> tuple:
    return (row.get("underlying"), row.get("expiry"), row.get("strike"), row.get("option_type"))


def _sort_key(row: dict) -> tuple:
    return (
        -float(row["expected_net"]),
        str(row.get("underlying") or ""),
        str(row.get("expiry") or ""),
        float(row.get("strike") or 0),
        str(row.get("option_type") or ""),
    )


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return float(value)


def _blocked() -> dict:
    return {
        "status": "UNAVAILABLE",
        "decision": "NO_TRADE",
        "decision_reason": "NO_APPROVED_FORECAST",
        "quoted_ask": None,
        "modelled_value": None,
        "gross_expected": None,
        "charges": None,
        "expected_net": None,
        "production_enabled": False,
        "usable_as_quote": False,
        "reasons": [],
        **_FLAGS,
    }
