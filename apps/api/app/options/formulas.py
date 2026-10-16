"""Pure option formulas. A result is a calculation, not a quote or a trade.

Black-76 uses the continuous discount exp(-rate * time_years) only when the
caller names that convention. The options spec does not state the compounding
rule, so any other convention is rejected. The chain spot is not read.
Vendor-Greek units are not converted. Production pricing stays unavailable.
"""

from __future__ import annotations

import math

_FLAGS = {
    "usable_as_quote": False,
    "production_enabled": False,
    "production_status": "UNAVAILABLE",
    "decision": "NO_TRADE",
    "expected_net": None,
    "forecast_accepted": False,
    "forecast_ready": False,
    "paper_approved": False,
    "live_approved": False,
    "real_market_data_verified": False,
    "trade_recommendation": False,
}


def black76_premium(inputs: dict) -> dict:
    """Discounted Black-76 premium for an explicit forward. Spot is not accepted."""
    if not isinstance(inputs, dict):
        return _failure("INVALID_PAYLOAD", "Black-76 inputs must be an object.")
    if inputs.get("forward_source") != "EXPLICIT_TEST_INPUT":
        return _failure("FORWARD_NOT_EXPLICIT", "The forward must be an explicit test input. Spot was not substituted.")
    if inputs.get("rate_convention") != "CONTINUOUS":
        return _failure("AMBIGUOUS_RATE_CONVENTION", "The spec does not name a compounding rule. Only an explicit CONTINUOUS convention is calculated.")
    if inputs.get("rate_unit") != "ANNUAL_CONTINUOUS":
        return _failure("AMBIGUOUS_RATE_UNIT", "The rate must be named ANNUAL_CONTINUOUS. A percent or another unit was not converted.")
    if inputs.get("volatility_unit") != "DECIMAL":
        return _failure("AMBIGUOUS_VOLATILITY_UNIT", "Volatility must be an explicit decimal. A percent was not divided by 100.")
    option_type = inputs.get("option_type")
    if option_type not in {"CE", "PE"}:
        return _failure("INVALID_OPTION_TYPE", "The option type must be CE or PE.")
    forward = _finite(inputs.get("forward"), positive=True)
    strike = _finite(inputs.get("strike"), positive=True)
    time_years = _finite(inputs.get("time_years"), nonnegative=True)
    volatility = _finite(inputs.get("volatility"), nonnegative=True)
    rate = _finite(inputs.get("rate"))
    missing = [
        name
        for name, value in (
            ("forward", forward),
            ("strike", strike),
            ("time_years", time_years),
            ("volatility", volatility),
            ("rate", rate),
        )
        if value is None
    ]
    if missing:
        return _failure("INVALID_DOMAIN", "A Black-76 input is missing, non-finite, or outside its domain.", missing=missing)
    undiscounted = _undiscounted(forward, strike, time_years, volatility, option_type)
    discount = math.exp(-rate * time_years)
    premium = max(0.0, discount * undiscounted)
    return _calculated(premium, formula="BLACK76_CONTINUOUS", extra={"discount_factor": discount})


def vendor_greek_step(inputs: dict) -> dict:
    """Taylor step from the options spec. Units are not inferred or converted."""
    if not isinstance(inputs, dict):
        return _failure("INVALID_PAYLOAD", "Greek inputs must be an object.")
    if not isinstance(inputs.get("theta_unit"), str) or not inputs.get("theta_unit"):
        return _failure("UNRESOLVED_THETA_UNIT", "Theta's time unit is not documented. No day or year conversion was applied.")
    vega_unit = inputs.get("vega_unit")
    move_unit = inputs.get("d_volatility_unit")
    if not isinstance(vega_unit, str) or not vega_unit or vega_unit != move_unit:
        return _failure("UNRESOLVED_VEGA_UNIT", "Vega and the volatility move must name the same explicit unit. No scale conversion was applied.")
    bid = _finite(inputs.get("bid"), positive=True)
    ask = _finite(inputs.get("ask"), positive=True)
    if bid is None or ask is None or ask < bid:
        return _failure("INVALID_QUOTE", "Bid and ask must be positive finite numbers with ask at least bid.")
    numbers = {
        name: _finite(inputs.get(name))
        for name in ("delta", "gamma", "theta", "vega", "d_underlying", "d_time", "d_volatility")
    }
    missing = [name for name, value in numbers.items() if value is None]
    if missing:
        return _failure("INVALID_DOMAIN", "A Greek input is missing or non-finite.", missing=missing)
    change = (
        numbers["delta"] * numbers["d_underlying"]
        + 0.5 * numbers["gamma"] * numbers["d_underlying"] ** 2
        + numbers["theta"] * numbers["d_time"]
        + numbers["vega"] * numbers["d_volatility"]
    )
    mid = (bid + ask) / 2
    return _calculated(
        max(0.0, mid + change),
        formula="VENDOR_GREEK_TAYLOR",
        extra={"quoted_mid": mid, "theta_unit": inputs["theta_unit"], "vega_unit": vega_unit},
    )


def _undiscounted(forward: float, strike: float, time_years: float, volatility: float, option_type: str) -> float:
    if time_years == 0 or volatility == 0:
        intrinsic = forward - strike if option_type == "CE" else strike - forward
        return max(0.0, intrinsic)
    root = volatility * math.sqrt(time_years)
    d1 = (math.log(forward / strike) + 0.5 * volatility * volatility * time_years) / root
    d2 = d1 - root
    if option_type == "CE":
        return forward * _norm_cdf(d1) - strike * _norm_cdf(d2)
    return strike * _norm_cdf(-d2) - forward * _norm_cdf(-d1)


def _norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _finite(value: object, *, positive: bool = False, nonnegative: bool = False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    number = float(value)
    if positive and number <= 0:
        return None
    if nonnegative and number < 0:
        return None
    return number


def _calculated(premium: float, *, formula: str, extra: dict) -> dict:
    result = {
        "ok": True,
        "status": "CALCULATED",
        "origin": "CALCULATED",
        "formula": formula,
        "premium": premium,
        **_FLAGS,
        "errors": [],
    }
    result.update(extra)
    return result


def _failure(code: str, detail: str, *, missing: list[str] | None = None) -> dict:
    return {
        "ok": False,
        "status": "UNAVAILABLE",
        "origin": "CALCULATED",
        "formula": None,
        "premium": None,
        "errors": [{"code": code, "detail": detail}],
        "missing": missing or [],
        **_FLAGS,
    }
