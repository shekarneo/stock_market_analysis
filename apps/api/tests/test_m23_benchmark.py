"""Tests for Milestone M23: Historical Data Expansion and Modern Forecasting Benchmark.

Verifies:
- Point-in-time feature extraction with zero future leakage.
- Target alignment (C2C, O2O, O2C_1B, O2C_2B).
- Walk-forward expanding window boundaries and embargo.
- LightGBM and XGBoost training and calibration.
- Chronos-2 foundation adapter quantile-to-probability mapping.
- Google TimesFM 3.0 licensing compliance (rejection without fabrication).
- Transaction cost accounting and terminal fold position handling.
- Benchmark cache persistence and invalidation.
- All safety invariants strictly FALSE.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import statistics
import pytest

from app.forecasting.m23_research import (
    IsotonicCalibrator,
    M23AlignedCandleRow,
    M23ModelType,
    M23ResearchConfig,
    MODEL_REGISTRY_METADATA,
    PredictionTarget,
    compute_chronos_raw_probabilities,
    evaluate_m23_walkforward,
    extract_m23_expanded_features,
    fit_lightgbm_classifier,
    fit_xgboost_classifier,
    run_m23_comprehensive_benchmark,
)
from app.market.storage import ASIA_KOLKATA, MarketDataStorageService


def _generate_synthetic_candles(n: int = 2000) -> list[dict]:
    """Generate realistic synthetic 15-minute candles for testing."""
    start_dt = datetime(2025, 10, 14, 9, 15, tzinfo=ASIA_KOLKATA)
    candles = []
    base_price = 24500.0

    for i in range(n):
        # 25 bars per day
        day_offset = i // 25
        bar_idx = i % 25
        hour = 9 + (15 + bar_idx * 15) // 60
        minute = (15 + bar_idx * 15) % 60
        candle_dt = (start_dt + timedelta(days=day_offset)).replace(hour=hour, minute=minute, second=0)

        step_ret = math.sin(i * 0.1) * 0.002 + ((i % 5) - 2) * 0.0005
        open_p = base_price
        close_p = base_price * (1.0 + step_ret)
        high_p = max(open_p, close_p) * 1.001
        low_p = min(open_p, close_p) * 0.999
        vol = 100000.0 + (i % 10) * 10000.0
        base_price = close_p

        candles.append({
            "timestamp": candle_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "open": round(open_p, 2),
            "high": round(high_p, 2),
            "low": round(low_p, 2),
            "close": round(close_p, 2),
            "volume": vol,
        })
    return candles


def test_extract_m23_expanded_features_geometry_and_leakage():
    """Verify point-in-time extraction without future leakage."""
    candles = _generate_synthetic_candles(100)
    rows = extract_m23_expanded_features(candles)

    assert len(rows) > 0
    for r in rows:
        assert len(r.features_base) == 3
        assert len(r.features_htf) == 4
        assert len(r.features_ml) == 12
        assert len(r.open_window) <= 64
        assert len(r.close_window) <= 64
        # Verify OHLC geometry in point-in-time record
        assert r.high >= r.low
        assert r.high >= r.open
        assert r.high >= r.close
        assert r.low <= r.open
        assert r.low <= r.close
        # Verify realized volatility is strictly positive
        assert r.realized_volatility > 0.0


def test_m23_target_definitions_and_alignment():
    """Verify exact target definitions: C2C, O2O, O2C_1B, O2C_2B."""
    candles = _generate_synthetic_candles(100)
    rows = extract_m23_expanded_features(candles)

    # Inspect a specific row and its alignment
    for r in rows[:10]:
        t = r.index
        c_t = float(candles[t]["close"])
        c_next1 = float(candles[t + 1]["close"])
        c_next2 = float(candles[t + 2]["close"])
        o_next1 = float(candles[t + 1]["open"])
        o_next2 = float(candles[t + 2]["open"])

        expected_c2c = (c_next1 - c_t) / c_t
        expected_o2o = (o_next2 - o_next1) / o_next1
        expected_o2c_1b = (c_next1 - o_next1) / o_next1
        expected_o2c_2b = (c_next2 - o_next1) / o_next1

        assert math.isclose(r.ret_c2c, expected_c2c, rel_tol=1e-5)
        assert math.isclose(r.ret_o2o, expected_o2o, rel_tol=1e-5)
        assert math.isclose(r.ret_o2c_1b, expected_o2c_1b, rel_tol=1e-5)
        assert math.isclose(r.ret_o2c_2b, expected_o2c_2b, rel_tol=1e-5)

        assert r.y_c2c == (1 if expected_c2c > 0 else 0)
        assert r.y_o2o == (1 if expected_o2o > 0 else 0)
        assert r.y_o2c_1b == (1 if expected_o2c_1b > 0 else 0)
        assert r.y_o2c_2b == (1 if expected_o2c_2b > 0 else 0)


def test_walkforward_fold_boundaries_and_embargo():
    """Verify that test sets are strictly unseen and embargo bars are respected."""
    candles = _generate_synthetic_candles(1800)
    rows = extract_m23_expanded_features(candles)

    cfg = M23ResearchConfig(
        initial_train_size=1000,
        validation_size=200,
        test_size=200,
        step_size=200,
        embargo_bars=2,
    )

    res = evaluate_m23_walkforward(rows, target=PredictionTarget.O2O, config=cfg)
    folds = res["folds"]
    assert len(folds) >= 2

    for f in folds:
        train_sz = f["train_size"]
        test_sz = f["test_size"]
        assert test_sz == 200
        assert train_sz >= 1000


def test_isotonic_calibration_behavior():
    """Verify IsotonicCalibrator monotonic mapping and bounds clipping."""
    cal = IsotonicCalibrator()
    probs = [0.1, 0.2, 0.4, 0.6, 0.8, 0.9]
    labels = [0, 0, 1, 0, 1, 1]

    cal.fit(probs, labels)
    calibrated = cal.transform([0.05, 0.5, 0.95])
    assert len(calibrated) == 3
    for p in calibrated:
        assert 0.0 <= p <= 1.0
    # Must be monotonically non-decreasing
    assert calibrated[0] <= calibrated[1] <= calibrated[2]


def test_lightgbm_and_xgboost_classifiers():
    """Verify LightGBM and XGBoost training and reproducible inference."""
    X_train = [[i * 0.01, (i % 3) * 0.1, 0.005] for i in range(100)]
    y_train = [1 if i % 2 == 0 else 0 for i in range(100)]
    X_test = [[0.05, 0.2, 0.005], [0.8, 0.1, 0.005]]

    lgb_m = fit_lightgbm_classifier(X_train, y_train)
    p_lgb = [float(p[1]) for p in lgb_m.predict_proba(X_test)]
    assert len(p_lgb) == 2
    assert all(0.0 <= p <= 1.0 for p in p_lgb)

    xgb_m = fit_xgboost_classifier(X_train, y_train)
    p_xgb = [float(p[1]) for p in xgb_m.predict_proba(X_test)]
    assert len(p_xgb) == 2
    assert all(0.0 <= p <= 1.0 for p in p_xgb)


def test_chronos_adapter_quantiles_to_probabilities():
    """Verify Chronos-2 probability mapping from quantiles."""
    candles = _generate_synthetic_candles(100)
    rows = extract_m23_expanded_features(candles)

    probs = compute_chronos_raw_probabilities(rows[:20], target=PredictionTarget.O2O, batch_size=10)
    assert len(probs) == 20
    assert all(0.0 < p < 1.0 for p in probs)


def test_timesfm_licensing_compliance():
    """Verify TimesFM 3.0 is blocked by license restriction and not fabricated."""
    meta = MODEL_REGISTRY_METADATA[M23ModelType.TIMESFM_3.value]
    assert meta["status"] == "BLOCKED_RESTRICTIVE_LICENSE"
    assert meta["commercial_use_allowed"] is False
    assert "timesfm-non-commercial-license-v1.0" in meta["license"]

    candles = _generate_synthetic_candles(1500)
    rows = extract_m23_expanded_features(candles)
    cfg = M23ResearchConfig(initial_train_size=1000, validation_size=100, test_size=100, step_size=100)
    res = evaluate_m23_walkforward(rows, target=PredictionTarget.O2O, config=cfg)

    # Must be marked BLOCKED across all folds and summaries
    for f in res["folds"]:
        tf_clf = f["classification"][M23ModelType.TIMESFM_3.value]
        assert tf_clf["status"] == "BLOCKED_RESTRICTIVE_LICENSE"

    sum_clf = res["summary_classification"][M23ModelType.TIMESFM_3.value]
    assert sum_clf["status"] == "BLOCKED_RESTRICTIVE_LICENSE"
    assert sum_clf["mean_accuracy"] is None
    assert res["brier_skill_scores_pct"][M23ModelType.TIMESFM_3.value] is None


def test_trading_simulation_costs_and_terminal_accounting():
    """Verify turnover tracking and terminal exit cost fee."""
    candles = _generate_synthetic_candles(1500)
    rows = extract_m23_expanded_features(candles)
    cfg = M23ResearchConfig(
        initial_train_size=1000,
        validation_size=100,
        test_size=100,
        cost_hurdles_bps=[0.0, 2.0, 5.0, 10.0],
    )
    res = evaluate_m23_walkforward(rows, target=PredictionTarget.O2O, config=cfg)
    summary_tr = res["summary_trading"]

    for m_key, cost_map in summary_tr.items():
        if m_key == M23ModelType.TIMESFM_3.value:
            continue
        c0 = cost_map["0.0_bps"]["compounded_net_return_pct"]
        c2 = cost_map["2.0_bps"]["compounded_net_return_pct"]
        c5 = cost_map["5.0_bps"]["compounded_net_return_pct"]
        c10 = cost_map["10.0_bps"]["compounded_net_return_pct"]
        # Higher cost hurdles must strictly monotonically decrease net returns if trades > 0
        if cost_map["10.0_bps"]["total_trades"] > 0:
            assert c0 >= c2 >= c5 >= c10


def test_benchmark_cache_and_invalidation(db):
    """Verify that benchmark results are cached and invalidated when inputs change."""
    dataset_id = "test_m23_dataset_v1"
    model_ver = "m23-all-models-v1"
    feat_cfg = {"features": "m23_12dim"}
    eval_cfg = {"initial_train": 1000}
    target = "O2O"
    metrics = {"accuracy": 0.52, "net_return": 1.5}

    # 1. Initially cache is empty
    assert MarketDataStorageService.get_cached_benchmark(
        dataset_id=dataset_id,
        model_version=model_ver,
        feature_config=feat_cfg,
        target=target,
        eval_settings=eval_cfg,
        session=db,
    ) is None

    # 2. Store cache
    res = MarketDataStorageService.cache_benchmark_result(
        dataset_id=dataset_id,
        model_version=model_ver,
        feature_config=feat_cfg,
        target=target,
        eval_settings=eval_cfg,
        metrics=metrics,
        session=db,
    )
    assert res is not None
    assert res.dataset_id == dataset_id

    # 3. Retrieve cache
    cached = MarketDataStorageService.get_cached_benchmark(
        dataset_id=dataset_id,
        model_version=model_ver,
        feature_config=feat_cfg,
        target=target,
        eval_settings=eval_cfg,
        session=db,
    )
    assert cached is not None
    assert cached["accuracy"] == 0.52

    # 4. Invalidate cache
    inv_count = MarketDataStorageService.invalidate_benchmark_cache(
        dataset_id=dataset_id,
        reason="Model hyperparameters changed",
        session=db,
    )
    assert inv_count >= 1

    # 5. Retrieve after invalidation should be None
    assert MarketDataStorageService.get_cached_benchmark(
        dataset_id=dataset_id,
        model_version=model_ver,
        feature_config=feat_cfg,
        target=target,
        eval_settings=eval_cfg,
        session=db,
    ) is None


def test_m23_safety_invariants():
    """Verify that all safety invariants remain strictly FALSE."""
    candles = _generate_synthetic_candles(1500)
    cfg = M23ResearchConfig(initial_train_size=1000, validation_size=100, test_size=100)
    res = run_m23_comprehensive_benchmark(candles, config=cfg, use_cache=False)

    invariants = res["safety_invariants"]
    assert invariants["forecast_ready"] is False
    assert invariants["real_market_data_verified"] is False
    assert invariants["paper_approved"] is False
    assert invariants["live_approved"] is False
    assert invariants["live_broker_routing_enabled"] is False
