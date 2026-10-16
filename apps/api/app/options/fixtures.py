"""Synthetic NIFTY chain for schema tests.

Every number below is a fixed software-test value. It is not a market print,
not a Groww quote, and not a model premium. Lot size, tick size, exchange, and
broker symbols are omitted because this fixture does not know them.
"""

from __future__ import annotations

FIXTURE_ORIGIN = "SYNTHETIC_FIXTURE"
FIXTURE_QUOTE = "2026-10-14T10:00:00+05:30"
FIXTURE_RETRIEVED = "2026-10-14T10:00:01+05:30"
FIXTURE_EXPIRY = "2026-10-20"
FIXTURE_UNDERLYING_PRICE = 25100.0

# Bid, ask, and last price are hand-written test numbers. They are not produced
# by Black-76 or by a vendor greek formula.
_QUOTES = (
    (25000, "CE", 180.0, 182.0, 181.0),
    (25000, "PE", 90.0, 92.0, 91.0),
    (25100, "CE", 140.0, 142.0, 141.0),
    (25100, "PE", 130.0, 132.0, 131.0),
    (25200, "CE", 100.0, 102.0, 101.0),
    (25200, "PE", 170.0, 172.0, 171.0),
)


def synthetic_nifty_chain() -> dict:
    """Return a new chain with the same contents on every call."""
    contracts = []
    for strike, option_type, bid, ask, ltp in _QUOTES:
        contracts.append(
            {
                "origin": FIXTURE_ORIGIN,
                "underlying": "NIFTY",
                "option_type": option_type,
                "strike": strike,
                "expiry": FIXTURE_EXPIRY,
                "underlying_price": FIXTURE_UNDERLYING_PRICE,
                "bid": bid,
                "ask": ask,
                "ltp": ltp,
                "quote_timestamp": FIXTURE_QUOTE,
                "trading_symbol": None,
                "groww_symbol": None,
                "lot_size": None,
                "tick_size": None,
                "volume": None,
                "open_interest": None,
                "open_interest_change": None,
                "greeks": {"delta": None, "gamma": None, "theta": None, "vega": None},
                "volatility": None,
            }
        )
    return {
        "schema_version": "m8-chain-1",
        "origin": FIXTURE_ORIGIN,
        "label": FIXTURE_ORIGIN,
        "underlying": "NIFTY",
        "expiry": FIXTURE_EXPIRY,
        "underlying_price": FIXTURE_UNDERLYING_PRICE,
        "quote_timestamp": FIXTURE_QUOTE,
        "retrieved_at": FIXTURE_RETRIEVED,
        "trading_symbol": None,
        "groww_symbol": None,
        "lot_size": None,
        "tick_size": None,
        "contracts": contracts,
        "real_market_data_verified": False,
        "market_observation": False,
    }
