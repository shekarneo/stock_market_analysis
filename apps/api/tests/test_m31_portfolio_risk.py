"""Unit test suite for Milestone M31: Portfolio Risk Management, Volatility-Parity Sizing, and Intraday Square-Off.
"""

from __future__ import annotations

from decimal import Decimal
import pytest

from app.risk.portfolio_risk import (
    assess_intraday_square_off,
    calculate_volatility_parity_size,
)


def test_volatility_parity_sizing_scales_inversely_with_atr():
    """Verify position size in lots scales inversely with ATR, equalizing dollar-volatility risk."""
    capital = Decimal("1000000.0")  # 10 Lakhs INR
    entry = Decimal("25000.0")
    stop = Decimal("24900.0")       # 100 pt stop

    # Low Volatility: ATR = 50 pts
    res_low_vol = calculate_volatility_parity_size(
        instrument="NIFTY",
        total_capital_inr=capital,
        entry_price=entry,
        stop_loss_price=stop,
        atr_value=Decimal("50.0"),
        win_probability=0.55,
        reward_to_risk_ratio=1.5,
        custom_lot_size=25,
    )

    # High Volatility: ATR = 200 pts
    res_high_vol = calculate_volatility_parity_size(
        instrument="NIFTY",
        total_capital_inr=capital,
        entry_price=entry,
        stop_loss_price=stop,
        atr_value=Decimal("200.0"),
        win_probability=0.55,
        reward_to_risk_ratio=1.5,
        custom_lot_size=25,
    )

    assert res_low_vol.decision == "EXECUTE"
    assert res_high_vol.decision == "EXECUTE"
    # Low volatility must allocate more lots than high volatility
    assert res_low_vol.recommended_lots > res_high_vol.recommended_lots
    # Dollar risk at stop must remain capped under 2% risk budget (20,000 INR)
    assert res_low_vol.dollar_risk_at_stop_inr <= 20000.0
    assert res_high_vol.dollar_risk_at_stop_inr <= 20000.0


def test_half_kelly_non_positive_edge_vetoes_trade():
    """Verify that when win probability is below breakeven, Half-Kelly clamps to 0 and asserts NO_TRADE."""
    res = calculate_volatility_parity_size(
        instrument="NIFTY",
        total_capital_inr=1000000.0,
        entry_price=25000.0,
        stop_loss_price=24900.0,
        atr_value=50.0,
        win_probability=0.35,  # Non-positive edge with 1.0 payoff
        reward_to_risk_ratio=1.0,
    )

    assert res.decision == "NO_TRADE"
    assert res.recommended_lots == 0
    assert res.total_quantity == 0
    assert "KELLY_VETO_NON_POSITIVE_EDGE" in res.reasons


def test_lot_size_floor_and_budget_constraints():
    """Verify system outputs NO_TRADE if capital is insufficient for 1 minimum lot, and does NOT round up."""
    # Tiny capital: 10,000 INR. 2% risk budget = 200 INR.
    # NIFTY 1 lot (25 qty) with 100 pt stop requires 2,500 INR risk budget!
    res = calculate_volatility_parity_size(
        instrument="NIFTY",
        total_capital_inr=10000.0,
        entry_price=25000.0,
        stop_loss_price=24900.0,
        atr_value=50.0,
        win_probability=0.60,
        custom_lot_size=25,
    )

    assert res.decision == "NO_TRADE"
    assert res.recommended_lots == 0
    assert "BUDGET_BELOW_MINIMUM_LOT_SIZE" in res.reasons


def test_intraday_square_off_timeline():
    """Verify square-off assessment across key Indian trading day milestones."""
    # 1. Normal session (10:30 IST)
    s1 = assess_intraday_square_off("10:30:00")
    assert s1.status == "NORMAL_TRADING"
    assert s1.allow_new_entries is True
    assert s1.force_square_off_now is False

    # 2. Entry cutoff window (15:12 IST)
    s2 = assess_intraday_square_off("15:12:00")
    assert s2.status == "ENTRY_CUTOFF"
    assert s2.allow_new_entries is False
    assert s2.force_square_off_now is False

    # 3. Mandatory square-off window (15:18 IST)
    s3 = assess_intraday_square_off("15:18:00")
    assert s3.status == "MANDATORY_SQUARE_OFF"
    assert s3.allow_new_entries is False
    assert s3.force_square_off_now is True

    # 4. Market closed (15:45 IST)
    s4 = assess_intraday_square_off("15:45:00")
    assert s4.status == "MARKET_CLOSED"
    assert s4.allow_new_entries is False
    assert s4.force_square_off_now is False

    # 5. Pre-market (08:30 IST)
    s5 = assess_intraday_square_off("08:30:00")
    assert s5.status == "MARKET_CLOSED"
    assert s5.allow_new_entries is False


def test_m31_safety_invariants_strictly_false():
    """Verify all 5 hard financial safety invariants remain False in portfolio risk sizing."""
    res = calculate_volatility_parity_size(
        instrument="NIFTY",
        total_capital_inr=1000000.0,
        entry_price=25000.0,
        stop_loss_price=24900.0,
        atr_value=50.0,
    )

    assert res.forecast_ready is False
    assert res.paper_approved is False
    assert res.live_approved is False
    assert res.real_market_data_verified is False
