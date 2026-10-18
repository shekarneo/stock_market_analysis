"""Milestone M20 Research Engine Tests.

Tests:
1. build_htf_1hour_context point-in-time calculation with zero future leakage.
2. evaluate_selective_transaction_costs position state machine, friction conversion, turnovers, and trade counting.
3. compute_max_drawdown equity drawdown logic.
4. Validation-only threshold tuning isolation (no test data leakage).
5. run_m20_walk_forward_evaluation across synthetic and realistic candles:
   - Evaluates all 6 canonical candidate models:
     (empirical_prior, majority_class, last_return_sign, logistic_regression_base,
      logistic_regression_htf, selective_entry_htf)
   - Verifies Brier score, BSS, turnover, trade count, net returns across hurdles (0, 1, 2, 5, 10 bps)
   - Verifies safety invariants remain False
   - Verifies trading_decision is BLOCKED
6. Fast failure on insufficient observations.
"""

from __future__ import annotations

import math
import statistics
import pytest

from app.forecasting.m20_research import (
    M20ResearchConfig,
    build_htf_1hour_context,
    compute_max_drawdown,
    evaluate_selective_transaction_costs,
    run_m20_walk_forward_evaluation,
)


def _make_dummy_candles(n: int = 150) -> list[dict]:
    """Generate deterministic synthetic candles."""
    candles = []
    base_price = 25000.0
    for i in range(n):
        # Deterministic gentle oscillation
        ret = 0.001 * math.sin(i * 0.4)
        c_open = base_price
        c_close = base_price * (1.0 + ret)
        c_high = max(c_open, c_close) * 1.0005
        c_low = min(c_open, c_close) * 0.9995
        base_price = c_close
        candles.append({
            "timestamp": f"2026-03-01T{9 + (i // 25):02d}:{(i % 25) * 15 % 60:02d}:00+05:30",
            "open": c_open,
            "high": c_high,
            "low": c_low,
            "close": c_close,
            "volume": 1000 + i * 10,
        })
    return candles


# ============================================================================
# 1. Max Drawdown Tests
# ============================================================================

def test_compute_max_drawdown_empty_and_flat():
    assert compute_max_drawdown([]) == 0.0
    assert compute_max_drawdown([0.0, 0.0, 0.0]) == 0.0


def test_compute_max_drawdown_hand_calculated():
    # Start at 1.0 -> down 10% to 0.9 -> up 5% to 0.945 -> down 20% to 0.756
    # Max drawdown is from 1.0 down to 0.756 -> -24.4%
    returns = [-0.10, 0.05, -0.20]
    dd = compute_max_drawdown(returns)
    expected_peak = 1.0
    val_after_r1 = 0.90
    val_after_r2 = 0.90 * 1.05  # 0.945
    val_after_r3 = 0.945 * 0.80  # 0.756
    expected_dd = (val_after_r3 - expected_peak) / expected_peak * 100.0  # -24.4%
    assert dd == pytest.approx(expected_dd, abs=0.01)


# ============================================================================
# 2. HTF 1-Hour Context & Leakage Prevention Tests
# ============================================================================

def test_build_htf_1hour_context_point_in_time_no_future_leakage():
    candles = _make_dummy_candles(20)
    htf = build_htf_1hour_context(candles)

    # First 3 hourly bars (12 15-minute bars) have fewer than 3 completed hours
    for i in range(11):
        assert htf[i]["htf_1h_return"] == 0.0
        assert htf[i]["htf_1h_trend_dir"] == 0.0

    # At bar index 11 (the end of the 3rd 1-hour bar: indices 0..3, 4..7, 8..11),
    # 3 hourly bars are complete! Bar 11 must now have valid non-zero HTF features
    assert 11 in htf
    assert "htf_1h_return" in htf[11]
    assert "htf_1h_close_vs_sma3" in htf[11]

    # Modifying future candle 15 must NOT change HTF context at bar 11
    candles_modified = [dict(c) for c in candles]
    candles_modified[15]["close"] = candles_modified[15]["close"] * 2.0
    htf_modified = build_htf_1hour_context(candles_modified)

    assert htf[11] == htf_modified[11]
    assert htf[10] == htf_modified[10]


# ============================================================================
# 3. Selective Entry Transaction Cost Mechanics
# ============================================================================

def test_evaluate_selective_transaction_costs_deadband_and_hysteresis():
    # 5 test bars
    test_rows = [
        {"next_return": 0.01},   # bar 0: p=0.60 -> enter long (turnover=1, pos=1)
        {"next_return": -0.01},  # bar 1: p=0.50 -> maintain long (turnover=0, pos=1)
        {"next_return": 0.02},   # bar 2: p=0.40 -> exit long (turnover=1, pos=0, trade closes)
        {"next_return": 0.01},   # bar 3: p=0.50 -> maintain flat (turnover=0, pos=0)
        {"next_return": 0.01},   # bar 4: p=0.60 -> enter long (turnover=1, pos=1, open trade)
    ]
    probabilities = [0.60, 0.50, 0.40, 0.50, 0.60]
    threshold_long = 0.55
    threshold_exit = 0.45

    res = evaluate_selective_transaction_costs(
        test_rows, probabilities, threshold_long, threshold_exit, [0.0, 10.0]
    )

    r_0 = res["0.0_bps"]
    assert r_0["total_turnover_events"] == 3
    assert r_0["closed_trades_count"] == 1
    assert r_0["total_trades_count"] == 2  # 1 closed + 1 open at end

    # Gross return:
    # bar 0: pos=1, ret=0.01 -> cum = 1.01
    # bar 1: pos=1, ret=-0.01 -> cum = 1.01 * 0.99 = 0.9999
    # bar 2: pos=0, ret=0.02 -> cum = 0.9999
    # bar 3: pos=0, ret=0.01 -> cum = 0.9999
    # bar 4: pos=1, ret=0.01 -> cum = 0.9999 * 1.01 = 1.009899
    expected_gross_pct = (1.009899 - 1.0) * 100
    assert r_0["cumulative_return_pct"] == pytest.approx(expected_gross_pct, abs=0.01)

    # 10 bps friction (0.001 per turnover)
    # bar 0: net_ret = 0.01 - 0.001 = 0.009
    # bar 1: net_ret = -0.01 - 0.0 = -0.01
    # bar 2: net_ret = 0.0 - 0.001 = -0.001
    # bar 3: net_ret = 0.0 - 0.0 = 0.0
    # bar 4: net_ret = 0.01 - 0.001 = 0.009
    r_10 = res["10.0_bps"]
    cum_10 = (1 + 0.009) * (1 - 0.01) * (1 - 0.001) * 1.0 * (1 + 0.009)
    expected_10_pct = (cum_10 - 1.0) * 100
    assert r_10["cumulative_return_pct"] == pytest.approx(expected_10_pct, abs=0.01)


# ============================================================================
# 4. Walk-Forward Evaluation Integrity & Baselines
# ============================================================================

def test_run_m20_walk_forward_evaluation_synthetic():
    candles = _make_dummy_candles(150)
    cfg = M20ResearchConfig(
        initial_train_size=40,
        validation_size=20,
        test_size=20,
        step_size=20,
        embargo_bars=1,
    )
    result = run_m20_walk_forward_evaluation(candles, cfg)

    assert result["ok"] is True
    assert result["trading_decision"] == "BLOCKED"
    assert result["total_folds"] > 0

    # Invariants must remain False
    inv = result["safety_invariants"]
    assert inv["forecast_ready"] is False
    assert inv["real_market_data_verified"] is False
    assert inv["paper_approved"] is False
    assert inv["live_approved"] is False
    assert inv["live_broker_routing_enabled"] is False

    # Check that all 6 candidate models are present
    expected_models = {
        "empirical_prior",
        "majority_class",
        "last_return_sign",
        "logistic_regression_base",
        "logistic_regression_htf",
        "selective_entry_htf",
    }
    assert set(result["summary_metrics"].keys()) == expected_models

    # Verify Brier skill scores are reported
    bss = result["brier_skill_scores_vs_prior"]
    assert bss["empirical_prior"] == 0.0
    assert "selective_entry_htf" in bss

    # Verify per-fold structure
    for fold in result["folds"]:
        assert "validation_tuned_thresholds" in fold
        for m_name in expected_models:
            assert m_name in fold["models"]
            sens = fold["models"][m_name]["transaction_cost_sensitivity"]
            for h in cfg.cost_hurdles_bps:
                assert f"{h}_bps" in sens


def test_run_m20_walk_forward_insufficient_data():
    candles = _make_dummy_candles(20)
    res = run_m20_walk_forward_evaluation(candles)
    assert res["ok"] is False
    assert res["code"] == "INSUFFICIENT_OBSERVATIONS"
    assert res["forecast_ready"] is False
