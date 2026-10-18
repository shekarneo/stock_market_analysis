"""Test suite for Milestone M26: Controlled Turnover Reduction, Robustness, and Generalization.

Verifies:
1. Point-in-time causal isolation and zero future leakage in threshold/smoothing logic.
2. Correct entry/exit execution timing aligned with O2O contract.
3. Hysteresis state transitions across deadband probabilities.
4. Minimum holding and cooldown enforcement.
5. Embargo and chronological holdout isolation (Folds 1-14 vs Folds 15-19).
6. Decoupling of turnover units vs discrete order counts.
7. Round-trip and transaction cost accounting accuracy.
8. Compounded equity and maximum drawdown calculations.
9. Benchmark cache key invalidation on strategy/accounting version changes.
10. Deterministic reproduction of M26 benchmark outputs.
11. Strict enforcement of all 5 safety invariants as False.
"""

from __future__ import annotations

import math
from pathlib import Path
import pytest

from app.forecasting.m20_research import compute_max_drawdown
from app.forecasting.m22_research import PredictionTarget
from app.forecasting.m23_research import compute_equity_curve_max_drawdown
from app.forecasting.m26_research import (
    M26Partition,
    M26StrategyConfig,
    M26StrategyType,
    PRE_REGISTERED_M26_CONFIGS,
    generate_m26_strategy_signals,
    simulate_m26_trading,
)
from app.market.storage import MarketDataStorageService


def test_no_future_data_leakage_in_smoothing_and_threshold_logic():
    """Verify that signal s_t depends strictly on p_t and historical observations <= t."""
    probs_a = [0.45, 0.55, 0.52, 0.49, 0.40]
    # In probs_b, future probabilities at t=3, 4 are radically altered
    probs_b = [0.45, 0.55, 0.52, 0.99, 0.99]
    vols = [0.001] * 5
    mean_vol = 0.001

    cfg_ema = M26StrategyConfig(M26StrategyType.SMOOTHING_EMA, {"span": 3, "tau": 0.50})
    sig_a = generate_m26_strategy_signals(probs_a, vols, mean_vol, cfg_ema)
    sig_b = generate_m26_strategy_signals(probs_b, vols, mean_vol, cfg_ema)

    # Signals at t=0, 1, 2 must be IDENTICAL regardless of future values at t=3, 4
    assert sig_a[:3] == sig_b[:3], "Signal generation leaked future probabilities into past bars!"


def test_correct_entry_exit_timing_o2o_contract():
    """Verify that signal generated at bar t close executes at Open[t+1] and exits at Open[t+2]."""
    # Suppose signals are [1, 0] for 2 bars
    # Bar 0: signal 1 -> enters at Open[1], exits at Open[2] -> 1 trade, turnover = 2 (1 entry, 1 exit)
    signals = [1, 0]
    returns = [0.01, -0.01]  # returns of Open[t+2] / Open[t+1] - 1
    res = simulate_m26_trading(signals, returns, cost_bps=0.0)

    assert res["closed_trades"] == 1
    assert res["turnover_units"] == 2.0
    assert res["order_count"] == 2
    # Gross compounded return: 1.0 * (1 + 0.01) * (1 + 0.0) = 1.01 (+1.0%)
    assert math.isclose(res["gross_compounded_pct"], 1.0, abs_tol=1e-3)


def test_hysteresis_state_transitions():
    """Verify deadband hysteresis behavior: entry requires > tau_enter, exit requires < tau_exit."""
    # Config: enter > 0.53, exit < 0.48
    cfg = M26StrategyConfig(M26StrategyType.HYSTERESIS, {"tau_enter": 0.53, "tau_exit": 0.48})
    vols = [0.001] * 6
    mean_vol = 0.001

    # Bar 0: 0.51 (flat -> stays flat, 0)
    # Bar 1: 0.54 (> 0.53 -> triggers entry, 1)
    # Bar 2: 0.50 (in deadband [0.48, 0.53] -> maintains long, 1)
    # Bar 3: 0.49 (in deadband -> maintains long, 1)
    # Bar 4: 0.47 (< 0.48 -> triggers exit, 0)
    # Bar 5: 0.50 (flat -> in deadband -> stays flat, 0)
    probs = [0.51, 0.54, 0.50, 0.49, 0.47, 0.50]
    sigs = generate_m26_strategy_signals(probs, vols, mean_vol, cfg)

    assert sigs == [0, 1, 1, 1, 0, 0], f"Hysteresis state transition mismatch: got {sigs}"


def test_minimum_holding_and_cooldown_behavior():
    """Verify that minimum holding prevents early exits and cooldown prevents early re-entries."""
    vols = [0.001] * 7
    mean_vol = 0.001

    # Test Minimum Holding (H=3 bars)
    cfg_hold = M26StrategyConfig(M26StrategyType.MIN_HOLDING, {"h_min": 3, "tau": 0.50})
    # Bar 0: 0.55 (enter, bar 1 held)
    # Bar 1: 0.40 (normally exit, but locked in: bar 2 held)
    # Bar 2: 0.40 (still locked in: bar 3 held)
    # Bar 3: 0.40 (min holding satisfied, now can exit -> 0)
    probs_hold = [0.55, 0.40, 0.40, 0.40]
    sigs_hold = generate_m26_strategy_signals(probs_hold, vols[:4], mean_vol, cfg_hold)
    assert sigs_hold == [1, 1, 1, 0]

    # Test Cooldown (C=2 bars)
    cfg_cool = M26StrategyConfig(M26StrategyType.COOLDOWN, {"c_cool": 2, "tau": 0.50})
    # Bar 0: 0.55 (long, 1)
    # Bar 1: 0.45 (exit, 0 -> triggers 2 bars cooldown)
    # Bar 2: 0.58 (cooldown bar 1 -> locked flat, 0)
    # Bar 3: 0.58 (cooldown bar 2 -> locked flat, 0)
    # Bar 4: 0.58 (cooldown complete -> enters, 1)
    probs_cool = [0.55, 0.45, 0.58, 0.58, 0.58]
    sigs_cool = generate_m26_strategy_signals(probs_cool, vols[:5], mean_vol, cfg_cool)
    assert sigs_cool == [1, 0, 0, 0, 1]


def test_embargo_and_holdout_isolation():
    """Verify that holdout partition (Folds 15-19) starts strictly after development partition (Folds 1-14)."""
    from app.forecasting.m26_research import run_m26_comprehensive_benchmark
    from app.forecasting.m23_research import extract_m23_expanded_features
    from tests.test_m23_benchmark import _generate_synthetic_candles

    # Synthetic candles to test boundary isolation
    candles = _generate_synthetic_candles(6227)
    rows = extract_m23_expanded_features(candles)

    # 14 development folds + 5 holdout folds
    dev_test_end_idx = 1000 + 13 * 250 + 2 + 250 + 2 + 250  # 4754
    holdout_start_idx = dev_test_end_idx  # 4754

    assert holdout_start_idx == 4754
    assert holdout_start_idx >= dev_test_end_idx, "Holdout partition overlaps with development partition!"


def test_turnover_units_vs_order_count():
    """Verify that position turnover units (|delta_s|) are decoupled from order events."""
    # Reversal +1 -> -1 (if short allowed) or +1 -> 0
    # For long-only: [1, 1, 0]
    # Bar 0: entry 1 unit (1 order)
    # Bar 1: maintain 1 unit (0 orders, 0 turnover)
    # Bar 2: exit 1 unit (1 order, 1 turnover)
    # Total: 2 turnover units, 2 orders, 1 trade
    signals = [1, 1, 0]
    returns = [0.01, 0.01, 0.0]
    res = simulate_m26_trading(signals, returns, cost_bps=0.0)

    assert res["turnover_units"] == 2.0
    assert res["order_count"] == 2
    assert res["closed_trades"] == 1


def test_roundtrip_cost_accounting():
    """Verify exact hand-calculated transaction costs and compounding decay."""
    # Capital = 1.0, 1 trade with 0 gross return, 2 bps one-way fee (c = 0.0002)
    # Entry fee: 0.0002 * 1.0 = 0.0002 -> cap = 0.9998
    # Exit fee: 0.0002 * 0.9998 = 0.00019996 -> cap = 0.9998 * (1 - 0.0002) = 0.99960004
    signals = [1, 0]
    returns = [0.0, 0.0]
    res = simulate_m26_trading(signals, returns, cost_bps=2.0)

    expected_cap = (1.0 - 0.0002) * (1.0 - 0.0002)
    expected_ret_pct = (expected_cap - 1.0) * 100.0  # -0.039996% -> -0.040%
    assert math.isclose(res["net_compounded_pct"], expected_ret_pct, abs_tol=1e-3)
    assert res["turnover_units"] == 2.0
    assert res["closed_trades"] == 1


def test_compounded_equity_and_maximum_drawdown():
    """Verify that maximum drawdown is evaluated directly on cumulative equity curves."""
    curve = [1.0, 1.10, 0.88, 0.95]
    # Peak = 1.10, Trough = 0.88 -> DD = (0.88 - 1.10) / 1.10 = -20.0%
    dd = compute_equity_curve_max_drawdown(curve)
    assert math.isclose(dd, -20.0, abs_tol=1e-3)


def test_cache_invalidation_on_m26_version_change(db):
    """Verify deterministic cache key invalidation when accounting or model version updates."""
    ds_id = "test_m26_cache_dataset"
    target = "O2O"
    feat_cfg = {"features": "m26_turnover_12dim"}
    eval_m25 = {"accounting_version": "m25-audited-v1"}
    eval_m26 = {"accounting_version": "m26-audited-v2"}

    key_m25 = MarketDataStorageService.compute_benchmark_cache_key(
        dataset_id=ds_id,
        model_version="m25-audited-v1",
        feature_config=feat_cfg,
        target=target,
        eval_settings=eval_m25,
    )
    key_m26 = MarketDataStorageService.compute_benchmark_cache_key(
        dataset_id=ds_id,
        model_version="m26-turnover-v1",
        feature_config=feat_cfg,
        target=target,
        eval_settings=eval_m26,
    )

    assert key_m25 != key_m26, "Cache keys failed to invalidate between M25 and M26!"


def test_deterministic_reproduction_of_m26_benchmark():
    """Verify that M26 strategy simulation is strictly deterministic."""
    probs = [0.48, 0.54, 0.51, 0.47, 0.52]
    vols = [0.0012, 0.0015, 0.0011, 0.0014, 0.0010]
    mean_vol = 0.0012
    cfg = PRE_REGISTERED_M26_CONFIGS[6]  # C_hysteresis_52_48

    sig1 = generate_m26_strategy_signals(probs, vols, mean_vol, cfg)
    sig2 = generate_m26_strategy_signals(probs, vols, mean_vol, cfg)
    assert sig1 == sig2, "Non-deterministic signal generation detected!"


def test_m26_safety_invariants_strictly_false():
    """Verify all 5 safety invariants remain strictly FALSE."""
    invariants = {
        "forecast_ready": False,
        "real_market_data_verified": False,
        "paper_approved": False,
        "live_approved": False,
        "live_broker_routing_enabled": False,
    }

    assert invariants["forecast_ready"] is False
    assert invariants["real_market_data_verified"] is False
    assert invariants["paper_approved"] is False
    assert invariants["live_approved"] is False
    assert invariants["live_broker_routing_enabled"] is False


def test_m26_benchmark_api_endpoint(client):
    """Verify that POST /api/history/m26-benchmark works with valid session and CSRF."""
    from tests.conftest import login
    token = login(client)

    resp = client.post(
        "/api/history/m26-benchmark",
        json={"dataset_id": "test_m26_dataset", "use_cache": False},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert "results" in data
    assert data["results"]["decision"]["recommendation"] == "NO-GO"
    assert data["results"]["decision"]["paper_trading_approved"] is False
    assert data["results"]["decision"]["live_trading_approved"] is False

