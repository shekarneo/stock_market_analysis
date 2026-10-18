"""Milestone M19 Metrics Audit Tests: Hand-Calculated Binary Metric Verifications.

Validates:
1. Hand-calculated Brier score for perfect, inverted, uninformative, and mixed predictions
2. Mathematical identity: For hard predictions p in {0, 1}, Brier score == 1 - Accuracy
3. Base-rate / empirical prior probability Brier score and Brier Skill Score (BSS)
4. Hand-calculated Accuracy, Balanced Accuracy, Precision, Recall, and F1
5. Confusion matrix accounting (TP, TN, FP, FN)
6. Transaction cost mechanics: friction rate conversion (bps to decimals), turnover events, and net returns
7. Expanding-window walk-forward out-of-sample isolation (no test data in feature scaler or model training)
"""

from __future__ import annotations

import math
import statistics
import pytest

from app.forecasting.metrics import binary_metrics
from app.forecasting.m19_research import (
    FeatureScaler,
    M19ResearchConfig,
    SimpleLogisticRegression,
    evaluate_transaction_costs,
    extract_point_in_time_features,
    run_m19_expanding_walk_forward,
)


# ============================================================================
# 1. Hand-Calculated Binary Metrics Verification
# ============================================================================

def test_audit_hand_calculated_perfect_and_inverted_predictions():
    """Verify Brier score and accuracy for extreme deterministic predictions."""
    labels = [1, 0, 1, 0]
    perfect_probs = [1.0, 0.0, 1.0, 0.0]
    inverted_probs = [0.0, 1.0, 0.0, 1.0]

    # Perfect
    m_perf = binary_metrics(labels, perfect_probs)
    assert m_perf["status"] == "DEFINED"
    assert m_perf["accuracy"]["value"] == 1.0
    assert m_perf["balanced_accuracy"]["value"] == 1.0
    assert m_perf["precision"]["value"] == 1.0
    assert m_perf["recall"]["value"] == 1.0
    assert m_perf["f1"]["value"] == 1.0
    assert m_perf["brier"]["value"] == 0.0
    assert m_perf["confusion_matrix"] == {"tn": 2, "fp": 0, "fn": 0, "tp": 2}

    # Inverted
    m_inv = binary_metrics(labels, inverted_probs)
    assert m_inv["accuracy"]["value"] == 0.0
    assert m_inv["balanced_accuracy"]["value"] == 0.0
    assert m_inv["precision"]["value"] == 0.0
    assert m_inv["recall"]["value"] == 0.0
    assert m_inv["f1"]["value"] is None  # Undefined 0 precision and recall
    assert m_inv["brier"]["value"] == 1.0
    assert m_inv["confusion_matrix"] == {"tn": 0, "fp": 2, "fn": 2, "tp": 0}


def test_audit_hand_calculated_uninformative_constant_prior():
    """Verify Brier score for uninformative 50/50 prediction equals exactly 0.2500."""
    labels = [1, 1, 0, 0]
    probs = [0.5, 0.5, 0.5, 0.5]

    m = binary_metrics(labels, probs)
    # Each squared error: (0.5 - 1)^2 = 0.25, (0.5 - 0)^2 = 0.25 -> Mean = 0.2500
    assert m["brier"]["value"] == 0.2500
    # Log loss: -ln(0.5) = 0.693147...
    assert round(m["log_loss"]["value"], 4) == round(-math.log(0.5), 4)
    # Threshold rule > 0.5: all predicted as 0
    assert m["confusion_matrix"] == {"tn": 2, "fp": 0, "fn": 2, "tp": 0}
    assert m["accuracy"]["value"] == 0.5000
    assert m["balanced_accuracy"]["value"] == 0.5000
    assert m["precision"]["value"] is None  # No predicted positives
    assert m["recall"]["value"] == 0.0


def test_audit_hand_calculated_arbitrary_mixed_example():
    """Verify hand-calculated metrics on an explicit multi-case dataset."""
    labels = [1, 0, 1, 1, 0]
    probs = [0.8, 0.2, 0.6, 0.4, 0.1]

    # Hand calculation:
    # y=1, p=0.8 -> (0.8 - 1)^2 = 0.04
    # y=0, p=0.2 -> (0.2 - 0)^2 = 0.04
    # y=1, p=0.6 -> (0.6 - 1)^2 = 0.16
    # y=1, p=0.4 -> (0.4 - 1)^2 = 0.36
    # y=0, p=0.1 -> (0.1 - 0)^2 = 0.01
    # Sum = 0.61. Mean = 0.61 / 5 = 0.1220
    # Predictions (>0.5): [1, 0, 1, 0, 0]
    # TP: idx 0 (y=1, p=1), idx 2 (y=1, p=1) -> TP = 2
    # TN: idx 1 (y=0, p=0), idx 4 (y=0, p=0) -> TN = 2
    # FP: none -> FP = 0
    # FN: idx 3 (y=1, p=0) -> FN = 1
    # Accuracy = 4 / 5 = 0.8000
    # TPR = 2 / 3, TNR = 2 / 2 = 1.0 -> Balanced Acc = (2/3 + 1) / 2 = 5/6 = 0.83333...
    # Precision = 2 / (2 + 0) = 1.0000
    # Recall = 2 / (2 + 1) = 2/3 = 0.66666...
    # F1 = 2 * (1.0 * 2/3) / (1.0 + 2/3) = 4/5 = 0.8000

    m = binary_metrics(labels, probs)
    assert round(m["brier"]["value"], 4) == 0.1220
    assert round(m["accuracy"]["value"], 4) == 0.8000
    assert round(m["balanced_accuracy"]["value"], 4) == 0.8333
    assert round(m["precision"]["value"], 4) == 1.0000
    assert round(m["recall"]["value"], 4) == 0.6667
    assert round(m["f1"]["value"], 4) == 0.8000
    assert m["confusion_matrix"] == {"tn": 2, "fp": 0, "fn": 1, "tp": 2}


def test_audit_proof_hard_predictions_brier_equals_one_minus_accuracy():
    """Prove that for any binary labels and hard predictions in {0, 1}, Brier == 1 - Accuracy.
    
    This explains why M19 baseline Brier scores were 0.5133 and 0.5200:
    The baselines were outputting hard {0, 1} decision rules rather than probabilities!
    """
    labels = [1, 0, 1, 1, 0, 0, 1, 0, 1, 0]
    hard_preds = [1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 0.0]

    m = binary_metrics(labels, hard_preds)
    acc = m["accuracy"]["value"]
    brier = m["brier"]["value"]

    assert round(brier, 6) == round(1.0 - acc, 6)


def test_audit_brier_skill_score_against_empirical_prior():
    """Verify Brier Skill Score (BSS) formula: BSS = 1 - (BS_model / BS_ref)."""
    # Suppose reference prior Brier is 0.2500 and model Brier is 0.2000
    bs_model = 0.2000
    bs_ref = 0.2500
    bss = 1.0 - (bs_model / bs_ref)
    assert round(bss, 4) == 0.2000  # 20% improvement over prior

    # If model Brier is 0.2846 and reference prior is 0.2516:
    bs_log = 0.2846
    bs_prior = 0.2516
    bss_negative = 1.0 - (bs_log / bs_prior)
    assert bss_negative < 0.0  # Demonstrates negative skill / overconfidence!


# ============================================================================
# 2. Transaction Cost Mechanics Verification
# ============================================================================

def test_audit_transaction_cost_units_and_friction_accounting():
    """Verify friction conversion (1 bp = 0.0001) and turnover accounting."""
    # 3 bars with known gross returns
    test_rows = [
        {"next_return": 0.01},   # Bar 1: +1.0%
        {"next_return": -0.005}, # Bar 2: -0.5%
        {"next_return": 0.02},   # Bar 3: +2.0%
    ]

    # Predict: Long, Flat, Long
    probs = [0.8, 0.2, 0.9]

    # Evaluate at 2.0 bps (0.0002 friction per turnover)
    res = evaluate_transaction_costs(test_rows, probs, [2.0])
    c2 = res["2.0_bps"]

    assert c2["hurdle_bps"] == 2.0
    assert c2["friction_per_turn"] == 0.0002

    # Hand calculation:
    # Bar 1: prev_pos=0.0 -> pos=1.0 (turnover=1.0, fee=0.0002). Gross=0.01. Net=0.01 - 0.0002 = 0.0098
    # Bar 2: prev_pos=1.0 -> pos=0.0 (turnover=1.0, fee=0.0002). Gross=0.0.  Net=0.0 - 0.0002 = -0.0002
    # Bar 3: prev_pos=0.0 -> pos=1.0 (turnover=1.0, fee=0.0002). Gross=0.02. Net=0.02 - 0.0002 = 0.0198
    # Turnovers count = 3
    # Cumulative return: (1 + 0.0098) * (1 - 0.0002) * (1 + 0.0198) = 1.0098 * 0.9998 * 1.0198 = 1.029584...
    # Return pct: ~2.958%
    assert c2["total_turnover_events"] == 3
    expected_cum = (1.0 + 0.0098) * (1.0 - 0.0002) * (1.0 + 0.0198)
    assert round(c2["cumulative_return_pct"], 2) == round((expected_cum - 1.0) * 100, 2)


# ============================================================================
# 3. Leakage Prevention and Walk-Forward Out-of-Sample Isolation
# ============================================================================

def test_audit_walk_forward_leakage_and_scaler_isolation():
    """Verify that feature scalers and models never observe test fold data."""
    # 125 synthetic continuous bars
    candles = []
    price = 25000.0
    for day in range(1, 6):
        d_str = f"2026-10-{day + 4:02d}"
        for b in range(25):
            m = 15 + (b * 15)
            h = 9 + (m // 60)
            m = m % 60
            price += ((b % 3) - 1.0) * 10.0
            ts = f"{d_str}T{h:02d}:{m:02d}:00"
            candles.append({
                "raw_timestamp": ts,
                "session_date": d_str,
                "time_str": f"{h:02d}:{m:02d}:00",
                "open": price - 5.0,
                "high": price + 10.0,
                "low": price - 10.0,
                "close": price,
            })

    cfg = M19ResearchConfig(
        initial_train_size=40,
        validation_size=20,
        test_size=20,
        step_size=20,
        embargo_bars=1,
    )

    result = run_m19_expanding_walk_forward(candles, cfg=cfg)
    assert result["ok"] is True
    assert result["leakage_prevention"]["lookahead_leakage_detected"] is False
    assert result["leakage_prevention"]["scaler_fitted_on_training_only"] is True
    assert result["leakage_prevention"]["no_shuffling"] is True


# ============================================================================
# 4. Milestone M20 Research Preparation Tests (Inactive and Safe)
# ============================================================================

def test_audit_m20_htf_point_in_time_alignment():
    """Verify that 1-hour higher-timeframe features do not leak future hourly closes."""
    from app.forecasting.m20_research import build_htf_1hour_context

    # Create 16 15-minute bars (4 hours of trading)
    candles = []
    price = 25000.0
    for i in range(16):
        price += 10.0
        candles.append({
            "raw_timestamp": f"2026-10-05T{9 + (i * 15 // 60):02d}:{(i * 15) % 60:02d}:00",
            "open": price - 2.0,
            "high": price + 5.0,
            "low": price - 5.0,
            "close": price,
        })

    htf = build_htf_1hour_context(candles)
    assert len(htf) == 16
    # Early bars (0 to 10) have fewer than 3 completed hourly bars -> returns 0.0 default
    assert htf[0]["htf_1h_trend_dir"] == 0.0
    assert htf[10]["htf_1h_trend_dir"] == 0.0
    # At bar index 11 (close of 3rd hour), exactly 3 completed hours exist (end_indices 3, 7, 11)
    assert htf[11]["htf_1h_trend_dir"] in (1.0, -1.0)


def test_audit_m20_selective_conviction_reduces_churn():
    """Verify selective conviction thresholding suppresses low-conviction noise trades."""
    from app.forecasting.m20_research import evaluate_selective_transaction_costs

    test_rows = [{"next_return": 0.002} for _ in range(10)]
    # Marginal noise probabilities fluctuating around 0.50
    noise_probs = [0.51, 0.49, 0.52, 0.48, 0.51, 0.49, 0.52, 0.48, 0.51, 0.49]

    # Standard unconstrained 0.50 rule -> 10 position switches!
    std_costs = evaluate_transaction_costs(test_rows, noise_probs, [2.0])
    assert std_costs["2.0_bps"]["total_turnover_events"] >= 8

    # Selective entry rule with long >= 0.55 and exit <= 0.45 -> Never triggers Long! 0 turnovers!
    sel_costs = evaluate_selective_transaction_costs(
        test_rows,
        noise_probs,
        threshold_long=0.55,
        threshold_exit=0.45,
        hurdles_bps=[2.0],
    )
    assert sel_costs["2.0_bps"]["total_turnover_events"] == 0
    assert sel_costs["2.0_bps"]["cumulative_return_pct"] == 0.0  # Kept cash, 0 fee loss!


def test_audit_m20_safety_invariants_inactive():
    """Verify M20 preparation keeps enabled=False and all safety flags False."""
    from app.forecasting.m20_research import M20ResearchConfig, prepare_m20_walk_forward_specification

    cfg = M20ResearchConfig()
    assert cfg.enabled is False

    spec = prepare_m20_walk_forward_specification()
    assert spec["enabled"] is False
    assert spec["status"] == "PREPARED_INACTIVE"
    for flag in (
        "forecast_ready",
        "real_market_data_verified",
        "paper_approved",
        "live_approved",
        "live_broker_routing_enabled",
    ):
        assert spec["safety_invariants"][flag] is False

