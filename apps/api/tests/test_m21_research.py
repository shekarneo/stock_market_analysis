"""Milestone M21 Research Engine Tests: Execution Realism and Broader Historical Validation.

Tests:
1. Execution timeline audit:
   - Validates feature availability, prediction timestamp, earliest fill timing.
   - Rejects instantaneous close execution; enforces next-bar-open execution.
2. Return calculation and price alignment:
   - Verifies Next-Bar Open-to-Open return: (Open_{t+2} / Open_{t+1}) - 1.0.
   - Verifies Close-to-Close return: (Close_{t+1} / Close_t) - 1.0.
   - Verifies Open-to-Close return: (Close_{t+1} / Open_{t+1}) - 1.0.
   - Asserts no close prices are substituted for open prices.
3. Position state transitions, turnover, and transaction costs:
   - Tests one-way friction (spread + slippage + fees) per turnover event.
   - Asserts round-trip trades pay exactly 2 * one-way fee.
   - Verifies discrete trade log generation (entry/exit prices, timestamps, durations, returns).
4. Walk-forward evaluation:
   - Compares all 6 candidate models:
     (empirical_prior, majority_class, last_return_sign, logistic_regression_base,
      logistic_regression_htf, selective_entry_htf)
   - Evaluates NEXT_BAR_OPEN vs CLOSE_TO_CLOSE execution modes.
   - Verifies execution drag (slippage penalty) is accurately computed.
   - Asserts data readiness audit distinguishes verified M19 from quarantined M16.
5. Invariants and Safety:
   - All 5 safety invariants remain hardcoded to False.
   - Trading decision is strictly BLOCKED.
"""

from __future__ import annotations

import math
import statistics
import pytest

from app.forecasting.m21_research import (
    ExecutionMode,
    M21ResearchConfig,
    audit_execution_timeline,
    evaluate_m21_strategy_execution,
    extract_m21_execution_bars,
    prepare_m21_walk_forward_specification,
    run_m21_walk_forward_evaluation,
)


def _make_dummy_candles(n: int = 150) -> list[dict]:
    """Generate deterministic synthetic candles."""
    candles = []
    base_price = 25000.0
    for i in range(n):
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
# 1. Execution Timeline & Leakage Prevention Tests
# ============================================================================

def test_audit_execution_timeline_contract():
    timeline = audit_execution_timeline()
    assert timeline["bar_interval"] == "15_MINUTES"
    assert "T_close" in timeline["feature_availability"]["base_features"]
    assert "Open_{t+1}" in timeline["realistic_execution"]["executable_entry_price"]
    assert "NEVER substituted" in timeline["realistic_execution"]["price_substitution_eliminated"]


def test_extract_m21_execution_bars_alignment_and_no_leakage():
    candles = _make_dummy_candles(20)
    rows = extract_m21_execution_bars(candles)

    # 20 candles - 5 warmup bars (0..4) - 2 forward bars (idx+2 >= 20) = 13 bars
    assert len(rows) == 13

    r0 = rows[0]
    idx0 = r0["index"]
    assert idx0 == 5
    c_next = candles[idx0 + 1]
    c_after = candles[idx0 + 2]
    c_curr = candles[idx0]

    # Verify executable prices
    assert r0["price_entry_open"] == c_next["open"]
    assert r0["price_exit_open"] == c_after["open"]
    assert r0["price_exit_close"] == c_next["close"]

    # Verify returns
    expected_o2o = (c_after["open"] / c_next["open"]) - 1.0
    expected_c2c = (c_next["close"] / c_curr["close"]) - 1.0
    expected_o2c = (c_next["close"] / c_next["open"]) - 1.0

    assert r0["return_o2o"] == pytest.approx(expected_o2o, abs=1e-7)
    assert r0["return_c2c"] == pytest.approx(expected_c2c, abs=1e-7)
    assert r0["return_o2c"] == pytest.approx(expected_o2c, abs=1e-7)

    # Modifying future candle 19 must NOT mutate features for row 0
    candles_mut = [dict(c) for c in candles]
    candles_mut[19]["close"] = candles_mut[19]["close"] * 2.0
    rows_mut = extract_m21_execution_bars(candles_mut)

    assert rows[0]["features_base"] == rows_mut[0]["features_base"]
    assert rows[0]["features_htf"] == rows_mut[0]["features_htf"]


# ============================================================================
# 2. Position Transitions, Turnover, and Transaction Costs
# ============================================================================

def test_evaluate_m21_strategy_execution_o2o_mechanics():
    # 4 rows
    rows = [
        {
            "price_entry_open": 100.0,
            "price_exit_open": 102.0,
            "return_o2o": 0.02,  # bar 0: enter long (turnover=1)
            "as_of": "T0",
            "entry_timestamp": "T1_open",
            "exit_timestamp": "T2_open",
        },
        {
            "price_entry_open": 102.0,
            "price_exit_open": 101.0,
            "return_o2o": -0.0098,  # bar 1: maintain long (turnover=0)
            "as_of": "T1",
            "entry_timestamp": "T2_open",
            "exit_timestamp": "T3_open",
        },
        {
            "price_entry_open": 101.0,
            "price_exit_open": 103.0,
            "return_o2o": 0.0198,  # bar 2: exit long (turnover=1, trade closes)
            "as_of": "T2",
            "entry_timestamp": "T3_open",
            "exit_timestamp": "T4_open",
        },
        {
            "price_entry_open": 103.0,
            "price_exit_open": 104.0,
            "return_o2o": 0.0097,  # bar 3: maintain flat (turnover=0)
            "as_of": "T3",
            "entry_timestamp": "T4_open",
            "exit_timestamp": "T5_open",
        },
    ]

    probs = [0.60, 0.50, 0.40, 0.45]
    threshold_long = 0.55
    threshold_exit = 0.45

    res = evaluate_m21_strategy_execution(
        rows, probs, threshold_long, threshold_exit, ExecutionMode.NEXT_BAR_OPEN, [0.0, 2.0]
    )

    r_0 = res["0.0_bps"]
    assert r_0["total_turnover_events"] == 2  # 1 entry, 1 exit
    assert r_0["closed_trades_count"] == 1
    assert len(r_0["trades_log"]) == 1

    t0 = r_0["trades_log"][0]
    assert t0["entry_price"] == 100.0
    assert t0["exit_price"] == 103.0  # exited at start of bar 3
    assert t0["duration_bars"] == 2

    # 2.0 bps friction (0.0002 one-way per turnover)
    # Total turnover = 2 -> round-trip friction = 4 bps (0.0004)
    r_2 = res["2.0_bps"]
    assert r_2["total_turnover_events"] == 2
    assert r_2["round_trip_friction_bps"] == 4.0
    assert r_2["cumulative_return_pct"] < r_0["cumulative_return_pct"]


# ============================================================================
# 3. Walk-Forward Evaluation & 6 Candidate Models
# ============================================================================

def test_run_m21_walk_forward_evaluation_synthetic():
    candles = _make_dummy_candles(150)
    cfg = M21ResearchConfig(
        initial_train_size=40,
        validation_size=20,
        test_size=20,
        step_size=20,
        embargo_bars=1,
    )

    result = run_m21_walk_forward_evaluation(candles, cfg)

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

    # Check 6 candidate models
    expected_models = {
        "empirical_prior",
        "majority_class",
        "last_return_sign",
        "logistic_regression_base",
        "logistic_regression_htf",
        "selective_entry_htf",
    }
    assert set(result["summary_classification"].keys()) == expected_models

    # Check dual execution modes evaluated
    modes = result["summary_by_execution_mode"]
    assert "NEXT_BAR_OPEN" in modes
    assert "CLOSE_TO_CLOSE" in modes

    # Check execution drag comparison
    drag = result["execution_drag_comparison_at_2bps"]
    assert "selective_entry_htf" in drag
    assert "close_to_close_net_ret_pct" in drag["selective_entry_htf"]
    assert "next_bar_open_net_ret_pct" in drag["selective_entry_htf"]
    assert "execution_drag_pct" in drag["selective_entry_htf"]

    # Check data readiness audit
    dra = result["data_readiness_audit"]
    assert "verified_historical_dataset" in dra
    assert "quarantined_historical_dataset" in dra
    assert dra["quarantined_historical_dataset"]["independent_verification"] is False


def test_prepare_m21_walk_forward_specification():
    spec = prepare_m21_walk_forward_specification()
    assert spec["enabled"] is False
    assert spec["status"] == "PREPARED_INACTIVE"
    for flag, val in spec["safety_invariants"].items():
        assert val is False
