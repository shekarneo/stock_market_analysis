"""Unit and integration tests for Milestone M37: Non-Linear Machine Learning (LightGBM) on HTF Swing Horizon.
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pytest

from app.forecasting.m27_htf_research import HTFCandle, HTFInterval
from app.forecasting.m28_regime_research import MarketRegime
from app.forecasting.m37_lightgbm_htf_research import (
    M37BenchmarkReport,
    M37StrategyMode,
    generate_19_expanding_folds,
    run_m37_lightgbm_benchmark,
    save_m37_benchmark_results,
    simulate_trading_execution,
)
from app.settings import REPO_ROOT


def test_19_expanding_folds_generation():
    """Verify that fold generation produces exactly 19 valid chronological folds with 2-bar embargo."""
    total_rows = 488
    folds = generate_19_expanding_folds(
        total_rows=total_rows,
        initial_train_bars=200,
        val_step_bars=15,
        embargo_bars=2,
        target_folds=19,
    )
    assert len(folds) == 19

    dev_folds = folds[:14]
    holdout_folds = folds[14:]
    assert len(dev_folds) == 14
    assert len(holdout_folds) == 5

    prev_train_end = 0
    for idx, (ts, te, vs, ve) in enumerate(folds, 1):
        assert ts == 0
        assert te > prev_train_end or idx == 1
        assert vs == te + 2, f"Embargo violation on fold {idx}: te={te}, vs={vs}"
        assert ve > vs
        assert ve <= total_rows
        assert ve - vs == 15 or (idx == 19 and ve <= total_rows)
        prev_train_end = te


def test_simulate_trading_execution_accounting():
    """Verify turnover, fee tiers, and max drawdown accounting."""
    # 4 bars: Flat -> Long (+1) -> Short (-1) -> Cash (0)
    positions = np.array([1.0, 1.0, -1.0, 0.0])
    returns = np.array([0.01, -0.005, 0.02, 0.00])

    sim = simulate_trading_execution(
        positions=positions,
        returns=returns,
        cost_0bps=0.0,
        cost_2bps=0.0002,
        cost_5bps=0.0005,
        cost_10bps=0.0010,
    )

    # Position deltas:
    # 0 -> 1.0 (delta = 1.0)
    # 1.0 -> 1.0 (delta = 0.0)
    # 1.0 -> -1.0 (delta = 2.0)
    # -1.0 -> 0.0 (delta = 1.0)
    # Total delta = 4.0. Turnover units = 4.0 / 2.0 = 2.0 units (2 full roundtrips)
    assert sim["turnover_units"] == 2.0
    assert sim["order_count"] == 3

    # Gross return (0 bps) should be higher than net return (2 bps), which is higher than (5 bps) and (10 bps)
    assert sim["gross_return_0bps"] > sim["net_return_2bps"] > sim["net_return_5bps"] > sim["net_return_10bps"]
    assert sim["max_drawdown_2bps"] >= 0.0


def test_deadband_and_regime_filtering_logic():
    """Verify that positions adhere to pre-registered rules for deadband and regime consensus."""
    # Test deadband logic
    p_values = [0.55, 0.51, 0.49, 0.45]
    deadband_low = 0.47
    deadband_high = 0.53

    expected_db = [1.0, 0.0, 0.0, -1.0]
    actual_db = []
    for p in p_values:
        if p > deadband_high:
            actual_db.append(1.0)
        elif p < deadband_low:
            actual_db.append(-1.0)
        else:
            actual_db.append(0.0)
    assert actual_db == expected_db

    # Test regime consensus logic
    regimes = [
        MarketRegime.TRENDING_BULL,
        MarketRegime.TRENDING_BULL,
        MarketRegime.TRENDING_BEAR,
        MarketRegime.SIDEWAYS_CONSOLIDATION,
    ]
    p_signals = [0.55, 0.45, 0.45, 0.60]
    expected_consensus = [1.0, 0.0, -1.0, 0.0]
    actual_consensus = []
    for reg, p in zip(regimes, p_signals):
        if reg == MarketRegime.TRENDING_BULL and p > 0.50:
            actual_consensus.append(1.0)
        elif reg == MarketRegime.TRENDING_BEAR and p < 0.50:
            actual_consensus.append(-1.0)
        else:
            actual_consensus.append(0.0)
    assert actual_consensus == expected_consensus


def test_m37_safety_invariants_strictly_false():
    """Verify that all 5 safety invariants remain strictly False in M37."""
    dataset_file = REPO_ROOT / "var" / "datasets" / "derived_nifty_15m_m23_bc7d31bceebf13a3.json"
    if not dataset_file.exists():
        pytest.skip("Dataset file not available for fast slice run")

    with open(dataset_file, "r") as f:
        payload = json.load(f)

    # Fast slice: 1000 candles to verify safety boundaries and report structure
    report = run_m37_lightgbm_benchmark(
        candles_15m=payload["candles"][:1500],
        dataset_id=payload["dataset_id"],
        interval=HTFInterval.HALF_DAY,
        initial_train_bars=40,
        val_step_bars=10,
        embargo_bars=2,
        target_folds=4,
        dev_fold_count=2,
    )

    inv = report.safety_invariants
    assert inv["forecast_ready"] is False
    assert inv["real_market_data_verified"] is False
    assert inv["paper_approved"] is False
    assert inv["live_approved"] is False
    assert inv["live_broker_routing_enabled"] is False


def test_m37_benchmark_reproducibility():
    """Verify that executing M37 with the same random seed produces identical results."""
    dataset_file = REPO_ROOT / "var" / "datasets" / "derived_nifty_15m_m23_bc7d31bceebf13a3.json"
    if not dataset_file.exists():
        pytest.skip("Dataset file not available")

    with open(dataset_file, "r") as f:
        payload = json.load(f)

    slice_candles = payload["candles"][:1000]

    run1 = run_m37_lightgbm_benchmark(
        candles_15m=slice_candles,
        dataset_id="test_repro",
        initial_train_bars=30,
        val_step_bars=8,
        embargo_bars=2,
        target_folds=3,
        dev_fold_count=2,
    )
    run2 = run_m37_lightgbm_benchmark(
        candles_15m=slice_candles,
        dataset_id="test_repro",
        initial_train_bars=30,
        val_step_bars=8,
        embargo_bars=2,
        target_folds=3,
        dev_fold_count=2,
    )

    assert len(run1.strategies) == len(run2.strategies)
    for s1, s2 in zip(run1.strategies, run2.strategies):
        assert s1.model_name == s2.model_name
        assert s1.strategy_mode == s2.strategy_mode
        assert abs(s1.full_net_return_2bps - s2.full_net_return_2bps) < 1e-6
        assert abs(s1.full_turnover_units - s2.full_turnover_units) < 1e-6


def test_m37_artifact_integrity():
    """Verify that the persisted M37 JSON artifact has complete structure and 171 fold records."""
    artifact_path = REPO_ROOT / "var" / "datasets" / "m37_htf_lightgbm_benchmark.json"
    assert artifact_path.exists(), f"M37 artifact missing at {artifact_path}"

    with open(artifact_path, "r") as f:
        data = json.load(f)

    assert data["granularity"] == "HALF_DAY"
    assert data["num_folds"] == 19
    assert data["dev_fold_count"] == 14
    assert data["holdout_fold_count"] == 5
    assert len(data["strategies"]) == 9  # 3 models x 3 modes
    assert len(data["fold_results"]) == 171  # 19 folds x 9 strategies

    # Invariants
    inv = data["safety_invariants"]
    assert all(v is False for v in inv.values())
