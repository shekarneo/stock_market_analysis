"""Milestone M9 regression tests: Ground-Truth Chart Comparison, Reconciliation, and Dataset Seal."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

from app.market.history import HistoryStore
from app.market.verified_history import (
    KNOWN_QUARANTINE_RAW_SHA256,
    build_trusted_dataset,
    find_independent_chart_reference,
    promote_reconciled_dataset,
    reconcile_quarantine_nifty_dataset,
    validate_quarantine_nifty_dataset,
)
from app.settings import REPO_ROOT

QUARANTINE_ID = "0105c2cfde527068e24b576e089b4dabfccda734fd20167ae28419a3e2e98057"
EXPECTED_RAW_SHA256 = "40ec5199e8a5f1059ce941d04a1a60ef15af6973286354ca1d8ecb7224f79075"


def _raw_groww_regular_candles():
    path = REPO_ROOT / "var" / "history" / "quarantine" / f"{QUARANTINE_ID}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    raw_candles = record.get("raw_candles") or []
    # 25 regular session candles from 09:15 to 15:15
    return raw_candles[:25]


def _build_exact_match_reference():
    raw_25 = _raw_groww_regular_candles()
    return [
        {
            "timestamp": row[0],
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]) if len(row) > 5 and row[5] is not None else 0.0,
        }
        for row in raw_25
    ]


def test_raw_groww_quarantine_file_sha256_integrity():
    path = REPO_ROOT / "var" / "history" / "quarantine" / f"{QUARANTINE_ID}.json"
    assert path.is_file()
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual_hash == EXPECTED_RAW_SHA256
    assert KNOWN_QUARANTINE_RAW_SHA256[QUARANTINE_ID] == EXPECTED_RAW_SHA256


def test_missing_reference_returns_blocked_reference_unavailable():
    # When no independent reference is passed and none found in repository
    result = reconcile_quarantine_nifty_dataset(QUARANTINE_ID, reference_data=None, reference_path=None)
    assert result["ok"] is False
    assert result["code"] == "BLOCKED_REFERENCE_UNAVAILABLE"
    assert result["status"] == "BLOCKED"
    assert "Independent machine-readable NIFTY 15-minute OHLC reference" in result["message"]
    assert result["manifest"] is None
    assert result["promoted"] is False
    assert result["real_market_data_verified"] is False
    assert result["forecast_ready"] is False
    assert result["paper_approved"] is False
    assert result["live_approved"] is False


def test_build_trusted_dataset_when_reference_unavailable():
    # Calling build_trusted_dataset(verified=True) without chart_reference returns BLOCKED_REFERENCE_UNAVAILABLE
    res = build_trusted_dataset(QUARANTINE_ID, verified=True, chart_reference=None)
    assert res["ok"] is False
    assert res["code"] == "BLOCKED_REFERENCE_UNAVAILABLE"
    assert res["status"] == "BLOCKED"
    assert res["real_market_data_verified"] is False


def test_exact_matches_produce_deterministic_manifest_and_success():
    ref = _build_exact_match_reference()
    assert len(ref) == 25

    res = reconcile_quarantine_nifty_dataset(QUARANTINE_ID, reference_data=ref)
    assert res["ok"] is True
    assert res["code"] == "RECONCILIATION_MATCHED"
    assert res["status"] == "RECONCILED_MATCHED"
    assert res["included_candles_count"] == 25
    assert res["excluded_candles_count"] == 1
    assert res["matched_candles_count"] == 25
    assert res["max_discrepancy"] == 0.0
    assert res["discrepancies"] == []

    # Manifest verification
    manifest = res["manifest"]
    assert manifest is not None
    assert manifest["schema_version"] == "m9-manifest-1"
    assert manifest["instrument"] == "NIFTY"
    assert manifest["interval"] == "M15"
    assert manifest["trading_date"] == "2026-10-13"
    assert manifest["timezone"] == "Asia/Kolkata"
    assert manifest["raw_data_hash"] == EXPECTED_RAW_SHA256
    assert manifest["validated_dataset_hash"] == res["dataset_id"]
    assert manifest["total_candles_received"] == 26
    assert manifest["included_candle_count"] == 25
    assert manifest["excluded_candle_count"] == 1
    assert "POST_SESSION_AUCTION_TICK" in manifest["exclusion_reasons"]["2026-10-13T15:30:00"]
    assert manifest["comparison_results"]["total_matched"] == 25
    assert manifest["comparison_results"]["discrepancies"] == []
    assert manifest["validation_status"] == "RECONCILED_MATCHED"

    # Safety invariant: real_market_data_verified must stay False
    assert manifest["real_market_data_verified"] is False
    assert res["real_market_data_verified"] is False
    assert res["forecast_ready"] is False
    assert res["paper_approved"] is False
    assert res["live_approved"] is False


def test_ohlc_mismatches_detected_and_recorded():
    ref = _build_exact_match_reference()
    # Introduce deliberate price discrepancy on close of first candle (09:15)
    ref[0]["close"] = 22475.0  # Groww price is 22471.4, diff = 3.6 > tolerance 0.05
    ref[0]["high"] = 22478.05  # stays consistent

    res = reconcile_quarantine_nifty_dataset(QUARANTINE_ID, reference_data=ref, tolerance=0.05)
    assert res["ok"] is False
    assert res["code"] == "RECONCILIATION_FAILED"
    assert res["status"] == "DISCREPANCIES_DETECTED"
    assert len(res["discrepancies"]) == 1
    disc = res["discrepancies"][0]
    assert disc["type"] == "OHLC_MISMATCH"
    assert disc["timestamp"] == "2026-10-13T09:15:00"
    assert disc["field"] == "close"
    assert disc["groww_price"] == 22471.4
    assert disc["reference_price"] == 22475.0
    assert disc["difference"] == 3.6
    assert disc["tolerance"] == 0.05
    assert res["manifest"] is None
    assert res["promoted"] is False


def test_missing_candles_in_reference_detected():
    ref = _build_exact_match_reference()
    # Drop candle at 11:00:00
    ref_missing = [c for c in ref if c["timestamp"] != "2026-10-13T11:00:00"]
    assert len(ref_missing) == 24

    res = reconcile_quarantine_nifty_dataset(QUARANTINE_ID, reference_data=ref_missing)
    assert res["ok"] is False
    assert res["code"] == "RECONCILIATION_FAILED"
    disc = [d for d in res["discrepancies"] if d["type"] == "MISSING_CANDLE_IN_REFERENCE"]
    assert len(disc) == 1
    assert disc[0]["timestamp"] == "2026-10-13T11:00:00"


def test_unexpected_candles_in_reference_detected():
    ref = _build_exact_match_reference()
    # Add unexpected bar at 09:00:00 before NSE open
    extra = dict(ref[0], timestamp="2026-10-13T09:00:00")
    ref.append(extra)

    res = reconcile_quarantine_nifty_dataset(QUARANTINE_ID, reference_data=ref)
    assert res["ok"] is False
    assert res["code"] == "RECONCILIATION_FAILED"
    disc = [d for d in res["discrepancies"] if d["type"] == "UNEXPECTED_REFERENCE_CANDLE"]
    assert len(disc) == 1
    assert disc[0]["timestamp"] == "2026-10-13T09:00:00"


def test_duplicate_candles_in_reference_detected():
    ref = _build_exact_match_reference()
    # Duplicate the 09:30 candle
    ref.append(dict(ref[1]))

    res = reconcile_quarantine_nifty_dataset(QUARANTINE_ID, reference_data=ref)
    assert res["ok"] is False
    assert res["code"] == "RECONCILIATION_FAILED"
    disc = [d for d in res["discrepancies"] if d["type"] == "DUPLICATE_REFERENCE_CANDLE"]
    assert len(disc) >= 1
    assert disc[0]["timestamp"] == "2026-10-13T09:30:00"


def test_timezone_mismatches_in_reference_detected():
    ref = _build_exact_match_reference()
    # Tag reference candle with UTC (+00:00) instead of IST (+05:30)
    ref[0]["timestamp"] = "2026-10-13T09:15:00+00:00"

    res = reconcile_quarantine_nifty_dataset(QUARANTINE_ID, reference_data=ref)
    assert res["ok"] is False
    assert res["code"] == "RECONCILIATION_FAILED"
    disc = [d for d in res["discrepancies"] if d["type"] == "TIMEZONE_MISMATCH"]
    assert len(disc) == 1
    assert "non-IST" in disc[0]["reason"]


def test_invalid_ohlc_values_in_reference_rejected():
    ref = _build_exact_match_reference()
    # High lower than close
    ref[0]["high"] = 22400.0  # close is 22471.4, open is 22367.25

    res = reconcile_quarantine_nifty_dataset(QUARANTINE_ID, reference_data=ref)
    assert res["ok"] is False
    assert res["code"] == "RECONCILIATION_FAILED"
    disc = [d for d in res["discrepancies"] if d["type"] == "INVALID_REFERENCE_OHLC"]
    assert len(disc) == 1
    assert "Invalid OHLC relationship" in disc[0]["reason"]


def test_invalid_ohlc_values_in_raw_quarantine_rejected():
    # Test validate_quarantine_nifty_dataset handles corrupted candles
    from app.market.quarantine_validation import validate_quarantine_payload
    bad_record = {
        "quarantine_id": "bad",
        "checksum": "bad",
        "raw_candles": [["2026-10-13T09:15:00", 100, 90, 80, 95, None]],  # high 90 < open 100
    }
    diag = validate_quarantine_payload(bad_record)
    assert any(item["status"] == "FAIL" for item in diag["failed"])


def test_raw_data_hash_changes_rejected():
    ref = _build_exact_match_reference()
    # Provide an unexpected raw hash
    wrong_hash = "0000000000000000000000000000000000000000000000000000000000000000"
    res = reconcile_quarantine_nifty_dataset(QUARANTINE_ID, reference_data=ref, expected_raw_sha256=wrong_hash)
    assert res["ok"] is False
    assert res["code"] == "RAW_DATA_HASH_CHANGED"
    assert "differs from expected" in res["message"]


def test_raw_quarantine_file_bytes_remain_strictly_unchanged():
    path = REPO_ROOT / "var" / "history" / "quarantine" / f"{QUARANTINE_ID}.json"
    bytes_before = path.read_bytes()
    sha_before = hashlib.sha256(bytes_before).hexdigest()

    # Run missing reference
    reconcile_quarantine_nifty_dataset(QUARANTINE_ID, reference_data=None)
    # Run exact match reference
    ref = _build_exact_match_reference()
    reconcile_quarantine_nifty_dataset(QUARANTINE_ID, reference_data=ref)
    # Run failing reference
    ref_fail = _build_exact_match_reference()
    ref_fail[0]["close"] = 99999.0
    reconcile_quarantine_nifty_dataset(QUARANTINE_ID, reference_data=ref_fail)

    bytes_after = path.read_bytes()
    sha_after = hashlib.sha256(bytes_after).hexdigest()

    assert bytes_before == bytes_after
    assert sha_before == sha_after == EXPECTED_RAW_SHA256


def test_promotion_fails_when_unreconciled_and_succeeds_when_matched(tmp_path):
    temp_store = HistoryStore(tmp_path / "history")

    # 1. Unreconciled / blocked result cannot be promoted
    blocked = reconcile_quarantine_nifty_dataset(QUARANTINE_ID, reference_data=None)
    p_fail = promote_reconciled_dataset(blocked, store=temp_store)
    assert p_fail["ok"] is False
    assert p_fail["code"] == "PROMOTION_REFUSED"

    # 2. Reconciled and matched dataset promotes successfully
    ref = _build_exact_match_reference()
    matched = reconcile_quarantine_nifty_dataset(QUARANTINE_ID, reference_data=ref)
    p_succ = promote_reconciled_dataset(matched, store=temp_store)
    assert p_succ["ok"] is True
    assert p_succ["code"] == "PROMOTED"
    assert p_succ["promoted"] is True
    dataset_id = p_succ["dataset_id"]
    assert dataset_id is not None

    # Verify stored artifact in HistoryStore
    saved = temp_store.read(dataset_id)
    assert saved["kind"] == "source_candles"
    assert saved["candle_count"] == 25
    assert saved["candle_boundary_role"] == "start"
    assert saved["manifest"]["raw_data_hash"] == EXPECTED_RAW_SHA256

    # Verify safety flags strictly remain False in promoted dataset
    assert saved["real_market_data_verified"] is False
    assert saved["forecast_ready"] is False
    assert saved["paper_approved"] is False
    assert saved["live_approved"] is False


def test_build_trusted_dataset_with_chart_reference_and_promotion(tmp_path):
    temp_store = HistoryStore(tmp_path / "history")
    ref = _build_exact_match_reference()

    res = build_trusted_dataset(QUARANTINE_ID, verified=True, chart_reference=ref, promote=True, store=temp_store)
    assert res["ok"] is True
    assert res["code"] == "RECONCILIATION_MATCHED"
    assert res["promoted"] is True
    assert res["promotion"]["code"] == "PROMOTED"
    assert res["real_market_data_verified"] is False
