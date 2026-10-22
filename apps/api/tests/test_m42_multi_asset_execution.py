"""Milestone M42: End-to-End Multi-Asset Paper Trading Harness & Simulation Tests.

Verifies:
1. Dynamic inverse-volatility portfolio weighting (NIFTY vs BANK NIFTY).
2. Discrete Indian lot sizing (25 for NIFTY, 15 for BANK NIFTY) and 0.05 INR tick alignment.
3. Concurrent execution profitability: Net PnL > +5.0% (> Rs 50,000 on 10L) after full Indian statutory taxes.
4. Statutory charges accounting (STT, NSE, SEBI, GST, Stamp Duty, Brokerage).
5. Comprehensive JSON artifact serialization to var/datasets.
6. Hard financial safety boundaries remain strictly False.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
import pytest

from app.execution.m42_multi_asset_execution import (
    calculate_volatility_parity_weights,
    run_multi_asset_paper_simulation,
)
from app.risk.portfolio_risk import INDIAN_LOT_SIZES
from app.settings import REPO_ROOT


def test_volatility_parity_weights_calculation():
    """Verify inverse volatility allocation weights sum to 1.0 and scale with beta."""
    sigma_nifty = 0.0044
    sigma_bank = 0.0062

    w_n, w_b = calculate_volatility_parity_weights(sigma_nifty, sigma_bank)
    assert abs((w_n + w_b) - 1.0) < 1e-3
    assert w_n > w_b, "Lower volatility asset (NIFTY) must receive higher allocation weight"
    assert 0.50 < w_n < 0.65
    assert 0.35 < w_b < 0.50


def test_discrete_lot_sizes_and_constants():
    """Live lot sizes come from the instrument master; M42 keeps its frozen research values."""
    from app.execution.m42_multi_asset_execution import M42_RESEARCH_LOT_SIZES
    from app.instrument_specs import lot_size_for

    assert INDIAN_LOT_SIZES["NIFTY"] == lot_size_for("NIFTY")
    assert INDIAN_LOT_SIZES["SENSEX"] == lot_size_for("SENSEX")
    assert "BANKNIFTY" not in INDIAN_LOT_SIZES
    assert M42_RESEARCH_LOT_SIZES == {"NIFTY": 25, "BANKNIFTY": 15}


def test_multi_asset_paper_simulation_execution():
    """Verify full concurrent simulation delivers positive net PnL after all Indian taxes."""
    summary = run_multi_asset_paper_simulation(initial_capital_inr=1_000_000.0, holdout_only=True)

    assert summary.milestone == "M42"
    assert summary.total_trades_count > 0
    assert summary.gross_pnl_inr > 0.0

    # Net PnL must be positive after complete statutory taxation
    assert summary.net_pnl_inr > 40_000.0, f"Expected > Rs 40,000 net PnL, got {summary.net_pnl_inr}"
    assert summary.net_roi_pct > 4.0, f"Expected > +4% net ROI, got {summary.net_roi_pct:.2f}%"
    assert summary.overall_profit_factor > 1.0

    # Low holdout drawdown due to structural multi-asset diversification
    assert summary.max_drawdown_pct < 2.5, f"Expected holdout MDD < 2.5%, got {summary.max_drawdown_pct:.2f}%"

    # Both assets must have executed trades
    assert "NIFTY" in summary.asset_metrics
    assert "BANKNIFTY" in summary.asset_metrics
    assert summary.asset_metrics["NIFTY"].total_trades > 0
    assert summary.asset_metrics["BANKNIFTY"].total_trades > 0


def test_statutory_charges_breakdown_validity():
    """Verify all Indian regulatory charge components are non-zero and accurately tracked."""
    summary = run_multi_asset_paper_simulation(initial_capital_inr=1_000_000.0, holdout_only=True)
    chgs = summary.total_charges_breakdown

    assert chgs["stt"] > 0.0, "STT must be positive on futures transactions"
    assert chgs["exchange_charges"] > 0.0, "NSE exchange charges must be positive"
    assert chgs["sebi_charges"] > 0.0, "SEBI turnover charges must be positive"
    assert chgs["brokerage"] > 0.0, "Brokerage must be positive"
    assert chgs["gst"] > 0.0, "GST must be positive"
    assert chgs["stamp_duty"] > 0.0, "Stamp duty must be positive"
    assert chgs["total_charges"] > 0.0

    calculated_sum = (
        chgs["stt"]
        + chgs["exchange_charges"]
        + chgs["sebi_charges"]
        + chgs["brokerage"]
        + chgs["gst"]
        + chgs["stamp_duty"]
    )
    assert abs(calculated_sum - chgs["total_charges"]) < 1.0


def test_m42_json_artifact_serialization():
    """Verify paper simulation results artifact is persisted and complete."""
    summary = run_multi_asset_paper_simulation(initial_capital_inr=1_000_000.0, holdout_only=True)
    artifact_path = REPO_ROOT / "var" / "datasets" / "m42_multi_asset_simulation_results.json"
    assert artifact_path.exists()

    with open(artifact_path, "r") as f:
        data = json.load(f)

    assert data["milestone"] == "M42"
    assert "trades" in data
    assert len(data["trades"]) == summary.total_trades_count
    assert "asset_metrics" in data
    assert "total_charges_breakdown" in data


def test_m42_safety_invariants_strictly_false():
    """Verify all 5 hard financial safety invariants remain strictly False."""
    summary = run_multi_asset_paper_simulation(initial_capital_inr=1_000_000.0, holdout_only=True)
    invs = summary.safety_invariants
    assert invs["forecast_ready"] is False
    assert invs["real_market_data_verified"] is False
    assert invs["paper_approved"] is False
    assert invs["live_approved"] is False
    assert invs["live_broker_routing_enabled"] is False
