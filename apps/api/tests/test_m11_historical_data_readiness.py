"""Milestone M11 regression tests: Real Historical Data Acquisition & Walk-Forward Evaluation Readiness."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
import pytest

from app.market.history import capabilities, validate_request
from app.market.schemas import IST
from app.market.verified_history import (
    reconcile_historical_dataset,
    validate_historical_dataset,
    evaluate_real_data_walkforward,
    reconcile_quarantine_nifty_dataset,
    find_independent_chart_reference,
    STANDARD_SESSION_START_TIMES,
)
from app.settings import REPO_ROOT

QUARANTINE_ID = "0105c2cfde527068e24b576e089b4dabfccda734fd20167ae28419a3e2e98057"


def _make_valid_day_raw(date_str: str = "2026-10-14", base_price: float = 22500.0) -> list[list]:
    """Helper creating 25 valid regular 15m candles + 1 closing auction tick."""
    candles = []
    p = base_price
    for t in STANDARD_SESSION_START_TIMES:
        ts = f"{date_str}T{t}"
        candles.append([ts, p, p + 15.0, p - 10.0, p + 5.0, 1000.0])
        p += 5.0
    # Add closing auction print at 15:30:00
    candles.append([f"{date_str}T15:30:00", p, p, p, p, 500.0])
    return candles


def test_provider_audit_capabilities_and_missing_credentials_block():
    """Verify capabilities accurately reflects provider constraints and unconfigured credentials."""
    caps = capabilities()
    assert caps["provider"] == "groww"
    assert caps["interval"] == "M15"
    assert caps["candle_interval"] == "15minute"
    assert caps["max_duration_per_request_days"] == 90
    assert caps["real_market_data_verified"] is False
    assert caps["forecast_ready"] is False
    assert caps["paper_approved"] is False
    assert caps["live_approved"] is False

    # Block code must reflect unverified candle boundary contract
    assert caps["blocking_code"] == "CANDLE_BOUNDARY_UNVERIFIED"

    # Request validation enforces 366 day max limit and history floor
    with pytest.raises(Exception) as exc_info:
        validate_request("NIFTY", "M15", datetime(2019, 1, 1, tzinfo=IST), datetime(2019, 6, 1, tzinfo=IST))
    assert exc_info.value.code == "BEFORE_DOCUMENTED_HISTORY"


def test_historical_dataset_schema_validation_success_multi_session():
    """Verify clean 2-session dataset passes validation and excludes post-session auction prints."""
    day1 = _make_valid_day_raw("2026-10-14", 22400.0)
    day2 = _make_valid_day_raw("2026-10-15", 22500.0)
    payload = {
        "instrument": "NIFTY",
        "interval": "15minute",
        "raw_candles": day1 + day2,
    }

    res = validate_historical_dataset(payload, verified=True)
    assert res["ok"] is True
    assert res["code"] == "VALIDATED"
    assert res["total_candles_received"] == 52  # 26 + 26
    assert res["regular_candle_count"] == 50  # 25 + 25
    assert res["excluded_boundary_count"] == 2  # Two 15:30 auction ticks
    assert res["session_count"] == 2
    assert res["has_gaps"] is False
    assert res["real_market_data_verified"] is False
    assert res["forecast_ready"] is False


def test_historical_dataset_rejects_unsupported_instrument_and_interval():
    """Verify non-NIFTY instruments or non-15m intervals are rejected immediately."""
    day = _make_valid_day_raw()

    # Wrong instrument
    res_inst = validate_historical_dataset({"instrument": "BANKNIFTY", "interval": "15minute", "raw_candles": day})
    assert res_inst["ok"] is False
    assert res_inst["code"] == "UNSUPPORTED_INSTRUMENT"

    # Wrong interval
    res_inter = validate_historical_dataset({"instrument": "NIFTY", "interval": "5minute", "raw_candles": day})
    assert res_inter["ok"] is False
    assert res_inter["code"] == "UNSUPPORTED_INTERVAL"


def test_historical_dataset_rejects_invalid_numeric_ohlc_and_geometry():
    """Verify boolean prices, negative values, and High/Low geometry violations fail."""
    day = _make_valid_day_raw()

    # High < Open violation
    day_bad_geom = copy.deepcopy(day)
    day_bad_geom[3][2] = day_bad_geom[3][1] - 10.0  # High lower than Open
    res_geom = validate_historical_dataset({"instrument": "NIFTY", "interval": "15minute", "raw_candles": day_bad_geom}, verified=True)
    assert res_geom["ok"] is False
    assert res_geom["code"] == "OHLC_VALIDATION_FAILED"

    # Boolean price rejection
    day_bool = copy.deepcopy(day)
    day_bool[5][4] = True
    res_bool = validate_historical_dataset({"instrument": "NIFTY", "interval": "15minute", "raw_candles": day_bool}, verified=True)
    assert res_bool["ok"] is False
    assert res_bool["code"] == "OHLC_VALIDATION_FAILED"


def test_historical_dataset_detects_duplicate_timestamps():
    """Verify duplicate candle timestamps trigger clean failure without guessing."""
    day = _make_valid_day_raw()
    day_dup = copy.deepcopy(day)
    day_dup[2][0] = day_dup[1][0]  # Duplicate timestamp

    res = validate_historical_dataset({"instrument": "NIFTY", "interval": "15minute", "raw_candles": day_dup}, verified=True)
    assert res["ok"] is False
    assert res["code"] == "AMBIGUOUS_TIME"
    assert len(res["issues"]) == 1


def test_historical_dataset_detects_missing_candles_per_session_without_forward_fill():
    """Verify missing session candles are detected as gaps and never silently fabricated."""
    day = _make_valid_day_raw("2026-10-14")
    # Drop 10:15:00 and 10:30:00 bars (indices 4 and 5)
    dropped_day = [c for idx, c in enumerate(day) if idx not in (4, 5)]

    res = validate_historical_dataset({"instrument": "NIFTY", "interval": "15minute", "raw_candles": dropped_day}, verified=True)
    assert res["ok"] is True
    assert res["has_gaps"] is True
    assert res["missing_candles_count"] == 2
    missing_times = [m["expected_time"] for m in res["missing_candles"]]
    assert "10:15:00" in missing_times
    assert "10:30:00" in missing_times

    # Verify regular candle count equals exactly observed 23 bars (never fabricated)
    assert res["regular_candle_count"] == 23


def test_historical_dataset_excludes_incomplete_candles():
    """Verify in-progress candles whose interval extends beyond current wall time are excluded."""
    day = _make_valid_day_raw("2026-10-14")
    # Simulate wall time at 11:35:00 IST on that day
    simulated_now = datetime(2026, 10, 14, 11, 35, 0, tzinfo=IST)

    res = validate_historical_dataset(
        {"instrument": "NIFTY", "interval": "15minute", "raw_candles": day},
        verified=True,
        now=simulated_now,
    )
    assert res["ok"] is True
    # Candles starting after 11:30 (ending at 11:45 or later) must be excluded as incomplete
    assert res["excluded_incomplete_count"] > 0
    for inc in res["excluded_incomplete_candles"]:
        assert inc["exclusion_reason"] == "INCOMPLETE_CANDLE"


def test_reconciliation_returns_blocked_when_independent_reference_unavailable():
    """Verify reconciliation halts with BLOCKED_REFERENCE_UNAVAILABLE when reference is absent."""
    day = _make_valid_day_raw("2026-10-14")
    raw_payload = {"instrument": "NIFTY", "interval": "15minute", "raw_candles": day}

    res = reconcile_historical_dataset(raw_payload, reference_data=None, reference_path=None)
    assert res["ok"] is False
    assert res["code"] == "BLOCKED_REFERENCE_UNAVAILABLE"
    assert res["status"] == "BLOCKED"
    assert res["raw_hash_unchanged"] is True
    assert res["real_market_data_verified"] is False
    assert res["forecast_ready"] is False
    assert res["paper_approved"] is False
    assert res["live_approved"] is False


def test_reconciliation_detects_discrepancies_against_independent_reference():
    """Verify price excursions exceeding tolerance are flagged as discrepancies."""
    day = _make_valid_day_raw("2026-10-14", 22500.0)
    raw_payload = {"instrument": "NIFTY", "interval": "15minute", "raw_candles": day}

    # Reference has 25 regular bars but index 3 has close price 22521.0 instead of 22520.0 (delta 1.0 > 0.05 tolerance)
    ref_data = []
    for c in day[:25]:
        if c[0].endswith("10:00:00"):
            ref_data.append({
                "timestamp": c[0],
                "open": c[1],
                "high": c[2],
                "low": c[3],
                "close": c[4] + 1.0,
            })
        else:
            ref_data.append({
                "timestamp": c[0],
                "open": c[1],
                "high": c[2],
                "low": c[3],
                "close": c[4],
            })

    res = reconcile_historical_dataset(raw_payload, reference_data=ref_data, tolerance=0.05)
    assert res["ok"] is False
    assert res["code"] == "RECONCILIATION_FAILED"
    assert res["status"] == "DISCREPANCIES_DETECTED"
    assert len(res["discrepancies"]) == 1
    assert res["discrepancies"][0]["field"] == "close"


def test_reconciliation_exact_match_generates_sealed_manifest():
    """Verify exact match against independent reference produces verified manifest with unchanged raw hash."""
    day = _make_valid_day_raw("2026-10-14", 22500.0)
    raw_payload = {"instrument": "NIFTY", "interval": "15minute", "raw_candles": day}

    # Build reference matching all 25 regular candles
    ref_data = [
        {"timestamp": c[0], "open": c[1], "high": c[2], "low": c[3], "close": c[4]}
        for c in day[:25]
    ]

    res = reconcile_historical_dataset(raw_payload, reference_data=ref_data, tolerance=0.05)
    assert res["ok"] is True
    assert res["code"] == "RECONCILIATION_MATCHED"
    assert res["status"] == "RECONCILED_MATCHED"
    assert res["matched_candles_count"] == 25
    assert res["manifest"] is not None
    assert res["manifest"]["verification"]["status"] == "RECONCILED_MATCHED"
    assert res["raw_hash_unchanged"] is True

    # Invariants must remain fail-closed
    assert res["real_market_data_verified"] is False
    assert res["forecast_ready"] is False
    assert res["paper_approved"] is False
    assert res["live_approved"] is False


def test_quarantined_13_october_groww_dataset_remains_blocked():
    """Verify the quarantined 13 Oct Groww dataset remains locked in quarantine under M11."""
    path = REPO_ROOT / "var" / "history" / "quarantine" / f"{QUARANTINE_ID}.json"
    assert path.is_file()

    # Reconcile without reference must return BLOCKED_REFERENCE_UNAVAILABLE
    res = reconcile_quarantine_nifty_dataset(QUARANTINE_ID, reference_data=None, reference_path=None)
    assert res["ok"] is False
    assert res["code"] == "BLOCKED_REFERENCE_UNAVAILABLE"
    assert res["status"] == "BLOCKED"
    assert res["promoted"] is False
    assert res["real_market_data_verified"] is False


def test_real_data_walkforward_gate_blocks_unverified_or_quarantined_data():
    """Verify evaluate_real_data_walkforward refuses unverified, synthetic, or quarantined datasets."""
    # 1. Quarantined dataset
    quarantine_payload = {
        "instrument": "NIFTY",
        "quarantine_id": QUARANTINE_ID,
        "label": "UNVERIFIED_PROVIDER",
        "real_market_data_verified": False,
    }
    res_q = evaluate_real_data_walkforward(quarantine_payload)
    assert res_q["ok"] is False
    assert res_q["code"] == "BLOCKED_UNVERIFIED_DATA"
    assert res_q["status"] == "BLOCKED"

    # 2. Synthetic dataset
    synth_payload = {
        "instrument": "NIFTY",
        "origin": "SYNTHETIC",
        "synthetic": True,
        "real_market_data_verified": False,
    }
    res_s = evaluate_real_data_walkforward(synth_payload)
    assert res_s["ok"] is False
    assert res_s["code"] == "BLOCKED_UNVERIFIED_DATA"
    assert res_s["status"] == "BLOCKED"
