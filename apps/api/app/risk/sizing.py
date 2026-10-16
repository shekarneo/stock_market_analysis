"""Position-size arithmetic from the risk spec.

The formula runs only when every named input is supplied. A missing charge is
not treated as zero. A lot count below one is NO TRADE, and it is not rounded up.
"""

from __future__ import annotations

import math
from decimal import Decimal

from app.risk.money import decimal_or_none


def size_position(
    *,
    ask: object,
    lot_size: object,
    charges_per_lot: object,
    risk_capital: object,
    max_risk_fraction_per_trade: object,
) -> dict:
    ask_value = decimal_or_none(ask)
    lot = decimal_or_none(lot_size)
    charges = decimal_or_none(charges_per_lot)
    capital = decimal_or_none(risk_capital)
    fraction = decimal_or_none(max_risk_fraction_per_trade)
    missing = []
    if ask_value is None or ask_value <= 0:
        missing.append("MISSING_ASK")
    if lot is None or lot <= 0:
        missing.append("MISSING_LOT_SIZE")
    if charges is None:
        missing.append("MISSING_CHARGES")
    if capital is None or capital <= 0:
        missing.append("MISSING_RISK_CAPITAL")
    if fraction is None or fraction <= 0:
        missing.append("MISSING_RISK_FRACTION")
    result = {
        "status": "UNAVAILABLE",
        "decision": "NO_TRADE",
        "lot_count": None,
        "quantity": None,
        "premium_outlay": None,
        "one_lot_risk": None,
        "trade_risk_budget": None,
        "reasons": missing,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
    }
    if missing:
        return result
    one_lot = ask_value * lot + charges
    budget = capital * fraction
    if one_lot <= 0:
        result["reasons"] = ["INVALID_LOT_RISK"]
        return result
    lot_count = math.floor(budget / one_lot)
    result["one_lot_risk"] = one_lot
    result["trade_risk_budget"] = budget
    result["lot_count"] = lot_count
    if lot_count < 1:
        result["reasons"] = ["LOT_COUNT_BELOW_ONE"]
        return result
    result["status"] = "CALCULATED"
    result["quantity"] = lot_count * lot
    result["premium_outlay"] = ask_value * result["quantity"]
    result["reasons"] = []
    return result
