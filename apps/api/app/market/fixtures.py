from __future__ import annotations

from datetime import date, datetime, timedelta

from app.market.calendar import ExchangeCalendar
from app.market.schemas import (
    IST,
    Candle,
    ContextObservation,
    DataOrigin,
    MarketSession,
    QualityStatus,
    Quote,
)

FIXTURE_DAY = date(2026, 1, 5)
CLOSED_TEST_DAY = date(2026, 1, 4)
SOURCE_ID = "synthetic_quiet_day"


def fixture_calendar() -> ExchangeCalendar:
    return ExchangeCalendar(listed_sessions={FIXTURE_DAY}, closed_dates={CLOSED_TEST_DAY})


def _bar(underlying: str, start: datetime, price: float, retrieved_at: datetime) -> Candle:
    return Candle(
        instrument_id=underlying,
        underlying=underlying,
        exchange=None,
        interval="M15",
        bar_start=start,
        bar_end=start + timedelta(minutes=15),
        provider_timestamp=None,
        retrieved_at=retrieved_at,
        open=price,
        high=price + 5,
        low=price - 5,
        close=price + 1,
        volume=None,
        source_id=SOURCE_ID,
        origin=DataOrigin.SYNTHETIC,
        session=MarketSession.OPEN,
    )


def quiet_day_candles(underlying: str, *, retrieved_at: datetime | None = None) -> list[Candle]:
    start = datetime(2026, 1, 5, 9, 15, tzinfo=IST)
    retrieved = retrieved_at or datetime(2026, 1, 5, 10, 15, tzinfo=IST)
    base = {"NIFTY": 10000.0, "SENSEX": 20000.0, "CRUDEOILMINI": 6500.0}[underlying]
    return [_bar(underlying, start + timedelta(minutes=15 * step), base + step, retrieved) for step in range(4)]


def quiet_day_quote(underlying: str, *, now: datetime) -> Quote:
    candles = quiet_day_candles(underlying, retrieved_at=now)
    last = candles[-1]
    return Quote(
        instrument_id=underlying,
        underlying=underlying,
        exchange=None,
        event_timestamp=last.bar_end,
        provider_timestamp=None,
        retrieved_at=now,
        last_price=last.close,
        open=candles[0].open,
        high=max(item.high for item in candles),
        low=min(item.low for item in candles),
        close=last.close,
        volume=None,
        source_id=SOURCE_ID,
        origin=DataOrigin.SYNTHETIC,
        session=MarketSession.CLOSED if now > last.bar_end else MarketSession.OPEN,
    )


def quiet_day_context(*, now: datetime) -> list[ContextObservation]:
    synthetic_at = datetime(2026, 1, 5, 10, 0, tzinfo=IST)
    present = [
        ("INDIA_VIX", 10.0, "index"),
        ("USDINR", 80.0, "INR per USD"),
        ("GOLD", 1000.0, "synthetic unit"),
    ]
    rows = [
        ContextObservation(
            code=code,
            value=value,
            unit=unit,
            event_timestamp=synthetic_at,
            retrieved_at=now,
            source_id=SOURCE_ID,
            origin=DataOrigin.SYNTHETIC,
            quality=QualityStatus.WARN,
            detail="Synthetic value for the quiet-day fixture. Not a market print.",
        )
        for code, value, unit in present
    ]
    for code in ("BRENT", "MCX_CRUDE", "WTI"):
        rows.append(
            ContextObservation(
                code=code,
                value=None,
                unit=None,
                event_timestamp=None,
                retrieved_at=now,
                source_id=SOURCE_ID,
                origin=DataOrigin.SYNTHETIC,
                quality=QualityStatus.WARN,
                detail="Field is present. No crude price is available in this fixture.",
            )
        )
    return rows
