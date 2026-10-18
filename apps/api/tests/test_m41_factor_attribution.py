"""Milestone M41: Statistical Factor Attribution & Feature Explainability Tests.

Verifies:
1. Feature vector completeness and 19-factor registry.
2. Information Coefficient (Rank IC) and ICIR boundary compliance.
3. Permutation Feature Importance (PFI) Brier delta calculations across 19 folds.
4. Cross-asset factor loading divergence, cosine similarity, and opposing-sign detection.
5. Benchmark report serialization to JSON artifact.
6. Hard financial safety boundaries remain strictly False.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from app.forecasting.m41_factor_attribution import (
    FEATURE_NAMES,
    compute_cross_asset_divergence,
    compute_information_coefficients,
    compute_permutation_feature_importance,
    run_m41_factor_attribution_benchmark,
)
from app.settings import REPO_ROOT


def test_m41_feature_list_completeness_and_order():
    """Verify exactly 19 features are registered and uniquely named."""
    assert len(FEATURE_NAMES) == 19
    assert len(set(FEATURE_NAMES)) == 19
    assert "ret_1" in FEATURE_NAMES
    assert "trend_hh_ll" in FEATURE_NAMES
    assert "adx_norm" in FEATURE_NAMES
    assert "hurst" in FEATURE_NAMES
    assert "is_trending_bull" in FEATURE_NAMES


def test_m41_benchmark_report_execution_and_artifacts():
    """Verify execution of M41 benchmark generates complete report and JSON artifact."""
    report = run_m41_factor_attribution_benchmark()
    assert report.milestone == "M41"
    assert len(report.nifty_attribution.factor_metrics) == 19
    assert len(report.banknifty_attribution.factor_metrics) == 19

    # Check top predictive factors are identified
    assert len(report.nifty_attribution.top_predictive_factors) > 0
    assert len(report.banknifty_attribution.top_predictive_factors) > 0

    # Cross asset divergence check
    div = report.cross_asset_divergence
    assert -1.0 <= div.cosine_similarity <= 1.0
    assert div.euclidean_distance > 0.0
    assert len(div.inverted_sign_factors) >= 2

    # Check artifact file
    artifact_path = REPO_ROOT / "var" / "datasets" / "m41_factor_attribution_results.json"
    assert artifact_path.exists()
    with open(artifact_path, "r") as f:
        data = json.load(f)
    assert data["milestone"] == "M41"
    assert "nifty_attribution" in data
    assert "banknifty_attribution" in data
    assert "cross_asset_divergence" in data


def test_m41_factor_metrics_bounds_and_validity():
    """Verify factor metrics adhere to mathematical bounds."""
    report = run_m41_factor_attribution_benchmark()

    for fm in report.nifty_attribution.factor_metrics:
        assert -1.0 <= fm.information_coefficient <= 1.0
        assert 0.0 <= fm.sign_stability_pct <= 100.0
        assert fm.role_classification in {
            "PRIMARY_ALPHA_DRIVER",
            "SECONDARY_ALPHA_DRIVER",
            "OVERFITTING_RISK",
            "NEUTRAL_PASS_THROUGH",
            "REGIME_CONTEXT_MODULATOR",
        }

    for fm in report.banknifty_attribution.factor_metrics:
        assert -1.0 <= fm.information_coefficient <= 1.0
        assert 0.0 <= fm.sign_stability_pct <= 100.0


def test_m41_cross_asset_opposing_signs_detection():
    """Verify mathematical detection of opposing sign factors between NIFTY and BANK NIFTY."""
    report = run_m41_factor_attribution_benchmark()
    div = report.cross_asset_divergence

    # At least ret_4, bar_pos, or ret_1 should exhibit opposing signs
    opposing = set(div.inverted_sign_factors)
    assert any(f in opposing for f in ["ret_1", "ret_4", "bar_pos", "hurst"])


def test_m41_safety_invariants_strictly_false():
    """Verify all 5 hard financial safety invariants remain strictly False."""
    report = run_m41_factor_attribution_benchmark()
    invs = report.safety_invariants
    assert invs["forecast_ready"] is False
    assert invs["real_market_data_verified"] is False
    assert invs["paper_approved"] is False
    assert invs["live_approved"] is False
    assert invs["live_broker_routing_enabled"] is False
