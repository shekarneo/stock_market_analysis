"""Specified risk arithmetic. A missing component stays missing.

Session P&L is realized plus unrealized, minus booked charges, minus estimated
exit charges. None of those components is replaced with zero. Exit-charge
estimates have no configured schedule, so a ledger session does not produce a
P&L figure.
"""

from __future__ import annotations

from decimal import Decimal

from app.risk.money import decimal_or_none

_FLAGS = {
    "forecast_ready": False,
    "paper_approved": False,
    "live_approved": False,
    "real_market_data_verified": False,
}


def unrealized_mark(
    *,
    bid: object,
    average_entry_ask: object,
    filled_quantity: object,
    bid_fresh: object,
) -> dict:
    """Mark a long option. A stale bid uses the full premium, not a guessed price."""
    entry = decimal_or_none(average_entry_ask)
    quantity = decimal_or_none(filled_quantity)
    missing = []
    if entry is None or entry <= 0:
        missing.append("MISSING_ENTRY_ASK")
    if quantity is None or quantity <= 0:
        missing.append("MISSING_FILLED_QUANTITY")
    if bid_fresh is True:
        price = decimal_or_none(bid)
        if price is None or price <= 0:
            missing.append("MISSING_BID")
    elif bid_fresh is not False:
        missing.append("BID_FRESHNESS_UNKNOWN")
    if missing:
        return _unavailable(missing)
    if bid_fresh is True:
        return _calculated((decimal_or_none(bid) - entry) * quantity, "FRESH_BID")
    return _calculated(-(entry * quantity), "FULL_PREMIUM_LOSS")


def session_pnl(
    *,
    realized_pnl: object,
    unrealized_mark_value: object,
    charges_booked: object,
    exit_charges: object,
) -> dict:
    """Combine the four specified P&L terms. Each term must be supplied."""
    parts = {
        "realized_pnl": _supplied(realized_pnl),
        "unrealized_mark": _supplied(unrealized_mark_value),
        "charges_booked": _supplied(charges_booked),
        "exit_charges": _supplied(exit_charges),
    }
    missing = [name for name, value in parts.items() if value is None]
    if missing:
        return _unavailable([f"MISSING_{name.upper()}" for name in missing])
    value = parts["realized_pnl"] + parts["unrealized_mark"] - parts["charges_booked"] - parts["exit_charges"]
    return _calculated(value, "SESSION_PNL")


def deployable_amounts(*, paper_cash: object, risk_capital: object, reserved: object, open_premium: object, cash_buffer_fraction: object) -> dict:
    """Paper deployable cash and the remaining aggregate budget."""
    cash = _supplied(paper_cash)
    capital = _supplied(risk_capital)
    held = _supplied(reserved)
    premium = _supplied(open_premium)
    buffer = _supplied(cash_buffer_fraction)
    missing = []
    if cash is None:
        missing.append("MISSING_PAPER_CASH")
    if capital is None:
        missing.append("MISSING_RISK_CAPITAL")
    if held is None:
        missing.append("MISSING_RESERVED")
    if premium is None:
        missing.append("MISSING_OPEN_PREMIUM")
    if buffer is None:
        missing.append("MISSING_CASH_BUFFER")
    if missing:
        result = _unavailable(missing)
        result["deployable"] = None
        result["aggregate_remaining"] = None
        return result
    result = _calculated(None, "DEPLOYABLE")
    result["deployable"] = cash * (Decimal("1") - buffer)
    result["aggregate_remaining"] = capital - held - premium
    return result


def _supplied(value: object) -> Decimal | None:
    if value is None:
        return None
    return decimal_or_none(value)


def _unavailable(reasons: list[str]) -> dict:
    return {
        "status": "UNAVAILABLE",
        "value": None,
        "label": None,
        "reasons": reasons,
        **_FLAGS,
    }


def _calculated(value: Decimal | None, label: str) -> dict:
    return {
        "status": "CALCULATED",
        "value": value,
        "label": label,
        "reasons": [],
        **_FLAGS,
    }
