"""Exchange session intelligence, cross-market data freshness, and post-close analysis.

Milestone M13:
Authoritative session models, timezone-aware schedules, dynamic US DST handling
for MCX sessions, fine-grained freshness policies, cross-market snapshot aggregation,
and post-close contextual analysis for the V6 Indian Market Analysis & Quantitative
Forecasting System.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

IST = ZoneInfo("Asia/Kolkata")
ET = ZoneInfo("America/New_York")
UTC = timezone.utc


class MarketSegment(str, Enum):
    NSE_CASH = "NSE_CASH"
    BSE_CASH = "BSE_CASH"
    NSE_DERIVATIVES = "NSE_DERIVATIVES"
    MCX_COMMODITY = "MCX_COMMODITY"
    INTERNATIONAL_COMMODITY = "INTERNATIONAL_COMMODITY"
    US_EQUITY = "US_EQUITY"
    US_TREASURY = "US_TREASURY"
    FOREX = "FOREX"
    MARKET_INDICATOR = "MARKET_INDICATOR"


class MarketState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PRE_OPEN = "PRE_OPEN"
    POST_CLOSE = "POST_CLOSE"
    UNKNOWN = "UNKNOWN"


class SessionPhase(str, Enum):
    PRE_OPEN = "PRE_OPEN"
    REGULAR = "REGULAR"
    POST_CLOSE = "POST_CLOSE"
    EVENING = "EVENING"
    SPECIAL = "SPECIAL"
    CLOSED = "CLOSED"


class FreshnessStatus(str, Enum):
    LIVE = "LIVE"
    FRESH = "FRESH"
    DELAYED = "DELAYED"
    STALE = "STALE"
    CLOSED_SESSION_VALID = "CLOSED_SESSION_VALID"
    UNAVAILABLE = "UNAVAILABLE"
    INCOMPLETE_CANDLE = "INCOMPLETE_CANDLE"
    UNVERIFIED = "UNVERIFIED"
    UNKNOWN = "UNKNOWN"


# --- Authoritative Exchange Holidays (Standard Indian Market Holidays) ---
# Note: In accordance with SEBI/NSE/BSE exchange circulars.
NSE_BSE_HOLIDAYS_2026: set[date] = {
    date(2026, 1, 26),  # Republic Day
    date(2026, 3, 3),   # Holi
    date(2026, 3, 20),  # Id-Ul-Fitr
    date(2026, 3, 27),  # Ram Navami
    date(2026, 4, 3),   # Good Friday
    date(2026, 4, 14),  # Dr. Baba Saheb Ambedkar Jayanti
    date(2026, 5, 1),   # Maharashtra Day
    date(2026, 5, 27),  # Bakri Id / Eid-ul-Adha
    date(2026, 6, 26),  # Muharram
    date(2026, 8, 15),  # Independence Day
    date(2026, 10, 2),  # Mahatma Gandhi Jayanti
    date(2026, 10, 20), # Dussehra
    date(2026, 11, 8),  # Diwali Laxmi Pujan (Muhurat session only)
    date(2026, 11, 10), # Diwali Balipratipada
    date(2026, 11, 24), # Guru Nanak Jayanti
    date(2026, 12, 25), # Christmas
}

# MCX Holidays: Morning closed (09:00-17:00), Evening open (17:00-23:30/23:55)
MCX_EVENING_ONLY_HOLIDAYS_2026: set[date] = {
    date(2026, 3, 3),   # Holi
    date(2026, 3, 27),  # Ram Navami
    date(2026, 4, 14),  # Ambedkar Jayanti
    date(2026, 5, 1),   # Maharashtra Day
    date(2026, 5, 27),  # Bakri Id
    date(2026, 6, 26),  # Muharram
    date(2026, 10, 20), # Dussehra
    date(2026, 11, 24), # Guru Nanak Jayanti
}

# Full day closures for MCX (both sessions closed)
MCX_FULL_CLOSURES_2026: set[date] = {
    date(2026, 1, 26),  # Republic Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 8, 15),  # Independence Day
    date(2026, 10, 2),  # Mahatma Gandhi Jayanti
    date(2026, 12, 25), # Christmas
}

# Diwali Muhurat Trading Special Session Date & Window
DIWALI_MUHURAT_2026_DATE = date(2026, 11, 8)
DIWALI_MUHURAT_START = time(18, 0)
DIWALI_MUHURAT_END = time(19, 15)


def is_us_daylight_saving_time(dt: datetime) -> bool:
    """Return True if US Daylight Saving Time (EDT) is active for the given moment.

    Determined authoritatively using ZoneInfo('America/New_York').
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    et_dt = dt.astimezone(ET)
    dst_offset = et_dt.dst()
    return dst_offset is not None and dst_offset.total_seconds() > 0


@dataclass(frozen=True)
class FreshnessPolicy:
    warn_seconds: int
    stale_seconds: int
    allow_closed_retention: bool = True


@dataclass(frozen=True)
class InstrumentSessionConfig:
    instrument: str
    exchange: str
    segment: MarketSegment
    tz: ZoneInfo
    pre_open_start: time | None = None
    pre_open_end: time | None = None
    regular_open: time = time(9, 15)
    regular_close: time = time(15, 30)
    post_close_start: time | None = None
    post_close_end: time | None = None
    freshness: FreshnessPolicy = FreshnessPolicy(warn_seconds=60, stale_seconds=180)
    notes: str = ""


# Default session policies for all supported categories
_FRESHNESS_EQUITY = FreshnessPolicy(warn_seconds=60, stale_seconds=180)
_FRESHNESS_COMMODITY = FreshnessPolicy(warn_seconds=120, stale_seconds=300)
_FRESHNESS_GLOBAL = FreshnessPolicy(warn_seconds=300, stale_seconds=900)
_FRESHNESS_MACRO = FreshnessPolicy(warn_seconds=86400, stale_seconds=172800)


def get_instrument_session_config(instrument: str) -> InstrumentSessionConfig:
    """Return the authoritative session configuration for a given instrument."""
    inst = instrument.strip().upper()

    # 1. NSE Cash Equities & Indices
    if inst in {"NIFTY", "BANKNIFTY", "NIFTYIT", "NIFTYAUTO", "NIFTYMETAL", "NIFTY_MIDCAP"}:
        return InstrumentSessionConfig(
            instrument=inst,
            exchange="NSE",
            segment=MarketSegment.NSE_CASH,
            tz=IST,
            pre_open_start=time(9, 0),
            pre_open_end=time(9, 15),
            regular_open=time(9, 15),
            regular_close=time(15, 30),
            post_close_start=time(15, 30),
            post_close_end=time(16, 0),
            freshness=_FRESHNESS_EQUITY,
            notes="NSE Cash Market with pre-open (09:00-09:15) and closing auction (15:30-16:00).",
        )

    # 2. BSE Cash Equities & Indices
    if inst in {"SENSEX", "BANKEX"}:
        return InstrumentSessionConfig(
            instrument=inst,
            exchange="BSE",
            segment=MarketSegment.BSE_CASH,
            tz=IST,
            pre_open_start=time(9, 0),
            pre_open_end=time(9, 15),
            regular_open=time(9, 15),
            regular_close=time(15, 30),
            post_close_start=time(15, 30),
            post_close_end=time(16, 0),
            freshness=_FRESHNESS_EQUITY,
            notes="BSE Cash Market with pre-open and closing auction.",
        )

    # 3. NSE Equity Derivatives
    if inst in {"NIFTY_FUT", "BANKNIFTY_FUT", "NIFTY_CE", "NIFTY_PE"}:
        return InstrumentSessionConfig(
            instrument=inst,
            exchange="NSE",
            segment=MarketSegment.NSE_DERIVATIVES,
            tz=IST,
            pre_open_start=None,  # No pre-open for derivatives
            pre_open_end=None,
            regular_open=time(9, 15),
            regular_close=time(15, 30),
            post_close_start=None,
            post_close_end=None,
            freshness=_FRESHNESS_EQUITY,
            notes="NSE Equity Derivatives (Futures & Options). Continuous session 09:15-15:30.",
        )

    # 4. MCX Commodity Contracts
    if inst in {"CRUDE", "CRUDEOILMINI", "CRUDEMINI", "GOLDMINI", "SILVERMINI", "NATURALGASMINI", "MCX_CRUDE"}:
        return InstrumentSessionConfig(
            instrument=inst,
            exchange="MCX",
            segment=MarketSegment.MCX_COMMODITY,
            tz=IST,
            pre_open_start=time(8, 45),
            pre_open_end=time(8, 59),
            regular_open=time(9, 0),
            regular_close=time(23, 30),  # Adjusted dynamically to 23:55 during winter
            post_close_start=time(23, 30),
            post_close_end=time(23, 45),
            freshness=_FRESHNESS_COMMODITY,
            notes="MCX Commodity Contract trading until 23:30 (US DST) or 23:55 (US Standard Time).",
        )

    # 5. International Commodity Benchmarks
    if inst in {"BRENT", "WTI"}:
        return InstrumentSessionConfig(
            instrument=inst,
            exchange="ICE/NYMEX",
            segment=MarketSegment.INTERNATIONAL_COMMODITY,
            tz=ET,
            regular_open=time(18, 0),  # Sunday 18:00 ET to Friday 17:00 ET
            regular_close=time(17, 0),
            freshness=_FRESHNESS_GLOBAL,
            notes="International crude benchmark. Near 24h electronic trading with 17:00-18:00 ET daily break.",
        )

    # 6. US Equity Indices
    if inst in {"DJI", "DOWFUTURES", "SPX", "IXIC", "DOW_JONES"}:
        return InstrumentSessionConfig(
            instrument=inst,
            exchange="NYSE/CME",
            segment=MarketSegment.US_EQUITY,
            tz=ET,
            regular_open=time(9, 30) if inst != "DOWFUTURES" else time(18, 0),
            regular_close=time(16, 0) if inst != "DOWFUTURES" else time(17, 0),
            freshness=_FRESHNESS_GLOBAL,
            notes="US Equities / Futures in America/New_York timezone.",
        )

    # 7. US Treasury Yields
    if inst in {"US10Y", "US02Y", "US30Y"}:
        return InstrumentSessionConfig(
            instrument=inst,
            exchange="SIFMA/TREASURY",
            segment=MarketSegment.US_TREASURY,
            tz=ET,
            regular_open=time(8, 0),
            regular_close=time(17, 0),
            freshness=_FRESHNESS_MACRO,
            notes="US Treasury Yield indicators. Benchmark daily publication.",
        )

    # 8. Forex (USD/INR)
    if inst in {"USDINR", "USD_INR"}:
        return InstrumentSessionConfig(
            instrument=inst,
            exchange="NSE_CDS",
            segment=MarketSegment.FOREX,
            tz=IST,
            regular_open=time(9, 0),
            regular_close=time(17, 0),
            freshness=_FRESHNESS_EQUITY,
            notes="NSE Currency Derivatives / RBI Reference session 09:00-17:00 IST.",
        )

    # 9. India VIX & Market Derived Indicators
    if inst in {"VIX", "INDIAVIX", "INDIA_VIX"}:
        return InstrumentSessionConfig(
            instrument=inst,
            exchange="NSE",
            segment=MarketSegment.MARKET_INDICATOR,
            tz=IST,
            regular_open=time(9, 15),
            regular_close=time(15, 30),
            freshness=_FRESHNESS_EQUITY,
            notes="India VIX calculated during NSE equity hours 09:15-15:30 IST.",
        )

    # Other global indices
    if inst in {"GIFTNIFTY", "GIFT_NIFTY"}:
        return InstrumentSessionConfig(
            instrument=inst,
            exchange="NSE_IX",
            segment=MarketSegment.INTERNATIONAL_COMMODITY,
            tz=IST,
            regular_open=time(6, 30),
            regular_close=time(2, 45),  # 21 hours across midnight
            freshness=_FRESHNESS_GLOBAL,
            notes="GIFT City IFSC trading session 06:30 to 02:45 IST.",
        )

    if inst in {"NIKKEI", "HANGSENG"}:
        return InstrumentSessionConfig(
            instrument=inst,
            exchange="TSE/HKEX",
            segment=MarketSegment.US_EQUITY,
            tz=IST,
            regular_open=time(6, 30),
            regular_close=time(13, 30),
            freshness=_FRESHNESS_GLOBAL,
            notes="Asian market session.",
        )

    # Safe fallback
    return InstrumentSessionConfig(
        instrument=inst,
        exchange="UNKNOWN",
        segment=MarketSegment.NSE_CASH,
        tz=IST,
        regular_open=time(9, 15),
        regular_close=time(15, 30),
        freshness=_FRESHNESS_EQUITY,
        notes="Unrecognized instrument; defaulting to standard 09:15-15:30 IST session.",
    )


class SessionAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument: str
    exchange: str
    segment: MarketSegment
    market_state: MarketState
    session_phase: SessionPhase
    is_open: bool
    as_of: datetime
    timezone_name: str
    session_open: datetime | None = None
    session_close: datetime | None = None
    authoritative: bool
    limitation: str | None = None


def assess_market_session(instrument: str, as_of: datetime) -> SessionAssessment:
    """Assess market session status for an instrument as of the supplied timestamp.

    Deterministic time injection: `as_of` must be timezone-aware.
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")

    cfg = get_instrument_session_config(instrument)
    local_dt = as_of.astimezone(cfg.tz)
    local_date = local_dt.date()
    local_time = local_dt.time()
    weekday = local_dt.weekday()  # 0=Monday, 5=Saturday, 6=Sunday

    # Handle MCX dynamic close time based on US DST
    mcx_close_time = time(23, 30) if is_us_daylight_saving_time(as_of) else time(23, 55)

    # 1. Check Weekend
    if weekday in (5, 6):
        # Special check: Diwali Muhurat on weekend
        if local_date == DIWALI_MUHURAT_2026_DATE and DIWALI_MUHURAT_START <= local_time <= DIWALI_MUHURAT_END:
            return SessionAssessment(
                instrument=cfg.instrument,
                exchange=cfg.exchange,
                segment=cfg.segment,
                market_state=MarketState.OPEN,
                session_phase=SessionPhase.SPECIAL,
                is_open=True,
                as_of=as_of,
                timezone_name=str(cfg.tz),
                session_open=datetime.combine(local_date, DIWALI_MUHURAT_START, tzinfo=cfg.tz),
                session_close=datetime.combine(local_date, DIWALI_MUHURAT_END, tzinfo=cfg.tz),
                authoritative=True,
                limitation="Special Diwali Muhurat trading session.",
            )
        return SessionAssessment(
            instrument=cfg.instrument,
            exchange=cfg.exchange,
            segment=cfg.segment,
            market_state=MarketState.CLOSED,
            session_phase=SessionPhase.CLOSED,
            is_open=False,
            as_of=as_of,
            timezone_name=str(cfg.tz),
            authoritative=True,
            limitation="Closed for regular weekend.",
        )

    # 2. Check Exchange Holidays
    if cfg.exchange in ("NSE", "BSE"):
        if local_date in NSE_BSE_HOLIDAYS_2026:
            # Check special Diwali Muhurat session
            if local_date == DIWALI_MUHURAT_2026_DATE and DIWALI_MUHURAT_START <= local_time <= DIWALI_MUHURAT_END:
                return SessionAssessment(
                    instrument=cfg.instrument,
                    exchange=cfg.exchange,
                    segment=cfg.segment,
                    market_state=MarketState.OPEN,
                    session_phase=SessionPhase.SPECIAL,
                    is_open=True,
                    as_of=as_of,
                    timezone_name=str(cfg.tz),
                    session_open=datetime.combine(local_date, DIWALI_MUHURAT_START, tzinfo=cfg.tz),
                    session_close=datetime.combine(local_date, DIWALI_MUHURAT_END, tzinfo=cfg.tz),
                    authoritative=True,
                    limitation="Special Diwali Muhurat trading session.",
                )
            return SessionAssessment(
                instrument=cfg.instrument,
                exchange=cfg.exchange,
                segment=cfg.segment,
                market_state=MarketState.CLOSED,
                session_phase=SessionPhase.CLOSED,
                is_open=False,
                as_of=as_of,
                timezone_name=str(cfg.tz),
                authoritative=True,
                limitation=f"Official {cfg.exchange} holiday on {local_date.isoformat()}.",
            )

    if cfg.exchange == "MCX":
        if local_date in MCX_FULL_CLOSURES_2026:
            return SessionAssessment(
                instrument=cfg.instrument,
                exchange="MCX",
                segment=cfg.segment,
                market_state=MarketState.CLOSED,
                session_phase=SessionPhase.CLOSED,
                is_open=False,
                as_of=as_of,
                timezone_name=str(cfg.tz),
                authoritative=True,
                limitation=f"Official MCX full-day holiday on {local_date.isoformat()}.",
            )
        if local_date in MCX_EVENING_ONLY_HOLIDAYS_2026:
            # Morning closed 09:00-17:00, Evening open 17:00 to 23:30/23:55
            evening_start = time(17, 0)
            if local_time < evening_start:
                return SessionAssessment(
                    instrument=cfg.instrument,
                    exchange="MCX",
                    segment=cfg.segment,
                    market_state=MarketState.CLOSED,
                    session_phase=SessionPhase.CLOSED,
                    is_open=False,
                    as_of=as_of,
                    timezone_name=str(cfg.tz),
                    session_open=datetime.combine(local_date, evening_start, tzinfo=cfg.tz),
                    session_close=datetime.combine(local_date, mcx_close_time, tzinfo=cfg.tz),
                    authoritative=True,
                    limitation="MCX morning session closed for holiday; evening session opens at 17:00 IST.",
                )
            elif evening_start <= local_time <= mcx_close_time:
                return SessionAssessment(
                    instrument=cfg.instrument,
                    exchange="MCX",
                    segment=cfg.segment,
                    market_state=MarketState.OPEN,
                    session_phase=SessionPhase.EVENING,
                    is_open=True,
                    as_of=as_of,
                    timezone_name=str(cfg.tz),
                    session_open=datetime.combine(local_date, evening_start, tzinfo=cfg.tz),
                    session_close=datetime.combine(local_date, mcx_close_time, tzinfo=cfg.tz),
                    authoritative=True,
                    limitation="MCX holiday evening session active.",
                )
            else:
                return SessionAssessment(
                    instrument=cfg.instrument,
                    exchange="MCX",
                    segment=cfg.segment,
                    market_state=MarketState.CLOSED,
                    session_phase=SessionPhase.CLOSED,
                    is_open=False,
                    as_of=as_of,
                    timezone_name=str(cfg.tz),
                    authoritative=True,
                    limitation="MCX evening session closed for the night.",
                )

    # 3. Regular Session Hours Evaluation
    effective_close = mcx_close_time if cfg.exchange == "MCX" else cfg.regular_close

    # Pre-open window
    if cfg.pre_open_start and cfg.pre_open_end and cfg.pre_open_start <= local_time < cfg.pre_open_end:
        return SessionAssessment(
            instrument=cfg.instrument,
            exchange=cfg.exchange,
            segment=cfg.segment,
            market_state=MarketState.PRE_OPEN,
            session_phase=SessionPhase.PRE_OPEN,
            is_open=False,
            as_of=as_of,
            timezone_name=str(cfg.tz),
            session_open=datetime.combine(local_date, cfg.regular_open, tzinfo=cfg.tz),
            session_close=datetime.combine(local_date, effective_close, tzinfo=cfg.tz),
            authoritative=True,
            limitation=f"{cfg.exchange} Pre-Open order matching session.",
        )

    # Regular trading window
    if cfg.regular_open <= local_time <= effective_close:
        phase = SessionPhase.EVENING if (cfg.exchange == "MCX" and local_time >= time(17, 0)) else SessionPhase.REGULAR
        return SessionAssessment(
            instrument=cfg.instrument,
            exchange=cfg.exchange,
            segment=cfg.segment,
            market_state=MarketState.OPEN,
            session_phase=phase,
            is_open=True,
            as_of=as_of,
            timezone_name=str(cfg.tz),
            session_open=datetime.combine(local_date, cfg.regular_open, tzinfo=cfg.tz),
            session_close=datetime.combine(local_date, effective_close, tzinfo=cfg.tz),
            authoritative=True,
        )

    # Post-close auction window
    if cfg.post_close_start and cfg.post_close_end and cfg.post_close_start < local_time <= cfg.post_close_end:
        return SessionAssessment(
            instrument=cfg.instrument,
            exchange=cfg.exchange,
            segment=cfg.segment,
            market_state=MarketState.POST_CLOSE,
            session_phase=SessionPhase.POST_CLOSE,
            is_open=False,
            as_of=as_of,
            timezone_name=str(cfg.tz),
            session_open=datetime.combine(local_date, cfg.regular_open, tzinfo=cfg.tz),
            session_close=datetime.combine(local_date, effective_close, tzinfo=cfg.tz),
            authoritative=True,
            limitation=f"{cfg.exchange} Post-close closing price calculation / trade modification window.",
        )

    # Outside regular session
    return SessionAssessment(
        instrument=cfg.instrument,
        exchange=cfg.exchange,
        segment=cfg.segment,
        market_state=MarketState.CLOSED,
        session_phase=SessionPhase.CLOSED,
        is_open=False,
        as_of=as_of,
        timezone_name=str(cfg.tz),
        session_open=datetime.combine(local_date, cfg.regular_open, tzinfo=cfg.tz),
        session_close=datetime.combine(local_date, effective_close, tzinfo=cfg.tz),
        authoritative=True,
        limitation="Outside regular exchange trading hours.",
    )


class FreshnessAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument: str
    freshness_status: FreshnessStatus
    age_seconds: float | None
    warn_threshold_seconds: int
    stale_threshold_seconds: int
    event_timestamp: datetime | None = None
    provider_timestamp: datetime | None = None
    retrieved_at: datetime | None = None
    reason: str


def assess_observation_freshness(
    instrument: str,
    as_of: datetime,
    *,
    event_timestamp: datetime | None = None,
    retrieved_at: datetime | None = None,
    provider_timestamp: datetime | None = None,
    market_state: MarketState = MarketState.OPEN,
) -> FreshnessAssessment:
    """Assess freshness of an observation taking session status and instrument policy into account.

    Never mark LIVE solely because the API returned successfully.
    When a market is CLOSED, the last valid price remains legitimate context rather than STALE.
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")

    cfg = get_instrument_session_config(instrument)
    policy = cfg.freshness

    effective_ts = event_timestamp or provider_timestamp or retrieved_at
    if effective_ts is None:
        return FreshnessAssessment(
            instrument=cfg.instrument,
            freshness_status=FreshnessStatus.UNAVAILABLE,
            age_seconds=None,
            warn_threshold_seconds=policy.warn_seconds,
            stale_threshold_seconds=policy.stale_seconds,
            reason="No event, provider, or retrieval timestamp was present.",
        )

    if effective_ts.tzinfo is None:
        return FreshnessAssessment(
            instrument=cfg.instrument,
            freshness_status=FreshnessStatus.UNVERIFIED,
            age_seconds=None,
            warn_threshold_seconds=policy.warn_seconds,
            stale_threshold_seconds=policy.stale_seconds,
            reason="Observation timestamp was naive and could not establish authoritative freshness.",
        )

    age = (as_of - effective_ts).total_seconds()

    # If the market is CLOSED, an observation from the session close is VALID context, NOT STALE
    if market_state in (MarketState.CLOSED, MarketState.POST_CLOSE):
        return FreshnessAssessment(
            instrument=cfg.instrument,
            freshness_status=FreshnessStatus.CLOSED_SESSION_VALID,
            age_seconds=age,
            warn_threshold_seconds=policy.warn_seconds,
            stale_threshold_seconds=policy.stale_seconds,
            event_timestamp=event_timestamp,
            provider_timestamp=provider_timestamp,
            retrieved_at=retrieved_at,
            reason="Market session is closed. Retaining official closing price context.",
        )

    # During OPEN / PRE_OPEN:
    if age < 0:
        return FreshnessAssessment(
            instrument=cfg.instrument,
            freshness_status=FreshnessStatus.UNVERIFIED,
            age_seconds=age,
            warn_threshold_seconds=policy.warn_seconds,
            stale_threshold_seconds=policy.stale_seconds,
            event_timestamp=event_timestamp,
            provider_timestamp=provider_timestamp,
            retrieved_at=retrieved_at,
            reason="Timestamp is in the future relative to observation moment.",
        )

    if age <= policy.warn_seconds:
        status = FreshnessStatus.LIVE if age <= 30 else FreshnessStatus.FRESH
        return FreshnessAssessment(
            instrument=cfg.instrument,
            freshness_status=status,
            age_seconds=age,
            warn_threshold_seconds=policy.warn_seconds,
            stale_threshold_seconds=policy.stale_seconds,
            event_timestamp=event_timestamp,
            provider_timestamp=provider_timestamp,
            retrieved_at=retrieved_at,
            reason=f"Observation is active ({int(age)}s age).",
        )

    if age <= policy.stale_seconds:
        return FreshnessAssessment(
            instrument=cfg.instrument,
            freshness_status=FreshnessStatus.DELAYED,
            age_seconds=age,
            warn_threshold_seconds=policy.warn_seconds,
            stale_threshold_seconds=policy.stale_seconds,
            event_timestamp=event_timestamp,
            provider_timestamp=provider_timestamp,
            retrieved_at=retrieved_at,
            reason=f"Observation is delayed past warn threshold ({int(age)}s > {policy.warn_seconds}s).",
        )

    return FreshnessAssessment(
        instrument=cfg.instrument,
        freshness_status=FreshnessStatus.STALE,
        age_seconds=age,
        warn_threshold_seconds=policy.warn_seconds,
        stale_threshold_seconds=policy.stale_seconds,
        event_timestamp=event_timestamp,
        provider_timestamp=provider_timestamp,
        retrieved_at=retrieved_at,
        reason=f"Quote is stale during active market session ({int(age)}s > {policy.stale_seconds}s).",
    )


class CandleFreshnessAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument: str
    bar_start: datetime
    bar_end: datetime
    is_complete: bool
    status: FreshnessStatus
    reason: str


def assess_candle_freshness(
    instrument: str,
    as_of: datetime,
    bar_start: datetime,
    bar_end: datetime,
) -> CandleFreshnessAssessment:
    """Assess whether a candle is complete or an unfinished bar.

    Preserves Groww contract evidence: Groww candle timestamps represent candle-start times.
    If `bar_start <= as_of < bar_end`, the bar is currently unfolding and must not be treated as sealed.
    """
    if as_of.tzinfo is None or bar_start.tzinfo is None or bar_end.tzinfo is None:
        raise ValueError("Timestamps must be timezone-aware")

    if bar_end <= bar_start:
        return CandleFreshnessAssessment(
            instrument=instrument,
            bar_start=bar_start,
            bar_end=bar_end,
            is_complete=False,
            status=FreshnessStatus.UNVERIFIED,
            reason="Invalid candle interval: bar_end is before or equal to bar_start.",
        )

    if as_of < bar_end:
        return CandleFreshnessAssessment(
            instrument=instrument,
            bar_start=bar_start,
            bar_end=bar_end,
            is_complete=False,
            status=FreshnessStatus.INCOMPLETE_CANDLE,
            reason="Candle is currently unfolding (in-progress bar). Not sealed for quantitative evaluation.",
        )

    return CandleFreshnessAssessment(
        instrument=instrument,
        bar_start=bar_start,
        bar_end=bar_end,
        is_complete=True,
        status=FreshnessStatus.FRESH,
        reason="Completed historical/intraday bar.",
    )


class InstrumentStatusReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument: str
    exchange: str
    segment: MarketSegment
    market_state: MarketState
    session_phase: SessionPhase
    is_open: bool
    freshness_status: FreshnessStatus
    price: float | None = None
    event_timestamp: str | None = None
    provider_timestamp: str | None = None
    retrieved_at: str | None = None
    age_seconds: float | None = None
    authoritative: bool
    verification_status: str = "UNVERIFIED"
    warning_or_limitation: str | None = None


def assess_instrument_status(
    instrument: str,
    as_of: datetime,
    quote_or_data: dict | None = None,
) -> InstrumentStatusReport:
    """Combine session state and observation freshness for a single instrument."""
    session = assess_market_session(instrument, as_of)

    if not quote_or_data:
        return InstrumentStatusReport(
            instrument=instrument,
            exchange=session.exchange,
            segment=session.segment,
            market_state=session.market_state,
            session_phase=session.session_phase,
            is_open=session.is_open,
            freshness_status=FreshnessStatus.UNAVAILABLE,
            authoritative=session.authoritative,
            verification_status="UNVERIFIED",
            warning_or_limitation="No quote data available.",
        )

    price = quote_or_data.get("last_price")

    def _parse_ts(val: Any) -> datetime | None:
        if isinstance(val, datetime):
            return val if val.tzinfo is not None else val.replace(tzinfo=IST)
        if isinstance(val, str) and val:
            try:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                return dt if dt.tzinfo is not None else dt.replace(tzinfo=IST)
            except Exception:
                return None
        return None

    event_ts = _parse_ts(quote_or_data.get("event_timestamp"))
    retrieved_ts = _parse_ts(quote_or_data.get("retrieved_at"))
    provider_ts = _parse_ts(quote_or_data.get("provider_timestamp"))

    freshness = assess_observation_freshness(
        instrument,
        as_of,
        event_timestamp=event_ts,
        retrieved_at=retrieved_ts,
        provider_timestamp=provider_ts,
        market_state=session.market_state,
    )

    warning = session.limitation or (freshness.reason if freshness.freshness_status in (FreshnessStatus.STALE, FreshnessStatus.DELAYED) else None)

    return InstrumentStatusReport(
        instrument=instrument,
        exchange=session.exchange,
        segment=session.segment,
        market_state=session.market_state,
        session_phase=session.session_phase,
        is_open=session.is_open,
        freshness_status=freshness.freshness_status,
        price=price,
        event_timestamp=event_ts.isoformat() if event_ts else None,
        provider_timestamp=provider_ts.isoformat() if provider_ts else None,
        retrieved_at=retrieved_ts.isoformat() if retrieved_ts else None,
        age_seconds=freshness.age_seconds,
        authoritative=session.authoritative,
        verification_status=quote_or_data.get("verification_status", "UNVERIFIED"),
        warning_or_limitation=warning,
    )


# --- Cross-Market Snapshot & Post-Close Analysis ---

def build_cross_market_snapshot(
    quotes: list[dict],
    commodities: list[dict],
    global_indices: list[dict],
    sectoral_indices: list[dict],
    as_of: datetime,
) -> dict:
    """Build a unified cross-market snapshot with per-instrument status and freshness.

    Distinguishes:
    1. Indian Equities & Indices
    2. Indian Commodities (MCX)
    3. International Markets
    4. Macro & Indicators
    """
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=IST)

    indian_equities: list[dict] = []
    indian_commodities: list[dict] = []
    international_markets: list[dict] = []
    macro_indicators: list[dict] = []

    # Map existing data
    equity_map = {q.get("instrument"): q for q in quotes if q.get("instrument")}
    comm_map = {c.get("instrument"): c for c in commodities if c.get("instrument")}
    global_map = {g.get("instrument"): g for g in global_indices if g.get("instrument")}
    sector_map = {s.get("instrument"): s for s in sectoral_indices if s.get("instrument")}

    # 1. Indian Equities
    for sym in ["NIFTY", "SENSEX", "BANKNIFTY", "NIFTYIT", "NIFTYAUTO", "NIFTYMETAL"]:
        data = equity_map.get(sym) or sector_map.get(sym)
        rep = assess_instrument_status(sym, as_of, data)
        item = rep.model_dump(mode="json")
        if data:
            item["day_change"] = data.get("day_change")
            item["percent_change"] = data.get("percent_change")
            item["name"] = data.get("name") or sym
        indian_equities.append(item)

    # 2. Indian Commodities (MCX)
    for sym in ["CRUDEOILMINI", "GOLDMINI", "SILVERMINI", "NATURALGASMINI"]:
        data = comm_map.get(sym)
        rep = assess_instrument_status(sym, as_of, data)
        item = rep.model_dump(mode="json")
        if data:
            item["day_change"] = data.get("day_change")
            item["percent_change"] = data.get("percent_change")
            item["unit"] = data.get("unit")
            item["name"] = data.get("name") or sym
        indian_commodities.append(item)

    # 3. International Markets
    for sym in ["GIFTNIFTY", "DJI", "DOWFUTURES", "NIKKEI", "HANGSENG", "BRENT"]:
        data = global_map.get(sym)
        rep = assess_instrument_status(sym, as_of, data)
        item = rep.model_dump(mode="json")
        if data:
            item["day_change"] = data.get("day_change")
            item["percent_change"] = data.get("percent_change")
            item["name"] = data.get("name") or sym
        international_markets.append(item)

    # 4. Macro Indicators
    for sym in ["VIX", "USDINR", "US10Y"]:
        data = sector_map.get(sym) or global_map.get(sym)
        rep = assess_instrument_status(sym, as_of, data)
        item = rep.model_dump(mode="json")
        if data:
            item["day_change"] = data.get("day_change")
            item["percent_change"] = data.get("percent_change")
            item["name"] = data.get("name") or sym
        macro_indicators.append(item)

    # Aggregate session states
    is_equity_open = any(eq["is_open"] for eq in indian_equities if eq["instrument"] in ("NIFTY", "SENSEX"))
    is_commodity_open = any(c["is_open"] for c in indian_commodities)
    post_close_mode = not is_equity_open

    # Warnings for timestamp spreads
    all_timestamps = [
        datetime.fromisoformat(item["event_timestamp"])
        for group in (indian_equities, indian_commodities, international_markets, macro_indicators)
        for item in group
        if item.get("event_timestamp")
    ]
    spread_seconds = (max(all_timestamps) - min(all_timestamps)).total_seconds() if len(all_timestamps) > 1 else 0

    warnings: list[str] = []
    if post_close_mode:
        warnings.append("Indian equity cash sessions are CLOSED. Retaining confirmed closing prices.")
        if is_commodity_open:
            warnings.append("MCX commodity contracts remain OPEN. Commodity prices are updating live.")
        else:
            warnings.append("MCX commodity contracts are CLOSED.")

    if spread_seconds > 3600:
        warnings.append(
            f"Cross-market observation timestamp spread is wide ({int(spread_seconds / 60)} minutes). Incompatible observation windows."
        )

    return {
        "as_of": as_of.astimezone(IST).isoformat(),
        "is_equity_open": is_equity_open,
        "is_commodity_open": is_commodity_open,
        "post_close_mode": post_close_mode,
        "timestamp_spread_seconds": spread_seconds,
        "warnings": warnings,
        "indian_equities": indian_equities,
        "indian_commodities": indian_commodities,
        "international_markets": international_markets,
        "macro_indicators": macro_indicators,
        "safety_flags": {
            "forecast_ready": False,
            "real_market_data_verified": False,
            "paper_approved": False,
            "live_approved": False,
        },
    }


def generate_post_close_analysis(cross_market_snapshot: dict, as_of: datetime) -> dict:
    """Generate overnight / post-close contextual analysis when Indian equity market is closed.

    Retains last valid equity close, incorporates ongoing MCX commodity session and global market sentiment,
    without claiming that closed equity data is live or that forecasts are validated.
    """
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=IST)

    equities = cross_market_snapshot.get("indian_equities") or []
    commodities = cross_market_snapshot.get("indian_commodities") or []
    global_mkts = cross_market_snapshot.get("international_markets") or []
    macros = cross_market_snapshot.get("macro_indicators") or []

    nifty = next((e for e in equities if e["instrument"] == "NIFTY"), {})
    sensex = next((e for e in equities if e["instrument"] == "SENSEX"), {})
    crude = next((c for c in commodities if c["instrument"] == "CRUDEOILMINI"), {})
    vix = next((m for m in macros if m["instrument"] == "VIX"), {})
    dji = next((g for g in global_mkts if g["instrument"] == "DJI"), {})

    return {
        "mode": "POST_CLOSE_ANALYSIS",
        "generated_at": as_of.astimezone(IST).isoformat(),
        "equity_session_state": "CLOSED",
        "last_equity_closes": {
            "NIFTY": {"close": nifty.get("price"), "timestamp": nifty.get("event_timestamp")},
            "SENSEX": {"close": sensex.get("price"), "timestamp": sensex.get("event_timestamp")},
        },
        "active_commodity_session": {
            "is_open": cross_market_snapshot.get("is_commodity_open", False),
            "CRUDEOILMINI": {
                "last_price": crude.get("price"),
                "status": crude.get("market_state"),
                "freshness": crude.get("freshness_status"),
                "timestamp": crude.get("event_timestamp"),
            },
        },
        "overnight_context": {
            "global_sentiment": dji.get("percent_change"),
            "domestic_volatility": vix.get("price"),
        },
        "summary": (
            "Equity cash sessions are closed. Official closing prints preserved. "
            "Overnight cross-market context generated. All safety and trading approval flags remain false."
        ),
        "safety_flags": {
            "forecast_ready": False,
            "real_market_data_verified": False,
            "paper_approved": False,
            "live_approved": False,
        },
    }
