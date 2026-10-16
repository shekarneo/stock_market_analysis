"""Single source of truth for which underlyings the desk analyzes and trades.

Scope: NIFTY (NSE), SENSEX (BSE). BANKNIFTY was removed from scope; stored
rows that name it are kept as history, but new writes refuse it.
Lot size, tick size, and expiry are never stored here. They must come from
the caller or an instrument master.
"""

from __future__ import annotations

INDEX_UNDERLYINGS: tuple[str, ...] = ("NIFTY", "SENSEX")
"""Index underlyings with a forecast and an options path."""

COMMODITY_UNDERLYINGS: tuple[str, ...] = ("CRUDEOILMINI",)
"""Commodity underlyings traded on MCX."""

OPTION_UNDERLYINGS: tuple[str, ...] = ("NIFTY", "SENSEX", "CRUDEOILMINI")
"""Underlyings whose CE/PE inputs the options module accepts."""

FUTURES_UNDERLYINGS: tuple[str, ...] = ("CRUDEOILMINI",)
"""Underlyings where futures trading (LONG_FUT, SHORT_FUT) is allowed."""

TRADABLE_UNDERLYINGS: tuple[str, ...] = ("NIFTY", "SENSEX", "CRUDEOILMINI")
"""Every underlying a decision, registry entry, or risk allow-list may name."""

REMOVED_UNDERLYINGS: frozenset[str] = frozenset({"BANKNIFTY"})

OPTION_STRUCTURES: tuple[str, ...] = ("LONG_CE", "LONG_PE")
FUTURES_STRUCTURES: tuple[str, ...] = ("LONG_FUT", "SHORT_FUT")
ALL_STRUCTURES: tuple[str, ...] = OPTION_STRUCTURES + FUTURES_STRUCTURES

DECISIONS: tuple[str, ...] = ("NO_TRADE", "BUY_CE", "BUY_PE", "BUY_FUT", "SELL_FUT")


def canonical_underlying(name: str | None) -> str | None:
    """Normalize alias names to canonical identifiers."""
    if not name:
        return None
    upper = name.strip().upper()
    if upper in {"CRUDEMINI", "CRUDEOILM", "MCX_CRUDE_MINI", "CRUDEOILMINI"}:
        return "CRUDEOILMINI"
    return upper


def underlying_list_text(values: tuple[str, ...]) -> str:
    """'A, B, or C' for error messages, so wording follows the tuple."""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} or {values[1]}"
    return ", ".join(values[:-1]) + f", or {values[-1]}"
