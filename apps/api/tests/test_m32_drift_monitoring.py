"""Milestone M32 Test Suite: Observability, Feature Drift Monitoring & Kill Switch Tripping.

Verifies:
1. PSI calculation precision and quantile binning.
2. Sensitivity to moderate vs critical distribution shifts.
3. KS test and Wasserstein distance quantification.
4. Fail-safe circuit breaker tripping OpsState.kill_switch = True in database.
5. Safe behavior when drift is within acceptable bounds.
6. Real NIFTY 1-year benchmark Dev vs Holdout drift audit.
7. Preservation of all 5 financial safety invariants.
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pytest
from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.domain.tables import AuditEvent, OpsState
from app.monitoring.drift_detector import (
    DEFAULT_CRITICAL_PSI_THRESHOLD,
    DEFAULT_WARNING_PSI_THRESHOLD,
    calculate_ks,
    calculate_psi,
    calculate_wasserstein,
    evaluate_and_enforce_drift_circuit_breaker,
    evaluate_feature_matrix_drift,
    run_nifty_benchmark_drift_audit,
)
from app.risk.ledger import read_kill_switch, set_kill_switch
from app.settings import REPO_ROOT


def test_psi_identical_distributions_near_zero():
    """Identical distributions should exhibit negligible PSI (< 0.05) and STABLE status."""
    rng = np.random.default_rng(42)
    sample_a = rng.normal(loc=100.0, scale=15.0, size=2000).tolist()
    sample_b = rng.normal(loc=100.0, scale=15.0, size=2000).tolist()

    psi, bins = calculate_psi(sample_a, sample_b, num_bins=10)
    assert psi < 0.05
    assert len(bins) > 0


def test_psi_moderate_and_critical_distribution_shifts():
    """Shifts of varying magnitudes should properly cross warning and critical thresholds."""
    rng = np.random.default_rng(1337)
    ref = rng.normal(loc=0.0, scale=1.0, size=3000).tolist()

    # Moderate shift (mean shifted by 0.35 std)
    moderate_tgt = rng.normal(loc=0.35, scale=1.0, size=3000).tolist()
    psi_mod, _ = calculate_psi(ref, moderate_tgt, num_bins=10)
    assert 0.08 <= psi_mod < 0.30

    # Severe shift (mean shifted by 1.5 std)
    severe_tgt = rng.normal(loc=1.5, scale=1.5, size=3000).tolist()
    psi_sev, _ = calculate_psi(ref, severe_tgt, num_bins=10)
    assert psi_sev >= DEFAULT_CRITICAL_PSI_THRESHOLD


def test_ks_and_wasserstein_metrics():
    """Verify KS statistic and Wasserstein distance capture distribution distances accurately."""
    rng = np.random.default_rng(999)
    dist1 = rng.normal(loc=50.0, scale=5.0, size=1000).tolist()
    dist2 = rng.normal(loc=50.0, scale=5.0, size=1000).tolist()
    dist3 = rng.normal(loc=65.0, scale=8.0, size=1000).tolist()

    # Identical distributions
    ks_stat_same, pval_same = calculate_ks(dist1, dist2)
    wass_same = calculate_wasserstein(dist1, dist2)
    assert ks_stat_same < 0.10
    assert pval_same > 0.05
    assert wass_same < 1.0

    # Divergent distributions
    ks_stat_diff, pval_diff = calculate_ks(dist1, dist3)
    wass_diff = calculate_wasserstein(dist1, dist3)
    assert ks_stat_diff > 0.70
    assert pval_diff < 1e-10
    assert wass_diff > 10.0


def test_circuit_breaker_trips_kill_switch_on_critical_drift(db):
    """When critical drift is detected, circuit breaker must trip the kill switch in DB."""
    session = get_session_factory()()
    try:
        # Ensure kill switch is initially reset for test
        set_kill_switch(session, enabled=False, actor="test.setup", reason="reset before test")
        assert read_kill_switch(session) is False

        rng = np.random.default_rng(7)
        ref_matrix = {
            "feature_volatility": rng.normal(loc=1.0, scale=0.1, size=1000).tolist(),
            "feature_momentum": rng.normal(loc=0.0, scale=1.0, size=1000).tolist(),
        }
        # Target exhibits severe volatility explosion
        target_matrix = {
            "feature_volatility": rng.normal(loc=3.5, scale=1.5, size=1000).tolist(),
            "feature_momentum": rng.normal(loc=0.0, scale=1.0, size=1000).tolist(),
        }

        report = evaluate_and_enforce_drift_circuit_breaker(
            session,
            ref_matrix,
            target_matrix,
            actor="drift.circuit_breaker",
            critical_psi_threshold=0.25,
            commit=True,
        )

        assert report.overall_status == "CRITICAL_DRIFT"
        assert report.kill_switch_tripped is True
        assert "feature_volatility" in report.critical_features
        assert "CRITICAL_FEATURE_DRIFT" in (report.kill_switch_reason or "")

        # Verify that database row is updated
        ops_row = session.get(OpsState, 1)
        assert ops_row is not None
        assert ops_row.kill_switch is True

        # Verify audit event logged
        audit = (
            session.query(AuditEvent)
            .filter(AuditEvent.action == "risk.kill_switch")
            .order_by(AuditEvent.created_at.desc())
            .first()
        )
        assert audit is not None
        assert audit.after.get("kill_switch") is True
        assert "CRITICAL_FEATURE_DRIFT" in audit.after.get("reason", "")
    finally:
        session.close()


def test_circuit_breaker_safe_under_normal_conditions(db):
    """When drift is minimal, circuit breaker must NOT trip the kill switch."""
    session = get_session_factory()()
    try:
        set_kill_switch(session, enabled=False, actor="test.setup", reason="reset before test")
        assert read_kill_switch(session) is False

        rng = np.random.default_rng(2026)
        ref_matrix = {
            "f1": rng.normal(loc=10.0, scale=2.0, size=1000).tolist(),
            "f2": rng.normal(loc=0.5, scale=0.05, size=1000).tolist(),
        }
        target_matrix = {
            "f1": rng.normal(loc=10.02, scale=2.01, size=1000).tolist(),
            "f2": rng.normal(loc=0.501, scale=0.049, size=1000).tolist(),
        }

        report = evaluate_and_enforce_drift_circuit_breaker(
            session,
            ref_matrix,
            target_matrix,
            actor="drift.circuit_breaker",
            critical_psi_threshold=0.25,
            commit=True,
        )

        assert report.overall_status == "STABLE"
        assert report.kill_switch_tripped is False
        assert len(report.critical_features) == 0
        assert read_kill_switch(session) is False
    finally:
        session.close()


def test_nifty_benchmark_drift_dev_vs_holdout():
    """Run feature drift audit comparing NIFTY Folds 1–14 dev window vs Folds 15–19 holdout."""
    report = run_nifty_benchmark_drift_audit()

    assert report is not None
    assert report.max_psi >= 0.0
    assert "returns" in report.feature_metrics
    assert "atr" in report.feature_metrics
    assert "adx" in report.feature_metrics
    assert "volume" in report.feature_metrics

    # Check persisted JSON artifact
    artifact_path = REPO_ROOT / "var/datasets/m32_drift_benchmark_results.json"
    assert artifact_path.exists()
    with open(artifact_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["max_psi"] == report.max_psi
    assert "feature_metrics" in data


def test_m32_safety_invariants_strictly_false():
    """All 5 financial safety invariants must remain strictly False."""
    report = evaluate_feature_matrix_drift({}, {})
    assert report.forecast_ready is False
    assert report.real_market_data_verified is False
    assert report.paper_approved is False
    assert report.live_approved is False
    assert report.live_broker_routing_enabled is False
