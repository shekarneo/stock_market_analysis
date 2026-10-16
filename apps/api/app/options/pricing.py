"""Pricing-method gates. Neither method is enabled.

The formulas in the options spec are not applied. A caller-supplied
assumption does not verify theta's time unit, exercise style, a future,
a rate source, or a forecast.
"""

from __future__ import annotations

METHODS = ("MODELLED_VENDOR_GREEKS", "MODELLED_BLACK76")

# Repository facts. These stay unverified until the options spec's evidence exists.
UNVERIFIED_ASSUMPTIONS = {
    "theta_time_unit": "UNVERIFIED",
    "exercise_style": "UNVERIFIED",
    "matching_future": "ABSENT",
    "rate_source": "DISABLED",
    "iv_live_scale_check": "NOT_DONE",
    "approved_forecast": "ABSENT",
}


def unavailable_decision() -> dict:
    return {
        "method": None,
        "status": "UNAVAILABLE",
        "enabled": False,
        "premium": None,
        "expected_net": None,
        "decision": "NO_TRADE",
        "decision_reason": "NO_APPROVED_FORECAST",
        "origin": "CALCULATED",
        "usable_as_quote": False,
        "trade_recommendation": False,
        "forecast_accepted": False,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
        "errors": [],
        "missing": [],
        "unverified": [f"{name}:{state}" for name, state in UNVERIFIED_ASSUMPTIONS.items()],
    }


def price_contract(contract: dict, method: str, assumptions: dict | None = None) -> dict:
    """Report whether a documented method may run. The premium stays null."""
    result = unavailable_decision()
    result["requested_method"] = method
    if assumptions:
        result["errors"].append(
            {
                "code": "ASSUMPTION_UNVERIFIED",
                "detail": "A caller-supplied assumption was not treated as verification.",
            }
        )
    if method not in METHODS:
        result["errors"].append({"code": "METHOD_UNKNOWN", "detail": "The pricing method is not one of the documented methods."})
        return result
    result["method"] = method
    result["missing"] = _missing(contract if isinstance(contract, dict) else {}, method)
    if result["missing"]:
        result["errors"].append({"code": "MISSING_METHOD_INPUT", "detail": "A required pricing input is absent. It was not invented."})
    result["status"] = "UNAVAILABLE"
    result["enabled"] = False
    result["premium"] = None
    result["expected_net"] = None
    result["decision"] = "NO_TRADE"
    return result


def _missing(contract: dict, method: str) -> list[str]:
    missing = []
    if method == "MODELLED_VENDOR_GREEKS":
        greeks = contract.get("greeks") if isinstance(contract.get("greeks"), dict) else {}
        for name in ("delta", "gamma", "theta", "vega"):
            if greeks.get(name) is None:
                missing.append(name)
        if not isinstance(contract.get("volatility"), dict):
            missing.append("volatility")
        if contract.get("bid") is None or contract.get("ask") is None:
            missing.append("bid_ask")
    if method == "MODELLED_BLACK76":
        if not isinstance(contract.get("volatility"), dict):
            missing.append("volatility")
        if contract.get("strike") is None:
            missing.append("strike")
        if contract.get("underlying_price") is None:
            missing.append("underlying_price")
        if contract.get("option_type") not in {"CE", "PE"}:
            missing.append("option_type")
        missing.append("year_fraction")
    missing.append("approved_forecast")
    return missing
