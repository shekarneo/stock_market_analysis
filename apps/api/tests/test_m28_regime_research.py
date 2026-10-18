"""Unit and integration test suite for Milestone M28: Causal Market Regime Detection & Volatility Gating.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from app.forecasting.m27_htf_research import (
    HTFCandle,
    HTFInterval,
    resample_candles_to_htf,
)
from app.forecasting.m28_regime_research import (
    MarketRegime,
    compute_causal_adx_and_regimes,
    extract_regime_aligned_features,
    run_regime_walk_forward_benchmark,
)
from app.settings import REPO_ROOT


@pytest.fixture
def sample_synthetic_htf_candles() -> list[HTFCandle]:
    """Generate 60 synthetic HTF candles containing:
    - 20 bars of strong uptrend (Bull regime)
    - 20 bars of tight sideways oscillation (Sideways regime)
    - 20 bars of strong downtrend (Bear regime)
    """
    candles = []
    base_p = 25000.0

    # Phase 1: Strong uptrend (+50 points per bar)
    for i in range(20):
        o = base_p + i * 50.0
        c = o + 40.0
        hi = c + 15.0
        lo = o - 5.0
        candles.append(
            HTFCandle(
                timestamp=f"2026-09-{i+1:02d} 12:15:00",
                open=o, high=hi, low=lo, close=c, volume=10000.0, open_interest=0.0,
                constituent_bars=12, session_date=f"2026-09-{i+1:02d}", interval=HTFInterval.HALF_DAY,
            )
        )

    # Phase 2: Sideways oscillation (+/- 5 points, tight range)
    curr_base = candles[-1].close
    for i in range(20):
        delta = 5.0 if i % 2 == 0 else -5.0
        o = curr_base
        c = curr_base + delta
        hi = max(o, c) + 3.0
        lo = min(o, c) - 3.0
        candles.append(
            HTFCandle(
                timestamp=f"2026-09-{21+i:02d} 12:15:00" if 21+i <= 30 else f"2026-10-{i-9:02d} 12:15:00",
                open=o, high=hi, low=lo, close=c, volume=3000.0, open_interest=0.0,
                constituent_bars=12, session_date="2026-10-01", interval=HTFInterval.HALF_DAY,
            )
        )

    # Phase 3: Strong downtrend (-60 points per bar)
    curr_base = candles[-1].close
    for i in range(20):
        o = curr_base - i * 60.0
        c = o - 50.0
        hi = o + 5.0
        lo = c - 15.0
        candles.append(
            HTFCandle(
                timestamp=f"2026-10-{11+i:02d} 12:15:00",
                open=o, high=hi, low=lo, close=c, volume=12000.0, open_interest=0.0,
                constituent_bars=12, session_date=f"2026-10-{11+i:02d}", interval=HTFInterval.HALF_DAY,
            )
        )

    return candles


def test_adx_causality_and_bounds(sample_synthetic_htf_candles):
    """Verify ADX and +DI/-DI remain within valid [0, 100] bounds and respect causal bounds."""
    indicators = compute_causal_adx_and_regimes(sample_synthetic_htf_candles, adx_period=14)
    assert len(indicators) == len(sample_synthetic_htf_candles)

    for ind in indicators:
        assert 0.0 <= ind.adx <= 100.0, f"ADX out of bounds: {ind.adx}"
        assert 0.0 <= ind.plus_di <= 100.0, f"+DI out of bounds: {ind.plus_di}"
        assert 0.0 <= ind.minus_di <= 100.0, f"-DI out of bounds: {ind.minus_di}"
        assert 0.1 <= ind.hurst <= 0.9, f"Hurst exponent out of bounds: {ind.hurst}"


def test_regime_classification_state_transitions(sample_synthetic_htf_candles):
    """Verify market regimes transition from Bull to Sideways to Bear."""
    indicators = compute_causal_adx_and_regimes(sample_synthetic_htf_candles, adx_period=7, adx_threshold=15.0)

    # In Phase 1 (uptrend), regime should detect TRENDING_BULL
    bull_detected = any(ind.regime == MarketRegime.TRENDING_BULL for ind in indicators[10:20])
    assert bull_detected, "Failed to detect TRENDING_BULL in sustained uptrend"

    # In Phase 2 (sideways oscillation), regime should transition to SIDEWAYS_CONSOLIDATION
    sideways_detected = any(ind.regime == MarketRegime.SIDEWAYS_CONSOLIDATION for ind in indicators[30:40])
    assert sideways_detected, "Failed to detect SIDEWAYS_CONSOLIDATION in flat oscillation"

    # In Phase 3 (downtrend), regime should detect TRENDING_BEAR
    bear_detected = any(ind.regime == MarketRegime.TRENDING_BEAR for ind in indicators[50:60])
    assert bear_detected, "Failed to detect TRENDING_BEAR in sustained downtrend"


def test_no_future_leakage_in_regime_indicators(sample_synthetic_htf_candles):
    """Verify indicator calculation at bar t is strictly invariant to future data at t+k."""
    t_cutoff = 35
    truncated_candles = sample_synthetic_htf_candles[:t_cutoff + 1]

    ind_full = compute_causal_adx_and_regimes(sample_synthetic_htf_candles)
    ind_trunc = compute_causal_adx_and_regimes(truncated_candles)

    # Compare indicator at t_cutoff
    assert abs(ind_full[t_cutoff].adx - ind_trunc[t_cutoff].adx) < 1e-6
    assert abs(ind_full[t_cutoff].plus_di - ind_trunc[t_cutoff].plus_di) < 1e-6
    assert abs(ind_full[t_cutoff].minus_di - ind_trunc[t_cutoff].minus_di) < 1e-6
    assert abs(ind_full[t_cutoff].hurst - ind_trunc[t_cutoff].hurst) < 1e-6
    assert ind_full[t_cutoff].regime == ind_trunc[t_cutoff].regime


def test_m28_safety_invariants_strictly_false():
    """Verify all 5 hard financial safety invariants remain strictly False in M28 benchmark."""
    dataset_file = REPO_ROOT / "var" / "datasets" / "derived_nifty_15m_m23_bc7d31bceebf13a3.json"
    if not dataset_file.exists():
        pytest.skip("Dataset file not available for fast slice run")

    with open(dataset_file, "r") as f:
        payload = json.load(f)

    candles = payload["candles"][:1500]
    result = run_regime_walk_forward_benchmark(
        candles_15m=candles,
        dataset_id=payload["dataset_id"],
        interval=HTFInterval.HALF_DAY,
        initial_train_bars=40,
        val_step_bars=10,
        embargo_bars=2,
        holdout_fold_count=2,
    )

    inv = result["safety_invariants"]
    assert inv["forecast_ready"] is False
    assert inv["real_market_data_verified"] is False
    assert inv["paper_approved"] is False
    assert inv["live_approved"] is False
    assert inv["live_broker_routing_enabled"] is False


def test_regime_distribution_on_nifty_dataset():
    """Verify that on real NIFTY 1-year data, Sideways Consolidation represents a significant portion of bars."""
    dataset_file = REPO_ROOT / "var" / "datasets" / "derived_nifty_15m_m23_bc7d31bceebf13a3.json"
    if not dataset_file.exists():
        pytest.skip("Dataset file not available")

    with open(dataset_file, "r") as f:
        payload = json.load(f)

    htf = resample_candles_to_htf(payload["candles"], target_interval=HTFInterval.HALF_DAY)
    ind = compute_causal_adx_and_regimes(htf)

    regimes = [x.regime for x in ind]
    sideways_count = sum(1 for r in regimes if r == MarketRegime.SIDEWAYS_CONSOLIDATION)
    pct_sideways = (sideways_count / len(regimes)) * 100.0

    # Real equity index markets spend between 30% and 75% of time consolidating
    assert 25.0 <= pct_sideways <= 85.0, f"Unexpected sideways prevalence: {pct_sideways:.1f}%"
