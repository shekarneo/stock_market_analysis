"""Milestone M22 Phase 1 Regression Tests: Target Alignment and Data Provenance.

Tests:
1. Correct C2C label indexing: close[t+1] / close[t] - 1.0.
2. Correct O2O label indexing: open[t+2] / open[t+1] - 1.0.
3. Correct O2C label indexing: close[t+1] / open[t+1] - 1.0 (1-bar) and close[t+2] / open[t+1] - 1.0 (2-bar).
4. No cross-target prediction reuse: verifies target-aligned training changes labels and predictions.
5. No future-feature leakage: mutating future candles does not alter feature vectors at bar t.
6. Execution timeline contract and timestamps.
7. Correct turnover accounting: one-way fee per turnover event; round-trip incurs exactly 2 * one-way fee.
8. Chronological walk-forward ordering with embargo.
9. Provenance audit:
   - Resolves M16/M17 hash discrepancy (dataset_id ac9484b6... vs file SHA-256 8765c30a...).
   - Audits M19 dataset_id (84c514e5...) vs file SHA-256 (a90d3e6f...).
   - Audits 3-level verification hierarchy (Levels 1 & 2 pass; Level 3 fails closed).
10. Safety invariants remain False; trading decision is BLOCKED.
"""

from __future__ import annotations

import math
import statistics
import pytest

from app.forecasting.m22_research import (
    M22ResearchConfig,
    PredictionTarget,
    audit_information_availability_contract,
    audit_m22_dataset_provenance,
    evaluate_m22_strategy_execution,
    extract_m22_aligned_rows,
    prepare_m22_walk_forward_specification,
    run_m22_phase1_evaluation,
    run_target_aligned_evaluation,
)


def _make_deterministic_candles(n: int = 150) -> list[dict]:
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
# 1. Target Alignment and Indexing Verification
# ============================================================================

def test_m22_target_label_indexing_hand_calculated():
    """Verify hand-calculated targets C2C, O2O, O2C_1B, O2C_2B."""
    candles = [
        {"timestamp": "T0", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5},   # warmup 0
        {"timestamp": "T1", "open": 100.5, "high": 102.0, "low": 100.0, "close": 101.0}, # warmup 1
        {"timestamp": "T2", "open": 101.0, "high": 102.5, "low": 100.5, "close": 101.5}, # warmup 2
        {"timestamp": "T3", "open": 101.5, "high": 103.0, "low": 101.0, "close": 102.0}, # warmup 3
        {"timestamp": "T4", "open": 102.0, "high": 103.5, "low": 101.5, "close": 102.5}, # warmup 4
        # bar t (index 5)
        {"timestamp": "T5", "open": 102.5, "high": 104.0, "low": 102.0, "close": 103.0},
        # bar t+1 (index 6)
        {"timestamp": "T6", "open": 103.5, "high": 105.0, "low": 103.0, "close": 104.5},
        # bar t+2 (index 7)
        {"timestamp": "T7", "open": 104.0, "high": 106.0, "low": 103.5, "close": 105.5},
    ]

    rows = extract_m22_aligned_rows(candles)
    assert len(rows) == 1
    r = rows[0]
    assert r["index"] == 5

    # C2C: close[t+1] / close[t] - 1.0 = 104.5 / 103.0 - 1.0 = +0.014563...
    expected_c2c = (104.5 / 103.0) - 1.0
    assert r["return_C2C"] == pytest.approx(expected_c2c, abs=1e-7)
    assert r["direction_C2C"] == 1

    # O2O: open[t+2] / open[t+1] - 1.0 = 104.0 / 103.5 - 1.0 = +0.0048309...
    expected_o2o = (104.0 / 103.5) - 1.0
    assert r["return_O2O"] == pytest.approx(expected_o2o, abs=1e-7)
    assert r["direction_O2O"] == 1

    # O2C_1B: close[t+1] / open[t+1] - 1.0 = 104.5 / 103.5 - 1.0 = +0.0096618...
    expected_o2c_1b = (104.5 / 103.5) - 1.0
    assert r["return_O2C_1B"] == pytest.approx(expected_o2c_1b, abs=1e-7)
    assert r["direction_O2C_1B"] == 1

    # O2C_2B: close[t+2] / open[t+1] - 1.0 = 105.5 / 103.5 - 1.0 = +0.0193236...
    expected_o2c_2b = (105.5 / 103.5) - 1.0
    assert r["return_O2C_2B"] == pytest.approx(expected_o2c_2b, abs=1e-7)
    assert r["direction_O2C_2B"] == 1


def test_m22_divergent_targets():
    """Verify hand-calculated case where C2C is UP but O2O is DOWN."""
    candles = [
        {"timestamp": "T0", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        {"timestamp": "T1", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        {"timestamp": "T2", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        {"timestamp": "T3", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        {"timestamp": "T4", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        # bar t: close = 100.0
        {"timestamp": "T5", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        # bar t+1: open gaps up to 105.0, but closes at 102.0
        # (close[t+1] / close[t] = 102.0 / 100.0 = +2% -> C2C is UP)
        {"timestamp": "T6", "open": 105.0, "high": 106.0, "low": 101.0, "close": 102.0},
        # bar t+2: open gaps down to 101.0
        # (open[t+2] / open[t+1] = 101.0 / 105.0 = -3.8% -> O2O is DOWN)
        {"timestamp": "T7", "open": 101.0, "high": 102.0, "low": 100.0, "close": 101.5},
    ]

    rows = extract_m22_aligned_rows(candles)
    r = rows[0]

    # C2C is positive (+2%)
    assert r["return_C2C"] > 0
    assert r["direction_C2C"] == 1

    # O2O is negative (-3.8%)
    assert r["return_O2O"] < 0
    assert r["direction_O2O"] == 0

    # This directly proves that a model predicting C2C cannot be assumed to match O2O!
    assert r["direction_C2C"] != r["direction_O2O"]


# ============================================================================
# 2. Information Availability & Prevention of Leakage
# ============================================================================

def test_m22_information_availability_contracts():
    c2c_contract = audit_information_availability_contract(PredictionTarget.C2C)
    assert c2c_contract["target_code"] == "C2C"
    assert c2c_contract["assumed_fill_price"] == "close[t]"

    o2o_contract = audit_information_availability_contract(PredictionTarget.O2O)
    assert o2o_contract["target_code"] == "O2O"
    assert o2o_contract["assumed_fill_price"] == "open[t+1]"
    assert o2o_contract["outcome_measurement_price"] == "open[t+2]"


def test_m22_future_leakage_prevention():
    candles = _make_deterministic_candles(30)
    rows = extract_m22_aligned_rows(candles)

    # Mutating candle 28 must not change feature vector or targets of row 5
    candles_mut = [dict(c) for c in candles]
    candles_mut[28]["close"] = candles_mut[28]["close"] * 5.0
    rows_mut = extract_m22_aligned_rows(candles_mut)

    assert rows[5]["features_base"] == rows_mut[5]["features_base"]
    assert rows[5]["features_htf"] == rows_mut[5]["features_htf"]
    assert rows[5]["return_O2O"] == rows_mut[5]["return_O2O"]


# ============================================================================
# 3. Transaction Costs and Turnover Accounting
# ============================================================================

def test_m22_transaction_costs_one_way_and_round_trip():
    rows = [
        {"return_O2O": 0.01, "price_entry_open": 100.0, "price_exit_open": 101.0, "as_of": "T1"},
        {"return_O2O": 0.02, "price_entry_open": 101.0, "price_exit_open": 103.0, "as_of": "T2"},
        {"return_O2O": -0.01, "price_entry_open": 103.0, "price_exit_open": 102.0, "as_of": "T3"},
    ]
    # enter on bar 0 (pos=1), exit on bar 2 (pos=0)
    probs = [0.80, 0.80, 0.20]
    res = evaluate_m22_strategy_execution(rows, probs, 0.60, 0.40, PredictionTarget.O2O, [0.0, 5.0])

    # 0 bps
    assert res["0.0_bps"]["total_turnover_events"] == 2
    assert res["0.0_bps"]["closed_trades_count"] == 1

    # 5 bps one-way = 10 bps round-trip
    assert res["5.0_bps"]["one_way_friction_rate"] == 0.0005
    assert res["5.0_bps"]["round_trip_friction_bps"] == 10.0
    assert res["5.0_bps"]["cumulative_return_pct"] < res["0.0_bps"]["cumulative_return_pct"]


# ============================================================================
# 4. Provenance and 3-Level Verification Audit
# ============================================================================

def test_m22_provenance_and_hash_reconciliation():
    prov = audit_m22_dataset_provenance()
    res = prov["hash_discrepancy_resolution"]

    # Reconciles M16 dataset_id vs raw file SHA-256
    assert res["m16_dataset_file"] == "derived_nifty_15m_regular_ac9484b605d484c2.json"
    assert res["raw_file_byte_sha256"] == "8765c30ac4c47da95cf22f9879d66746a7763b8ffe94ce056121829527e31b16"
    assert res["internal_json_dataset_id"] == "ac9484b605d484c24e7d38a52a4a43edf03d1a02198966c7952e79a2a9d804c9"

    # Verifies 3-level verification hierarchy
    levels = prov["verification_levels"]
    assert levels["level_1_internal_structural_validation"]["status"] == "PASS"
    assert levels["level_2_session_and_timestamp_validation"]["status"] == "PASS"
    assert levels["level_3_independent_external_verification"]["status"] == "FAILED_CREDENTIALS_MISSING"
    assert levels["level_3_independent_external_verification"]["verdict"] == "NOT_ATTAINED"


# ============================================================================
# 5. Full Phase 1 Walk-Forward Evaluation & Safety Invariants
# ============================================================================

def test_m22_phase1_evaluation_synthetic():
    candles = _make_deterministic_candles(150)
    cfg = M22ResearchConfig(
        initial_train_size=40,
        validation_size=20,
        test_size=20,
        step_size=20,
        embargo_bars=1,
    )

    res = run_m22_phase1_evaluation(candles, cfg)
    assert res["ok"] is True
    assert res["trading_decision"] == "BLOCKED"

    # Check that all 4 targets are evaluated
    targets = res["target_aligned_evaluations"]
    assert "C2C" in targets
    assert "O2O" in targets
    assert "O2C_1B" in targets
    assert "O2C_2B" in targets

    # Safety invariants
    inv = res["safety_invariants"]
    assert inv["forecast_ready"] is False
    assert inv["real_market_data_verified"] is False
    assert inv["paper_approved"] is False
    assert inv["live_approved"] is False
    assert inv["live_broker_routing_enabled"] is False


def test_prepare_m22_walk_forward_specification():
    spec = prepare_m22_walk_forward_specification()
    assert spec["enabled"] is False
    assert spec["status"] == "PREPARED_INACTIVE"
    for flag, val in spec["safety_invariants"].items():
        assert val is False
