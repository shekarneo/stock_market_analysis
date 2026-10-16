"""Tests for Milestone M13: Exchange Session Intelligence, Cross-Market Freshness, and Post-Close Analysis."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.market.session_intelligence import (
    ET,
    IST,
    CandleFreshnessAssessment,
    FreshnessAssessment,
    FreshnessStatus,
    InstrumentSessionConfig,
    InstrumentStatusReport,
    MarketSegment,
    MarketState,
    SessionAssessment,
    SessionPhase,
    assess_candle_freshness,
    assess_instrument_status,
    assess_market_session,
    assess_observation_freshness,
    build_cross_market_snapshot,
    generate_post_close_analysis,
    get_instrument_session_config,
    is_us_daylight_saving_time,
)


def test_supported_instrument_categories_and_configurations():
    """Phase 2: Distinguish all required market segments and configurations."""
    # 1. NSE cash equities & indices
    nifty = get_instrument_session_config("NIFTY")
    assert nifty.exchange == "NSE"
    assert nifty.segment == MarketSegment.NSE_CASH
    assert nifty.regular_open == time(9, 15)
    assert nifty.regular_close == time(15, 30)
    assert nifty.pre_open_start == time(9, 0)
    assert nifty.post_close_end == time(16, 0)
    assert nifty.tz == IST

    # 2. BSE cash equities & indices
    sensex = get_instrument_session_config("SENSEX")
    assert sensex.exchange == "BSE"
    assert sensex.segment == MarketSegment.BSE_CASH
    assert sensex.regular_open == time(9, 15)
    assert sensex.regular_close == time(15, 30)

    # 3. NSE equity derivatives
    nifty_fut = get_instrument_session_config("NIFTY_FUT")
    assert nifty_fut.segment == MarketSegment.NSE_DERIVATIVES
    assert nifty_fut.pre_open_start is None  # Derivatives have no pre-open

    # 4. MCX commodity contracts
    crude = get_instrument_session_config("CRUDEOILMINI")
    assert crude.exchange == "MCX"
    assert crude.segment == MarketSegment.MCX_COMMODITY
    assert crude.regular_open == time(9, 0)
    assert crude.freshness.warn_seconds == 120

    # 5. International commodity benchmarks
    brent = get_instrument_session_config("BRENT")
    assert brent.segment == MarketSegment.INTERNATIONAL_COMMODITY

    # 6. US equity indices
    dji = get_instrument_session_config("DJI")
    assert dji.segment == MarketSegment.US_EQUITY
    assert dji.tz == ET

    # 7. US Treasury yields
    us10y = get_instrument_session_config("US10Y")
    assert us10y.segment == MarketSegment.US_TREASURY
    assert us10y.freshness.warn_seconds == 86400  # Daily publication schedule

    # 8. USD/INR forex
    usdinr = get_instrument_session_config("USDINR")
    assert usdinr.segment == MarketSegment.FOREX
    assert usdinr.regular_open == time(9, 0)
    assert usdinr.regular_close == time(17, 0)

    # 9. India VIX
    vix = get_instrument_session_config("VIX")
    assert vix.segment == MarketSegment.MARKET_INDICATOR
    assert vix.regular_open == time(9, 15)
    assert vix.regular_close == time(15, 30)


def test_nse_session_states_deterministic():
    """Phase 3: NSE session pre-open, regular open, post-close, and night closure."""
    # Wednesday, October 14, 2026 (Regular trading day)
    wed = date(2026, 10, 14)

    # Pre-open at 09:05 IST
    as_of_pre = datetime.combine(wed, time(9, 5), tzinfo=IST)
    sess_pre = assess_market_session("NIFTY", as_of_pre)
    assert sess_pre.market_state == MarketState.PRE_OPEN
    assert sess_pre.session_phase == SessionPhase.PRE_OPEN
    assert sess_pre.is_open is False

    # Regular open at 11:30 IST
    as_of_open = datetime.combine(wed, time(11, 30), tzinfo=IST)
    sess_open = assess_market_session("NIFTY", as_of_open)
    assert sess_open.market_state == MarketState.OPEN
    assert sess_open.session_phase == SessionPhase.REGULAR
    assert sess_open.is_open is True

    # Post-close auction at 15:45 IST
    as_of_post = datetime.combine(wed, time(15, 45), tzinfo=IST)
    sess_post = assess_market_session("NIFTY", as_of_post)
    assert sess_post.market_state == MarketState.POST_CLOSE
    assert sess_post.session_phase == SessionPhase.POST_CLOSE
    assert sess_post.is_open is False

    # Night closed at 20:00 IST
    as_of_night = datetime.combine(wed, time(20, 0), tzinfo=IST)
    sess_night = assess_market_session("NIFTY", as_of_night)
    assert sess_night.market_state == MarketState.CLOSED
    assert sess_night.session_phase == SessionPhase.CLOSED
    assert sess_night.is_open is False


def test_mcx_trading_independently_when_equity_is_closed():
    """Phase 2 & 3: MCX continues trading after NSE closes at 15:30 IST."""
    wed = date(2026, 10, 14)

    # At 16:30 IST: NSE is closed, but MCX is open
    as_of_1630 = datetime.combine(wed, time(16, 30), tzinfo=IST)
    nse_sess = assess_market_session("NIFTY", as_of_1630)
    mcx_sess = assess_market_session("CRUDEOILMINI", as_of_1630)
    assert nse_sess.is_open is False
    assert nse_sess.market_state == MarketState.CLOSED
    assert mcx_sess.is_open is True
    assert mcx_sess.market_state == MarketState.OPEN

    # At 21:00 IST: MCX evening session is active
    as_of_2100 = datetime.combine(wed, time(21, 0), tzinfo=IST)
    mcx_sess_21 = assess_market_session("CRUDEOILMINI", as_of_2100)
    assert mcx_sess_21.is_open is True
    assert mcx_sess_21.session_phase == SessionPhase.EVENING


def test_mcx_us_dst_dynamic_close_time():
    """Phase 2: MCX close is 23:30 during US DST (summer) and 23:55 during US standard time (winter)."""
    # Summer date: July 15, 2026 (US DST active)
    summer_dt = datetime(2026, 7, 15, 12, 0, tzinfo=IST)
    assert is_us_daylight_saving_time(summer_dt) is True

    # At 23:35 IST on summer day: MCX regular trading is closed, in post-close
    mcx_summer_2335 = assess_market_session("CRUDEOILMINI", datetime(2026, 7, 15, 23, 35, tzinfo=IST))
    assert mcx_summer_2335.is_open is False
    assert mcx_summer_2335.market_state == MarketState.POST_CLOSE

    # At 23:50 IST on summer day: MCX post-close has completed, completely CLOSED
    mcx_summer_2350 = assess_market_session("CRUDEOILMINI", datetime(2026, 7, 15, 23, 50, tzinfo=IST))
    assert mcx_summer_2350.is_open is False
    assert mcx_summer_2350.market_state == MarketState.CLOSED

    # Winter date: December 16, 2026 (US Standard Time, EST, no DST)
    winter_dt = datetime(2026, 12, 16, 12, 0, tzinfo=IST)
    assert is_us_daylight_saving_time(winter_dt) is False

    # At 23:35 IST on winter day: MCX should still be OPEN (extended to 23:55 IST)
    mcx_winter_2335 = assess_market_session("CRUDEOILMINI", datetime(2026, 12, 16, 23, 35, tzinfo=IST))
    assert mcx_winter_2335.is_open is True
    assert mcx_winter_2335.market_state == MarketState.OPEN

    # At 23:58 IST on winter day: MCX is CLOSED
    mcx_winter_2358 = assess_market_session("CRUDEOILMINI", datetime(2026, 12, 16, 23, 58, tzinfo=IST))
    assert mcx_winter_2358.is_open is False


def test_weekend_and_authoritative_holidays():
    """Phase 2: Weekend and holiday closures for NSE and MCX."""
    # Weekend: Saturday, October 17, 2026 at 11:00 IST
    sat_dt = datetime(2026, 10, 17, 11, 0, tzinfo=IST)
    nse_sat = assess_market_session("NIFTY", sat_dt)
    mcx_sat = assess_market_session("CRUDEOILMINI", sat_dt)
    assert nse_sat.is_open is False
    assert mcx_sat.is_open is False

    # Full holiday: Independence Day, August 15, 2026
    aug15_dt = datetime(2026, 8, 15, 11, 0, tzinfo=IST)
    assert assess_market_session("NIFTY", aug15_dt).is_open is False
    assert assess_market_session("CRUDEOILMINI", aug15_dt).is_open is False

    # MCX Holiday Morning-Closed / Evening-Open: Holi, March 3, 2026
    # Morning at 11:00 IST: NSE closed, MCX closed
    holi_morning = datetime(2026, 3, 3, 11, 0, tzinfo=IST)
    assert assess_market_session("NIFTY", holi_morning).is_open is False
    assert assess_market_session("CRUDEOILMINI", holi_morning).is_open is False

    # Evening at 18:30 IST: NSE closed, MCX open for holiday evening session
    holi_evening = datetime(2026, 3, 3, 18, 30, tzinfo=IST)
    assert assess_market_session("NIFTY", holi_evening).is_open is False
    mcx_holi_eve = assess_market_session("CRUDEOILMINI", holi_evening)
    assert mcx_holi_eve.is_open is True
    assert mcx_holi_eve.session_phase == SessionPhase.EVENING


def test_diwali_muhurat_special_session():
    """Phase 2: Diwali Muhurat trading session (18:00 - 19:15 IST)."""
    muhurat_dt = datetime(2026, 11, 8, 18, 30, tzinfo=IST)
    nse_muhurat = assess_market_session("NIFTY", muhurat_dt)
    assert nse_muhurat.is_open is True
    assert nse_muhurat.session_phase == SessionPhase.SPECIAL

    # Outside the 18:00-19:15 window on Diwali day: Closed
    diwali_afternoon = datetime(2026, 11, 8, 14, 0, tzinfo=IST)
    assert assess_market_session("NIFTY", diwali_afternoon).is_open is False


def test_market_closed_with_valid_close_vs_market_open_with_stale_quote():
    """Phase 3 & 4: Clear distinction between CLOSED market (valid context) and OPEN market (stale quote)."""
    wed = date(2026, 10, 14)

    # Scenario A: Market is OPEN at 11:00 IST, but quote is 10 minutes old (600s) -> STALE
    now_open = datetime.combine(wed, time(11, 0), tzinfo=IST)
    stale_quote_ts = now_open - timedelta(seconds=600)
    freshness_open = assess_observation_freshness(
        "NIFTY",
        now_open,
        event_timestamp=stale_quote_ts,
        market_state=MarketState.OPEN,
    )
    assert freshness_open.freshness_status == FreshnessStatus.STALE

    # Scenario B: Market is CLOSED at 20:00 IST, quote is from session close at 15:30 IST (4.5 hours old)
    # -> NOT STALE, valid closed session retention!
    now_closed = datetime.combine(wed, time(20, 0), tzinfo=IST)
    close_quote_ts = datetime.combine(wed, time(15, 30), tzinfo=IST)
    freshness_closed = assess_observation_freshness(
        "NIFTY",
        now_closed,
        event_timestamp=close_quote_ts,
        market_state=MarketState.CLOSED,
    )
    assert freshness_closed.freshness_status == FreshnessStatus.CLOSED_SESSION_VALID
    assert "retaining official closing price" in freshness_closed.reason.lower()


def test_incomplete_candle_handling():
    """Phase 4: Preserve Groww candle-start timestamp contract; unfold incomplete bars without sealing."""
    now = datetime(2026, 10, 14, 10, 20, tzinfo=IST)

    # Bar covering 10:15 - 10:30 IST. Since now=10:20 IST, the bar is still unfolding!
    bar_start = datetime(2026, 10, 14, 10, 15, tzinfo=IST)
    bar_end = datetime(2026, 10, 14, 10, 30, tzinfo=IST)

    assessment = assess_candle_freshness("NIFTY", now, bar_start, bar_end)
    assert assessment.is_complete is False
    assert assessment.status == FreshnessStatus.INCOMPLETE_CANDLE
    assert "unfolding" in assessment.reason

    # Past completed bar: 10:00 - 10:15 IST
    past_start = datetime(2026, 10, 14, 10, 0, tzinfo=IST)
    past_end = datetime(2026, 10, 14, 10, 15, tzinfo=IST)
    past_assessment = assess_candle_freshness("NIFTY", now, past_start, past_end)
    assert past_assessment.is_complete is True
    assert past_assessment.status == FreshnessStatus.FRESH


def test_cross_market_snapshot_aggregation_and_post_close():
    """Phase 5 & 6: Unified cross-market snapshot and post-close analysis."""
    # 20:30 IST on a Wednesday: Equity is closed, MCX is open
    as_of = datetime(2026, 10, 14, 20, 30, tzinfo=IST)

    quotes = [
        {
            "instrument": "NIFTY",
            "last_price": 25150.0,
            "event_timestamp": "2026-10-14T15:30:00+05:30",
            "retrieved_at": "2026-10-14T15:30:05+05:30",
        },
        {
            "instrument": "SENSEX",
            "last_price": 82100.0,
            "event_timestamp": "2026-10-14T15:30:00+05:30",
            "retrieved_at": "2026-10-14T15:30:05+05:30",
        },
    ]

    commodities = [
        {
            "instrument": "CRUDEOILMINI",
            "last_price": 6150.0,
            "unit": "₹/bbl",
            "event_timestamp": "2026-10-14T20:29:45+05:30",
            "retrieved_at": "2026-10-14T20:29:50+05:30",
        }
    ]

    global_indices = [
        {
            "instrument": "DJI",
            "last_price": 42500.0,
            "percent_change": "+0.45%",
            "event_timestamp": "2026-10-14T20:25:00+05:30",
        }
    ]

    sectorals = [
        {
            "instrument": "VIX",
            "last_price": 13.5,
            "event_timestamp": "2026-10-14T15:30:00+05:30",
        }
    ]

    snapshot = build_cross_market_snapshot(quotes, commodities, global_indices, sectorals, as_of=as_of)

    assert snapshot["is_equity_open"] is False
    assert snapshot["is_commodity_open"] is True
    assert snapshot["post_close_mode"] is True

    # Check NIFTY in snapshot
    nifty = next(eq for eq in snapshot["indian_equities"] if eq["instrument"] == "NIFTY")
    assert nifty["market_state"] == "CLOSED"
    assert nifty["freshness_status"] == "CLOSED_SESSION_VALID"

    # Check CRUDEOILMINI in snapshot
    crude = next(c for c in snapshot["indian_commodities"] if c["instrument"] == "CRUDEOILMINI")
    assert crude["market_state"] == "OPEN"
    assert crude["is_open"] is True
    assert crude["freshness_status"] in ("LIVE", "FRESH")

    # Generate post-close analysis
    post_close = generate_post_close_analysis(snapshot, as_of=as_of)
    assert post_close["mode"] == "POST_CLOSE_ANALYSIS"
    assert post_close["equity_session_state"] == "CLOSED"
    assert post_close["last_equity_closes"]["NIFTY"]["close"] == 25150.0
    assert post_close["active_commodity_session"]["is_open"] is True
    assert post_close["active_commodity_session"]["CRUDEOILMINI"]["last_price"] == 6150.0

    # Phase 9 Safety invariant check
    for flags in (snapshot["safety_flags"], post_close["safety_flags"]):
        assert flags["forecast_ready"] is False
        assert flags["real_market_data_verified"] is False
        assert flags["paper_approved"] is False
        assert flags["live_approved"] is False


def test_stale_vs_unavailable_vs_unverified_semantics():
    """Phase 3 & 4: Strict semantics distinguishing UNAVAILABLE, UNVERIFIED, STALE, and CLOSED_SESSION_VALID."""
    as_of = datetime(2026, 10, 14, 11, 0, tzinfo=IST)

    # 1. No timestamp at all -> UNAVAILABLE
    unavail = assess_observation_freshness("NIFTY", as_of, event_timestamp=None, market_state=MarketState.OPEN)
    assert unavail.freshness_status == FreshnessStatus.UNAVAILABLE

    # 2. Naive timestamp (no tzinfo) -> UNVERIFIED
    naive_ts = datetime(2026, 10, 14, 10, 59)
    unverif = assess_observation_freshness("NIFTY", as_of, event_timestamp=naive_ts, market_state=MarketState.OPEN)
    assert unverif.freshness_status == FreshnessStatus.UNVERIFIED

    # 3. Old timestamp during active session -> STALE
    old_ts = as_of - timedelta(seconds=400)
    stale = assess_observation_freshness("NIFTY", as_of, event_timestamp=old_ts, market_state=MarketState.OPEN)
    assert stale.freshness_status == FreshnessStatus.STALE

    # 4. Old timestamp during closed session -> CLOSED_SESSION_VALID
    closed_as_of = datetime(2026, 10, 14, 21, 0, tzinfo=IST)
    close_ts = datetime(2026, 10, 14, 15, 30, tzinfo=IST)
    valid_closed = assess_observation_freshness("NIFTY", closed_as_of, event_timestamp=close_ts, market_state=MarketState.CLOSED)
    assert valid_closed.freshness_status == FreshnessStatus.CLOSED_SESSION_VALID


def test_cross_market_snapshot_spread_warning():
    """Phase 5: Incompatible observation timestamps produce explicit warnings without hiding."""
    as_of = datetime(2026, 10, 14, 21, 0, tzinfo=IST)

    quotes = [
        {
            "instrument": "NIFTY",
            "last_price": 25150.0,
            "event_timestamp": "2026-10-14T15:30:00+05:30",
        }
    ]
    commodities = [
        {
            "instrument": "CRUDEOILMINI",
            "last_price": 6150.0,
            "event_timestamp": "2026-10-14T20:55:00+05:30",
        }
    ]
    # 5.5 hours spread between equity close and commodity quote
    snapshot = build_cross_market_snapshot(quotes, commodities, [], [], as_of=as_of)
    assert snapshot["timestamp_spread_seconds"] > 3600
    assert any("timestamp spread is wide" in w for w in snapshot["warnings"])


def test_api_live_quotes_includes_session_intelligence(client):
    """Phase 7: Verify /api/market/live-quotes endpoint returns cross-market intelligence."""
    from tests.conftest import login
    login(client)
    res = client.get("/api/market/live-quotes")
    assert res.status_code == 200
    body = res.json()

    assert "cross_market_snapshot" in body
    assert "post_close_mode" in body
    assert "is_equity_open" in body
    assert "is_commodity_open" in body
    assert body["real_market_data_verified"] is False

    snapshot = body["cross_market_snapshot"]
    assert "indian_equities" in snapshot
    assert "indian_commodities" in snapshot
    assert "international_markets" in snapshot
    assert "macro_indicators" in snapshot
    assert snapshot["safety_flags"]["forecast_ready"] is False
    assert snapshot["safety_flags"]["live_approved"] is False

