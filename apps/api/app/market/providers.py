from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.market.fixtures import quiet_day_candles, quiet_day_context, quiet_day_quote
from app.market.schemas import (
    IST,
    Candle,
    ContextObservation,
    DataOrigin,
    MarketSession,
    Quote,
    RetrievalFailure,
    require_aware,
)

from app.instruments import INDEX_UNDERLYINGS, TRADABLE_UNDERLYINGS

INDEXES = INDEX_UNDERLYINGS
GROWW_DOCUMENTED_QUOTE_SYMBOL = "NIFTY"


class QuoteTransport(Protocol):
    def get_quote(self, trading_symbol: str) -> dict: ...


class MarketDataProvider(Protocol):
    provider_id: str

    def get_quote(self, underlying: str, *, now: datetime) -> Quote | RetrievalFailure: ...

    def get_candles(self, underlying: str, *, retrieved_at: datetime) -> list[Candle] | RetrievalFailure: ...

    def get_context(self, *, now: datetime) -> list[ContextObservation]: ...


class SyntheticProvider:
    provider_id = "synthetic"

    def get_quote(self, underlying: str, *, now: datetime) -> Quote | RetrievalFailure:
        now = require_aware(now, "now")
        if underlying not in TRADABLE_UNDERLYINGS:
            return RetrievalFailure(
                code="UNKNOWN_INSTRUMENT",
                message=f"{underlying} is not a synthetic index in the quiet-day fixture.",
                origin=DataOrigin.SYNTHETIC,
            )
        return quiet_day_quote(underlying, now=now)

    def get_candles(self, underlying: str, *, retrieved_at: datetime) -> list[Candle] | RetrievalFailure:
        retrieved_at = require_aware(retrieved_at, "retrieved_at")
        if underlying not in TRADABLE_UNDERLYINGS:
            return RetrievalFailure(
                code="UNKNOWN_INSTRUMENT",
                message=f"{underlying} is not a synthetic index in the quiet-day fixture.",
                origin=DataOrigin.SYNTHETIC,
            )
        return quiet_day_candles(underlying, retrieved_at=retrieved_at)

    def get_context(self, *, now: datetime) -> list[ContextObservation]:
        return quiet_day_context(now=require_aware(now, "now"))


class GrowwReadProvider:
    """Maps a caller-supplied get_quote payload. It does not open a socket or import growwapi.

    Historical candles are refused because the replacement schema is unverified.
    SENSEX quotes are refused because that index symbol is unverified.
    """

    provider_id = "groww"

    def __init__(self, transport: QuoteTransport | None = None) -> None:
        self.transport = transport
        self.network_calls = 0

    def get_quote(self, underlying: str, *, now: datetime) -> Quote | RetrievalFailure:
        now = require_aware(now, "now")
        if underlying != GROWW_DOCUMENTED_QUOTE_SYMBOL:
            return RetrievalFailure(
                code="UNVERIFIED_SYMBOL",
                message="Only the documented NIFTY quote example is mapped. This was not an authenticated call.",
                origin=None,
            )
        if self.transport is None:
            return RetrievalFailure(
                code="GROWW_NOT_VERIFIED",
                message="No authenticated Groww call has been made. Live quotes are not available.",
                origin=None,
            )
        self.network_calls += 1
        try:
            payload = self.transport.get_quote("NIFTY")
        except TimeoutError:
            return RetrievalFailure(
                code="PROVIDER_TIMEOUT",
                message="The quote transport timed out. No quote was created.",
                origin=None,
            )
        except OSError as exc:
            return RetrievalFailure(
                code="PROVIDER_ERROR",
                message=f"The quote transport failed: {exc.__class__.__name__}.",
                origin=None,
            )
        return normalize_documented_quote(payload, retrieved_at=now)

    def get_candles(self, underlying: str, *, retrieved_at: datetime) -> RetrievalFailure:
        return RetrievalFailure(
            code="CANDLE_BOUNDARY_UNVERIFIED",
            message=(
                "The Groww candle timestamp role and timezone are unverified. "
                "This path does not create candles and does not send a request."
            ),
            origin=None,
        )

    def get_context(self, *, now: datetime) -> list[ContextObservation]:
        return []


def normalize_documented_quote(payload: dict, *, retrieved_at: datetime) -> Quote | RetrievalFailure:
    if not isinstance(payload, dict):
        return RetrievalFailure(code="INVALID_PAYLOAD", message="Quote payload must be an object.", origin=None)
    ohlc = payload.get("ohlc")
    if not isinstance(ohlc, dict):
        return RetrievalFailure(
            code="MISSING_FIELD",
            message="Documented get_quote payload has no ohlc object.",
            origin=DataOrigin.DOCUMENTED_SAMPLE,
        )
    required = ("open", "high", "low", "close")
    if any(name not in ohlc for name in required) or "last_price" not in payload or "last_trade_time" not in payload:
        return RetrievalFailure(
            code="MISSING_FIELD",
            message="Documented quote fields last_price, last_trade_time, or ohlc are missing.",
            origin=DataOrigin.DOCUMENTED_SAMPLE,
        )
    event = datetime.fromtimestamp(int(payload["last_trade_time"]) / 1000, tz=IST)
    volume = payload.get("volume")
    return Quote(
        instrument_id="NIFTY",
        underlying="NIFTY",
        exchange="NSE",
        event_timestamp=event,
        provider_timestamp=event,
        retrieved_at=retrieved_at,
        last_price=float(payload["last_price"]),
        open=float(ohlc["open"]),
        high=float(ohlc["high"]),
        low=float(ohlc["low"]),
        close=float(ohlc["close"]),
        volume=None if volume is None else float(volume),
        source_id="groww_documented_sample",
        origin=DataOrigin.DOCUMENTED_SAMPLE,
        session=MarketSession.UNKNOWN,
    )
