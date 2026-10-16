"""Typed chain snapshot. A snapshot is built only after validation accepts the chain.

This module does not price a contract. Exchange, lot size, and broker symbols
stay null unless the caller supplied them. Nothing here invents those values.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.options.validation import CHAIN_SCHEMA, validate_option_chain


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OptionGreeks(StrictModel):
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None


class OptionVolatility(StrictModel):
    value: float
    scale: Literal["PERCENT", "DECIMAL"]


class OptionContractRecord(StrictModel):
    origin: Literal["UNVERIFIED_MARKET_INPUT", "SYNTHETIC_FIXTURE", "CALCULATED"] | None
    underlying: Literal["NIFTY", "SENSEX", "CRUDEOILMINI"] | None
    option_type: Literal["CE", "PE"] | None
    strike: float | None
    expiry: str | None
    underlying_price: float | None
    bid: float | None
    ask: float | None
    ltp: float | None = None
    premium: None = None
    quote_timestamp: str | None
    trading_symbol: str | None = None
    groww_symbol: str | None = None
    broker_symbol: str | None = None
    lot_size: float | None = None
    tick_size: float | None = None
    volume: float | None = None
    open_interest: float | None = None
    open_interest_change: float | None = None
    greeks: OptionGreeks
    volatility: OptionVolatility | None = None
    interest_rate: dict | None = None


class OptionChainSnapshot(StrictModel):
    schema_version: Literal["m8-chain-1"]
    origin: Literal["UNVERIFIED_MARKET_INPUT", "SYNTHETIC_FIXTURE", "CALCULATED"]
    underlying: Literal["NIFTY", "SENSEX", "CRUDEOILMINI"]
    expiry: str
    underlying_price: float
    quote_timestamp: str
    retrieved_at: str | None = None
    trading_symbol: str | None = None
    groww_symbol: str | None = None
    broker_symbol: str | None = None
    lot_size: float | None = None
    tick_size: float | None = None
    contracts: list[OptionContractRecord]
    pricing_status: Literal["UNAVAILABLE"]
    expected_net: None = None
    decision: Literal["NO_TRADE"]
    decision_reason: Literal["NO_APPROVED_FORECAST"]
    forecast_accepted: Literal[False]
    forecast_ready: Literal[False]
    paper_approved: Literal[False]
    live_approved: Literal[False]
    real_market_data_verified: Literal[False]


def parse_option_chain(payload: dict, *, as_of=None) -> tuple[OptionChainSnapshot | None, dict]:
    """Return a typed snapshot only when validate_option_chain accepts the payload."""
    report = validate_option_chain(payload, as_of=as_of)
    if not report["ok"] or report["snapshot"] is None:
        return None, report
    if report["snapshot"]["schema_version"] != CHAIN_SCHEMA:
        return None, report
    return OptionChainSnapshot.model_validate(report["snapshot"]), report
