"""Instrument master: the single place contract specifications are defined.

Every module that needs a lot size, strike step, or tick size reads it from here.
Values are exchange contract specifications as maintained by the operator and
must be re-checked against the exchange contract master whenever the exchange
revises them (lot sizes are revised periodically). A value that is not known is
None; callers must refuse to size or price rather than substitute a default.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.instruments import canonical_underlying

SPECS_REVIEWED_ON = "2026-10-22"
"""Date the values below were last checked against exchange contract specifications."""


@dataclass(frozen=True)
class InstrumentSpec:
    instrument: str
    exchange: str
    segment: str
    lot_size: int | None
    lot_unit: str
    strike_step: int | None
    option_tick_size: float | None
    futures_tick_size: float | None
    weekly_expiry_weekday: str | None


INSTRUMENT_SPECS: dict[str, InstrumentSpec] = {
    "NIFTY": InstrumentSpec(
        instrument="NIFTY",
        exchange="NSE",
        segment="FNO",
        lot_size=65,
        lot_unit="units",
        strike_step=50,
        option_tick_size=0.05,
        futures_tick_size=0.05,
        weekly_expiry_weekday="TUESDAY",
    ),
    "SENSEX": InstrumentSpec(
        instrument="SENSEX",
        exchange="BSE",
        segment="FNO",
        lot_size=20,
        lot_unit="units",
        strike_step=100,
        option_tick_size=0.05,
        futures_tick_size=0.05,
        weekly_expiry_weekday="THURSDAY",
    ),
    "CRUDEOILMINI": InstrumentSpec(
        instrument="CRUDEOILMINI",
        exchange="MCX",
        segment="COMMODITY",
        lot_size=10,
        lot_unit="barrels",
        strike_step=50,
        option_tick_size=None,
        futures_tick_size=1.0,
        weekly_expiry_weekday=None,
    ),
}


def get_spec(instrument: str | None) -> InstrumentSpec | None:
    """Return the spec for a tradable underlying, or None when it is not in the master."""
    canonical = canonical_underlying(instrument)
    if canonical is None:
        return None
    return INSTRUMENT_SPECS.get(canonical)


def lot_size_for(instrument: str | None) -> int | None:
    spec = get_spec(instrument)
    return spec.lot_size if spec else None


def strike_step_for(instrument: str | None) -> int | None:
    spec = get_spec(instrument)
    return spec.strike_step if spec else None
