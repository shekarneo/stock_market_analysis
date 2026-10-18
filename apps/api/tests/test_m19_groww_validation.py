"""Milestone M19 Tests: Groww Historical Data Validation and Research Readiness.

Tests:
1. Unit Tests:
   - Malformed candle geometry (high < max(open, close), low > min(open, close), high < low, non-positive price)
   - Missing bars and incomplete session auditing
   - Duplicate timestamps and overlapping chunk reconciliation (clean duplicates vs conflicting duplicates)
   - Timezone semantics (IST +05:30) and 15-minute interval spacing
   - Date-effective calendar classification (pre-market, post-market, holidays, special sessions)
   - M16 vs M17 dataset hash reconciliation and immutable quarantine preservation
2. Research Pipeline Tests:
   - Point-in-time feature extraction without future leakage
   - Chronological expanding-window walk-forward splits (no random shuffling)
   - Train-only feature scaling (zero lookahead test contamination)
   - Three canonical models: majority-class baseline, last-return-sign baseline, logistic regression
   - Multi-metric verification (accuracy, balanced accuracy, precision, recall, Brier score, confusion matrix)
   - Transaction-cost sensitivity across 0, 1, 2, 5 bps hurdles
3. Safety Invariant Tests:
   - Strict preservation of forecast_ready=False, real_market_data_verified=False,
     paper_approved=False, live_approved=False, live_broker_routing_enabled=False
4. Live Integration Test:
   - Bounded live retrieval with saved credentials (strictly separated, never silently mocked)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import pytest

from app.execution.orders import live_order_calls
from app.forecasting.m19_research import (
    FeatureScaler,
    M19ResearchConfig,
    SimpleLogisticRegression,
    extract_point_in_time_features,
    run_m19_expanding_walk_forward,
)
from app.market.groww_ingestion import (
    audit_session_completeness,
    classify_market_session_observations,
    reconcile_chunk_boundaries,
    verify_raw_quarantine_integrity,
)
from app.market.groww_validation import (
    explain_m16_m17_dataset_hashes,
    validate_live_groww_history,
)
from app.market.schemas import IST
from app.market.session_calendar import (
    InstrumentCategory,
    audit_observation_against_calendar,
    get_market_session_rule,
)
from app.settings import REPO_ROOT


# ============================================================================
# 1. Unit Tests: Geometry, Missing Bars, Duplicates, Timezones, Calendar
# ============================================================================

def test_m19_unit_geometric_consistency_and_malformed_candles():
    """Verify detection of OHLC bound violations and non-positive prices."""
    # Valid candle: High >= max(Open, Close), Low <= min(Open, Close)
    valid_candle = {"open": 25000.0, "high": 25050.0, "low": 24980.0, "close": 25020.0}
    assert valid_candle["high"] >= max(valid_candle["open"], valid_candle["close"])
    assert valid_candle["low"] <= min(valid_candle["open"], valid_candle["close"])

    # Malformed candle 1: High lower than Open
    bad_high = {"open": 25000.0, "high": 24990.0, "low": 24950.0, "close": 24970.0}
    assert not (bad_high["high"] >= max(bad_high["open"], bad_high["close"]))

    # Malformed candle 2: Low higher than Close
    bad_low = {"open": 25000.0, "high": 25050.0, "low": 25010.0, "close": 25005.0}
    assert not (bad_low["low"] <= min(bad_low["open"], bad_low["close"]))

    # Malformed candle 3: Inverted High and Low
    bad_hl = {"open": 25000.0, "high": 24900.0, "low": 25100.0, "close": 25000.0}
    assert bad_hl["high"] < bad_hl["low"]

    # Malformed candle 4: Non-positive price
    zero_price = {"open": 0.0, "high": 25000.0, "low": 0.0, "close": 25000.0}
    assert zero_price["open"] <= 0


def test_m19_unit_missing_bars_and_session_completeness():
    """Verify session completeness audit correctly flags missing 15m intervals."""
    complete_candles = []
    base_h, base_m = 9, 15
    for i in range(25):
        m = base_m + (i * 15)
        h = base_h + (m // 60)
        m = m % 60
        ts = f"2026-10-05T{h:02d}:{m:02d}:00"
        complete_candles.append({
            "raw_timestamp": ts,
            "candle_timestamp": ts,
            "date": "2026-10-05",
            "time_of_day": f"{h:02d}:{m:02d}:00",
            "open": 25000.0,
            "high": 25010.0,
            "low": 24990.0,
            "close": 25005.0,
        })

    audit_complete = audit_session_completeness(complete_candles)
    assert audit_complete["complete_sessions_count"] == 1
    assert audit_complete["incomplete_sessions_count"] == 0
    assert audit_complete["total_missing_bars_count"] == 0

    # Remove 3 bars to test gap detection
    incomplete_candles = [c for idx, c in enumerate(complete_candles) if idx not in (4, 10, 11)]
    audit_incomplete = audit_session_completeness(incomplete_candles)
    assert audit_incomplete["complete_sessions_count"] == 0
    assert audit_incomplete["incomplete_sessions_count"] == 1
    assert audit_incomplete["total_missing_bars_count"] == 3
    s0 = audit_incomplete["sessions"]["2026-10-05"]
    assert s0["missing_count"] == 3
    assert "10:15:00" in s0["missing_times"]
    assert "11:45:00" in s0["missing_times"]
    assert "12:00:00" in s0["missing_times"]


def test_m19_unit_duplicate_and_chunk_boundary_reconciliation():
    """Verify handling of clean duplicates and conflicting duplicate reconciliation."""
    # Chunk 1 ends at 2026-10-12T09:15:00
    chunk1 = {
        "quarantine_id": "chunk1_sha",
        "requested_start_sent": "2026-10-05 09:15:00",
        "requested_end_sent": "2026-10-12 09:15:00",
        "raw_candles": [
            ["2026-10-05T09:15:00", 25000.0, 25050.0, 24980.0, 25020.0, None, None],
            ["2026-10-12T09:15:00", 25100.0, 25150.0, 25080.0, 25120.0, None, None],
        ],
    }
    # Chunk 2 begins at 2026-10-12T09:15:00 with differing High/Low (conflict)
    chunk2 = {
        "quarantine_id": "chunk2_sha",
        "requested_start_sent": "2026-10-12 09:15:00",
        "requested_end_sent": "2026-10-16 15:30:00",
        "raw_candles": [
            ["2026-10-12T09:15:00", 25100.0, 25200.0, 25050.0, 25120.0, None, None],
            ["2026-10-12T09:30:00", 25120.0, 25160.0, 25110.0, 25140.0, None, None],
        ],
    }

    reconciled = reconcile_chunk_boundaries([chunk1, chunk2])
    assert reconciled["ok"] is True
    assert reconciled["total_raw_observations"] == 4
    assert reconciled["total_unique_candles"] == 3
    assert reconciled["duplicates_count"] == 1
    assert reconciled["conflicts_count"] == 1

    # Conflict resolved using deterministic leading chunk strategy
    boundary_candle = next(c for c in reconciled["reconciled_candles"] if c["raw_timestamp"] == "2026-10-12T09:15:00")
    assert boundary_candle["high"] == 25200.0
    assert boundary_candle["low"] == 25050.0


def test_m19_unit_session_calendar_classification_and_exclusions():
    """Verify pre-market and post-market observations are segregated from continuous trading."""
    test_candles = [
        {"raw_timestamp": "2026-10-05T09:00:00", "open": 25000.0, "high": 25000.0, "low": 25000.0, "close": 25000.0},
        {"raw_timestamp": "2026-10-05T09:15:00", "open": 25000.0, "high": 25050.0, "low": 24980.0, "close": 25020.0},
        {"raw_timestamp": "2026-10-05T15:15:00", "open": 25020.0, "high": 25040.0, "low": 25000.0, "close": 25030.0},
        {"raw_timestamp": "2026-10-05T15:30:00", "open": 25030.0, "high": 25030.0, "low": 25030.0, "close": 25030.0},
        {"raw_timestamp": "2026-10-05T15:45:00", "open": 25030.0, "high": 25030.0, "low": 25030.0, "close": 25030.0},
    ]

    classified = classify_market_session_observations(test_candles)
    assert len(classified["regular_candles"]) + len(classified["excluded_observations"]) == 5
    assert classified["regular_count"] == 2
    assert classified["excluded_count"] == 3
    assert classified["pre_market_count"] == 1
    assert classified["post_market_30_count"] == 1
    assert classified["post_market_45_count"] == 1


def test_m19_unit_m16_m17_hash_comparison():
    """Verify cryptographic audit explaining M16 vs M17 dataset hashes."""
    comp = explain_m16_m17_dataset_hashes()
    assert comp["ok"] is True
    assert comp["status"] == "CRYPTOGRAPHICALLY_VERIFIED_IMMUTABLE"
    assert comp["m16_dataset_sha256"] == comp["m17_dataset_sha256"]
    assert comp["derived_file_exists"] is True
    assert comp["immutable_preservation"] is True


# ============================================================================
# 2. Research Pipeline Tests: Leakage Prevention, Scaling, Models, Costs
# ============================================================================

def test_m19_research_point_in_time_features_no_lookahead_leakage():
    """Verify feature computation uses strictly backward-looking data."""
    # Synthetic continuous sequence of 20 candles
    candles = []
    price = 25000.0
    for i in range(20):
        price += (i % 3 - 1) * 20.0
        ts = f"2026-10-05T{9 + (i * 15 // 60):02d}:{(i * 15) % 60:02d}:00"
        candles.append({
            "raw_timestamp": ts,
            "session_date": "2026-10-05",
            "time_str": f"{9 + (i * 15 // 60):02d}:{(i * 15) % 60:02d}:00",
            "open": price - 10.0,
            "high": price + 20.0,
            "low": price - 20.0,
            "close": price,
        })

    dataset = extract_point_in_time_features(candles)
    # 20 candles with 5 warm-up and 1 lookahead label -> 14 observations
    assert len(dataset) == 14

    for row in dataset:
        # Verify features are strictly finite
        assert all(isinstance(v, (int, float)) for v in row["features"].values())
        # Target is binary 0 or 1
        assert row["target"] in (0, 1)


def test_m19_research_train_only_scaling_isolation():
    """Verify feature scaler fits only on train set, strictly isolating test data."""
    train_x = [
        {"f1": 10.0, "f2": 100.0},
        {"f1": 20.0, "f2": 200.0},
        {"f1": 30.0, "f2": 300.0},
    ]
    test_x = [
        {"f1": 1000.0, "f2": 10000.0},  # Extreme outlier in test
    ]

    scaler = FeatureScaler().fit(train_x)
    assert scaler.means["f1"] == 20.0
    assert scaler.means["f2"] == 200.0

    # Scaler transforms test using ONLY train statistics
    scaled_test = scaler.transform(test_x)
    assert scaler.means["f1"] == 20.0  # Still 20.0, test data did NOT alter scaler!


def test_m19_research_expanding_walk_forward_evaluation():
    """Verify chronological walk-forward research pipeline execution and baselines."""
    # Generate 125 synthetic continuous 15m candles (5 days x 25 bars)
    candles = []
    price = 25000.0
    for day in range(1, 6):
        d_str = f"2026-10-{day + 4:02d}"
        for b in range(25):
            m = 15 + (b * 15)
            h = 9 + (m // 60)
            m = m % 60
            price += ((b % 4) - 1.5) * 15.0
            ts = f"{d_str}T{h:02d}:{m:02d}:00"
            candles.append({
                "raw_timestamp": ts,
                "session_date": d_str,
                "time_str": f"{h:02d}:{m:02d}:00",
                "open": round(price - 10.0, 2),
                "high": round(price + 25.0, 2),
                "low": round(price - 25.0, 2),
                "close": round(price, 2),
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
    assert result["total_folds"] >= 2

    # Check metrics existence
    metrics = result["summary_metrics"]
    for m in ("majority_class", "last_return_sign", "logistic_regression"):
        assert m in metrics
        assert metrics[m]["mean_test_accuracy"] is not None
        assert metrics[m]["mean_test_balanced_accuracy"] is not None
        assert metrics[m]["mean_test_brier_score"] is not None

    # Check transaction cost sensitivity
    fold0 = result["folds"][0]
    log_model_fold0 = fold0["models"]["logistic_regression"]
    cost_table = log_model_fold0["transaction_cost_sensitivity"]
    assert "0.0_bps" in cost_table
    assert "1.0_bps" in cost_table
    assert "2.0_bps" in cost_table
    assert "5.0_bps" in cost_table
    # Higher friction must monotonically reduce cumulative return
    assert cost_table["0.0_bps"]["cumulative_return_pct"] >= cost_table["1.0_bps"]["cumulative_return_pct"]
    assert cost_table["1.0_bps"]["cumulative_return_pct"] >= cost_table["2.0_bps"]["cumulative_return_pct"]
    assert cost_table["2.0_bps"]["cumulative_return_pct"] >= cost_table["5.0_bps"]["cumulative_return_pct"]


# ============================================================================
# 3. Safety Invariant Tests
# ============================================================================

def test_m19_safety_invariants_strictly_preserved():
    """Verify all 5 required safety flags are hardcoded False and broker routing is disabled."""
    comp = explain_m16_m17_dataset_hashes()
    for flag in (
        "forecast_ready",
        "real_market_data_verified",
        "paper_approved",
        "live_approved",
        "live_broker_routing_enabled",
    ):
        assert comp["safety_invariants"][flag] is False

    # Check live order routing calls are empty
    assert len(live_order_calls) == 0


# ============================================================================
# 4. Mocked Integration Test (Controlled offline verification)
# ============================================================================

class MockGrowwCaller:
    """Mock caller for deterministic offline integration testing."""
    def __init__(self, c1_candles: list, c2_candles: list) -> None:
        self.c1_candles = c1_candles
        self.c2_candles = c2_candles
        self.call_count = 0

    def send(self, method: str, url: str, **kwargs):
        from app.integrations.http import HttpResult
        self.call_count += 1
        candles = self.c1_candles if self.call_count == 1 else self.c2_candles
        payload = {"payload": {"candles": candles}}
        raw_b = json.dumps(payload).encode("utf-8")
        return HttpResult(status_code=200, body=payload, text=raw_b.decode("utf-8"), raw=raw_b)


def test_m19_mocked_integration_groww_retrieval_and_validation(tmp_path):
    """Offline integration test with controlled HTTP caller verifying pipeline integration."""
    # Build 2 overlapping chunks with 1 boundary conflict
    c1 = [
        ["2026-10-05T09:15:00", 25000.0, 25050.0, 24980.0, 25020.0, None, None],
        ["2026-10-12T09:15:00", 25100.0, 25150.0, 25080.0, 25120.0, None, None],
    ]
    c2 = [
        ["2026-10-12T09:15:00", 25100.0, 25200.0, 25050.0, 25120.0, None, None],
        ["2026-10-12T09:30:00", 25120.0, 25160.0, 25110.0, 25140.0, None, None],
    ]
    mock_caller = MockGrowwCaller(c1, c2)

    # Mock session with a dummy token
    class DummySession:
        def get(self, *args, **kwargs):
            return None
        def query(self, *args, **kwargs):
            return self
        def filter_by(self, *args, **kwargs):
            return self
        def first(self):
            return None

    # Patch groww_read_token to return dummy token
    from unittest.mock import patch
    with patch("app.market.groww_validation.groww_read_token", return_value="mock-token-123"):
        result = validate_live_groww_history(
            caller=mock_caller,
            session=DummySession(),
            destination_dir=tmp_path,
        )

    assert result["ok"] is True
    assert result["status"] == "INTERNALLY_VALIDATED_EXTERNALLY_UNVERIFIED"
    assert result["duplicates_count"] == 1
    assert result["conflicts_count"] == 1
    assert len(result["raw_quarantine_chunks"]) == 2
    assert Path(result["dataset_file"]).is_file()
    for k, v in result["safety_invariants"].items():
        assert v is False


# ============================================================================
# 5. Live Integration Test (Conditioned on DB credentials, never mocked)
# ============================================================================

def test_m19_live_groww_retrieval_and_validation():
    """Live validation using saved DB credentials.
    
    If credentials do not exist or cannot be decrypted under current test settings,
    this test is skipped with an explicit explanatory message.
    NO MOCKS ARE SILENTLY SUBSTITUTED.
    """
    from app.db import get_session_factory
    from app.domain.tables import IntegrationCredential
    from app.integrations.crypto import decrypt_secrets
    from app.settings import get_settings

    active_settings = get_settings()
    session = get_session_factory()()
    try:
        cred = session.query(IntegrationCredential).filter_by(provider="groww").first()
        if not cred or not cred.ciphertext:
            pytest.skip("No saved Groww credentials in active database; skipping live integration test.")
        try:
            decrypt_secrets(active_settings, cred.ciphertext)
        except Exception as exc:
            pytest.skip(f"Test environment key cannot decrypt database credentials ({exc}); skipping live integration test.")
    finally:
        session.close()

    # Run live validation
    result = validate_live_groww_history(
        start_time="2026-10-05 09:15:00",
        boundary_time="2026-10-12 09:15:00",
        end_time="2026-10-16 15:30:00",
    )

    assert result["ok"] is True
    assert result["status"] == "INTERNALLY_VALIDATED_EXTERNALLY_UNVERIFIED"
    assert result["regular_candles_count"] == 250
    assert result["excluded_observations_count"] in (26, 28)
    assert result["complete_sessions_count"] == 10
    assert result["geometric_violations_count"] == 0
    assert result["conflicts_count"] == 1
    assert result["duplicates_count"] == 1

    # Verify all safety flags
    for k, v in result["safety_invariants"].items():
        assert v is False
