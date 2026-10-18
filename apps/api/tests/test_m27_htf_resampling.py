"""Test suite for Milestone M27: Higher-Timeframe (1-Hour & Half-Day) Resampling,
Target Alignment, and Walk-Forward Research Engine.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from app.forecasting.m27_htf_research import (
    HTFInterval,
    HTFCandle,
    extract_htf_features_and_targets,
    resample_candles_to_htf,
    run_htf_walk_forward_benchmark,
)
from app.settings import REPO_ROOT


@pytest.fixture
def sample_synthetic_15m_candles() -> list[list]:
    """Generate 50 synthetic 15m candles across 2 trading days (25 candles per day)."""
    candles = []
    base_price = 25000.0

    # Day 1: 2026-10-01 (09:15 to 15:15)
    for i in range(25):
        h = 9 + (15 + i * 15) // 60
        m = (15 + i * 15) % 60
        ts = f"2026-10-01 {h:02d}:{m:02d}:00"
        o = base_price + i * 10.0
        c = o + 5.0
        hi = max(o, c) + 8.0
        lo = min(o, c) - 6.0
        vol = 1000.0 + i * 50.0
        candles.append([ts, o, hi, lo, c, vol, 0.0])

    # Day 2: 2026-10-02 (09:15 to 15:15)
    base_price = 25300.0
    for i in range(25):
        h = 9 + (15 + i * 15) // 60
        m = (15 + i * 15) % 60
        ts = f"2026-10-02 {h:02d}:{m:02d}:00"
        o = base_price + i * 12.0
        c = o - 4.0
        hi = max(o, c) + 10.0
        lo = min(o, c) - 7.0
        vol = 1200.0 + i * 40.0
        candles.append([ts, o, hi, lo, c, vol, 0.0])

    return candles


def test_resampling_geometric_integrity(sample_synthetic_15m_candles):
    """Verify resampled candles strictly preserve geometric integrity and volume summation."""
    htf_1h = resample_candles_to_htf(sample_synthetic_15m_candles, target_interval=HTFInterval.ONE_HOUR)
    
    assert len(htf_1h) > 0
    for bar in htf_1h:
        assert bar.high >= bar.low
        assert bar.high >= max(bar.open, bar.close) - 1e-4
        assert bar.low <= min(bar.open, bar.close) + 1e-4
        assert bar.volume > 0.0
        assert bar.constituent_bars in {1, 4}  # 4 bars for normal hours, 1 for final tail bar


def test_session_boundary_preservation(sample_synthetic_15m_candles):
    """Verify candles from different calendar dates are never merged across session boundaries."""
    htf_half_day = resample_candles_to_htf(sample_synthetic_15m_candles, target_interval=HTFInterval.HALF_DAY)
    
    # 2 days, 2 bars per day = 4 bars total
    assert len(htf_half_day) == 4
    
    # Verify session dates
    assert htf_half_day[0].session_date == "2026-10-01"
    assert htf_half_day[1].session_date == "2026-10-01"
    assert htf_half_day[2].session_date == "2026-10-02"
    assert htf_half_day[3].session_date == "2026-10-02"

    # Bar 0 constituent count (AM) should be 12 (09:15 to 12:00)
    assert htf_half_day[0].constituent_bars == 12
    # Bar 1 constituent count (PM) should be 13 (12:15 to 15:15)
    assert htf_half_day[1].constituent_bars == 13


def test_causal_point_in_time_availability(sample_synthetic_15m_candles):
    """Verify HTF bar timestamp matches the close of the final constituent 15m candle."""
    htf_1h = resample_candles_to_htf(sample_synthetic_15m_candles, target_interval=HTFInterval.ONE_HOUR)
    
    # First 1-hour bar covers 09:15, 09:30, 09:45, 10:00 -> point-in-time close is 10:00:00
    assert htf_1h[0].timestamp == "2026-10-01 10:00:00"
    assert htf_1h[0].open == sample_synthetic_15m_candles[0][1]
    assert htf_1h[0].close == sample_synthetic_15m_candles[3][4]


def test_strict_o2o_target_alignment(sample_synthetic_15m_candles):
    """Verify O2O target is calculated from O_{t+1} to O_{t+2} without leakage."""
    htf_1h = resample_candles_to_htf(sample_synthetic_15m_candles, target_interval=HTFInterval.ONE_HOUR)
    rows, feat_names = extract_htf_features_and_targets(htf_1h)

    assert len(rows) > 0
    assert "ret_1" in feat_names
    assert "trend_hh_ll" in feat_names

    for r in rows:
        if r.target_return is not None:
            expected_ret = (r.target_price_open - r.exec_price_open) / r.exec_price_open
            assert abs(r.target_return - expected_ret) < 1e-6
            assert r.target_binary == (1 if expected_ret > 0 else 0)


def test_m27_safety_invariants_strictly_false():
    """Verify all 5 hard financial safety invariants remain strictly False."""
    dataset_file = REPO_ROOT / "var" / "datasets" / "derived_nifty_15m_m23_bc7d31bceebf13a3.json"
    if not dataset_file.exists():
        pytest.skip("Dataset file not available for full benchmark run")

    with open(dataset_file, "r") as f:
        payload = json.load(f)

    candles = payload["candles"][:1500]  # Fast slice
    summary = run_htf_walk_forward_benchmark(
        candles_15m=candles,
        dataset_id=payload["dataset_id"],
        interval=HTFInterval.HALF_DAY,
        initial_train_bars=50,
        val_step_bars=10,
        embargo_bars=2,
        holdout_fold_count=2,
    )

    inv = summary.safety_invariants
    assert inv["forecast_ready"] is False
    assert inv["real_market_data_verified"] is False
    assert inv["paper_approved"] is False
    assert inv["live_approved"] is False
    assert inv["live_broker_routing_enabled"] is False


def test_fee_to_alpha_ratio_on_real_nifty_data():
    """Verify that resampling from 15m to 1H significantly increases mean bar displacement."""
    dataset_file = REPO_ROOT / "var" / "datasets" / "derived_nifty_15m_m23_bc7d31bceebf13a3.json"
    if not dataset_file.exists():
        pytest.skip("Dataset file not available")

    with open(dataset_file, "r") as f:
        payload = json.load(f)

    candles = payload["candles"]
    htf_1h = resample_candles_to_htf(candles, target_interval=HTFInterval.ONE_HOUR)
    htf_half = resample_candles_to_htf(candles, target_interval=HTFInterval.HALF_DAY)

    rows_1h, _ = extract_htf_features_and_targets(htf_1h)
    rows_half, _ = extract_htf_features_and_targets(htf_half)

    ret_1h = [abs(r.target_return) for r in rows_1h if r.target_return is not None]
    ret_half = [abs(r.target_return) for r in rows_half if r.target_return is not None]

    mean_disp_1h = sum(ret_1h) / len(ret_1h) * 100.0
    mean_disp_half = sum(ret_half) / len(ret_half) * 100.0

    # 15m mean displacement is known to be ~0.12%
    # 1H is empirically ~0.207% (> 0.18%)
    assert mean_disp_1h > 0.18, f"1H displacement {mean_disp_1h:.3f}% is too low"
    # Half-day is empirically ~0.443% (> 0.40%)
    assert mean_disp_half > 0.40, f"Half-day displacement {mean_disp_half:.3f}% is too low"

    # Fee drag of 2 bps roundtrip (0.04% = 0.04% displacement)
    # Fee to alpha ratio on Half-day should be < 10%
    fee_ratio_half = (0.04 / mean_disp_half) * 100.0
    assert fee_ratio_half < 10.0, f"Half-day fee-to-alpha ratio {fee_ratio_half:.2f}% exceeds 10%"
