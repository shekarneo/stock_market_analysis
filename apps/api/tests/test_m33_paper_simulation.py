"""Milestone M33 Test Suite: End-to-End Paper Execution Simulation & Slippage Accounting.

Verifies:
1. Precise calculation of Indian statutory regulatory charges (STT, NSE, SEBI, GST, Stamp Duty, Brokerage).
2. NSE discrete 0.05 INR tick alignment and directional slippage mechanics.
3. End-to-end paper simulation lifecycle over real NIFTY swing data.
4. Conservation of capital: Net PnL = Gross PnL - Statutory Fees.
5. Strict preservation of all 5 financial safety invariants.
"""

from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import pytest

from app.execution.paper_simulation_harness import (
    NSE_TICK_SIZE,
    calculate_indian_market_charges,
    calculate_simulated_fill_price,
    round_to_tick,
    run_nifty_swing_paper_simulation,
)
from app.settings import REPO_ROOT


def test_indian_regulatory_charges_futures():
    """Verify exact statutory charge calculation for Indian index futures."""
    price = Decimal("24000.00")
    qty = 50  # 2 NIFTY lots (2 * 25)
    turnover = price * Decimal(str(qty))  # 1,200,000 INR (12 Lakhs)

    # 1. Buy Order
    buy_charges = calculate_indian_market_charges("FUTURES", "BUY", price, qty)
    assert buy_charges.turnover == Decimal("1200000.00")
    assert buy_charges.stt == Decimal("0.00")  # No STT on Buy futures
    assert buy_charges.stamp_duty == Decimal("24.00")  # 0.002% on 1,200,000 = 24.00
    assert buy_charges.brokerage == Decimal("20.00")   # Flat 20 INR
    assert buy_charges.exchange_charges == Decimal("20.76")  # 0.00173% of 1,200,000
    assert buy_charges.sebi_charges == Decimal("1.20")       # Rs 10 / crore = 1.20 on 12L
    # GST = 18% of (20.00 + 20.76 + 1.20) = 18% of 41.96 = 7.55
    assert buy_charges.gst == Decimal("7.55")
    assert buy_charges.total_charges == Decimal("73.51")

    # 2. Sell Order
    sell_charges = calculate_indian_market_charges("FUTURES", "SELL", price, qty)
    assert sell_charges.stt == Decimal("240.00")  # 0.02% on 1,200,000 = 240.00
    assert sell_charges.stamp_duty == Decimal("0.00")  # No stamp duty on Sell
    assert sell_charges.brokerage == Decimal("20.00")
    assert sell_charges.exchange_charges == Decimal("20.76")
    assert sell_charges.sebi_charges == Decimal("1.20")
    assert sell_charges.gst == Decimal("7.55")
    assert sell_charges.total_charges == Decimal("289.51")


def test_indian_regulatory_charges_options():
    """Verify options statutory charges reflecting revised 0.10% STT on sell premium."""
    premium = Decimal("200.00")
    qty = 100  # 4 NIFTY lots
    turnover = premium * Decimal(str(qty))  # 20,000 INR

    # 1. Options Buy
    buy_opt = calculate_indian_market_charges("OPTIONS", "BUY", premium, qty)
    assert buy_opt.stt == Decimal("0.00")
    assert buy_opt.stamp_duty == Decimal("0.60")  # 0.003% of 20,000 = 0.60
    assert buy_opt.brokerage == Decimal("10.00")   # 0.05% of 20,000 = 10.00 (capped at min 20)
    assert buy_opt.exchange_charges == Decimal("7.01")  # 0.03503% of 20,000 = 7.006 -> 7.01

    # 2. Options Sell
    sell_opt = calculate_indian_market_charges("OPTIONS", "SELL", premium, qty)
    assert sell_opt.stt == Decimal("20.00")  # 0.10% of 20,000 = 20.00
    assert sell_opt.stamp_duty == Decimal("0.00")


def test_tick_size_alignment_and_slippage():
    """Verify prices round strictly to 0.05 INR ticks with directional slippage."""
    ref_price = Decimal("25123.47")
    tick_rounded = round_to_tick(ref_price)
    assert tick_rounded == Decimal("25123.45")

    # Buy fill price adds slippage and rounds to tick
    buy_fill, buy_slip = calculate_simulated_fill_price("BUY", Decimal("25000.00"), atr=Decimal("150.00"))
    assert buy_fill > Decimal("25000.00")
    assert buy_slip > Decimal("0.00")
    # Verify exact tick boundary
    assert (buy_fill % NSE_TICK_SIZE) == Decimal("0.00")

    # Sell fill price subtracts slippage and rounds to tick
    sell_fill, sell_slip = calculate_simulated_fill_price("SELL", Decimal("25000.00"), atr=Decimal("150.00"))
    assert sell_fill < Decimal("25000.00")
    assert sell_slip > Decimal("0.00")
    assert (sell_fill % NSE_TICK_SIZE) == Decimal("0.00")


def test_paper_simulation_end_to_end_on_nifty_dataset():
    """Verify end-to-end execution of paper trading simulation on 1-year NIFTY dataset."""
    summary = run_nifty_swing_paper_simulation(initial_capital_inr=1_000_000.0)

    assert summary is not None
    assert summary.symbol == "NIFTY"
    assert summary.initial_capital_inr == 1_000_000.0
    assert summary.total_trades > 0
    assert summary.total_regulatory_charges_inr > 0.0
    assert summary.total_slippage_inr > 0.0

    # Capital Conservation Invariant: Net PnL = Gross PnL - Total Regulatory Charges
    computed_net = summary.gross_pnl_inr - summary.total_regulatory_charges_inr
    assert abs(summary.net_pnl_inr - computed_net) < 0.05

    # Check fee breakdown sums correctly
    summed_fees = (
        summary.total_stt_inr
        + summary.total_exchange_turnover_inr
        + summary.total_sebi_charges_inr
        + summary.total_gst_inr
        + summary.total_stamp_duty_inr
        + summary.total_brokerage_inr
    )
    assert abs(summary.total_regulatory_charges_inr - summed_fees) < 0.05

    # Check artifact persisted on disk
    artifact_path = REPO_ROOT / "var/datasets/m33_paper_simulation_results.json"
    assert artifact_path.exists()
    with open(artifact_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["total_trades"] == summary.total_trades
    assert "trades" in data
    assert len(data["trades"]) == summary.total_trades


def test_m33_safety_invariants_strictly_false():
    """All 5 financial safety invariants must remain strictly False."""
    summary = run_nifty_swing_paper_simulation(initial_capital_inr=1_000_000.0)
    assert summary.forecast_ready is False
    assert summary.real_market_data_verified is False
    assert summary.paper_approved is False
    assert summary.live_approved is False
    assert summary.live_broker_routing_enabled is False
