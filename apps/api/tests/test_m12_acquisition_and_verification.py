"""Milestone M12 regression tests: Authorized Acquisition, Verification & Real-Data Gating."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

from app.market.history import capabilities
from app.market.verified_history import (
    reconcile_historical_dataset,
    validate_historical_dataset,
    evaluate_real_data_walkforward,
    seal_historical_manifest,
    find_independent_chart_reference,
)
from app.settings import REPO_ROOT

M9_QUARANTINE_ID = "0105c2cfde527068e24b576e089b4dabfccda734fd20167ae28419a3e2e98057"
M9_EXPECTED_RAW_SHA256 = "40ec5199e8a5f1059ce941d04a1a60ef15af6973286354ca1d8ecb7224f79075"

CHUNK_IDS_6M = [
    "2323f19618c15d4f4493c797dd07491b569454d1698adb8702ed355b0c072e90",
    "354548401cc1654c40cf62bb9174a4af34fe94f17e5aa6e93a62fdffc028e785",
    "db75f3f891652f6cf900bbb9cb0b5169f2a1237a3afe5cf2b62df588049edc33",
]

EXPECTED_CHUNK_HASHES = {
    "2323f19618c15d4f4493c797dd07491b569454d1698adb8702ed355b0c072e90": "3834214245f4db55ba073db5390569f8ab385807e6ddcb6a094b737c6ed8f1a9",
    "354548401cc1654c40cf62bb9174a4af34fe94f17e5aa6e93a62fdffc028e785": "f80fc96135752675ec9845b4af1079a73c87195ee5e7f78db7ccc923415fd964",
    "db75f3f891652f6cf900bbb9cb0b5169f2a1237a3afe5cf2b62df588049edc33": "d6c92199e1697c34488feaed987046a6db3b39ef4dc3659b858a9d2a5f65983a",
}


def _load_6m_combined_candles() -> list[list]:
    all_candles = []
    seen = set()
    for qid in CHUNK_IDS_6M:
        path = REPO_ROOT / "var" / "history" / "quarantine" / f"{qid}.json"
        assert path.is_file(), f"Chunk file {path} not found"
        record = json.loads(path.read_text(encoding="utf-8"))
        for c in (record.get("raw_candles") or []):
            if c[0] not in seen:
                seen.add(c[0])
                all_candles.append(c)
    return all_candles


def test_m12_provider_selection_audit_requirements():
    """Verify provider selection criteria: Groww integration capabilities and candidate constraints."""
    caps = capabilities()
    assert caps["provider"] == "groww"
    assert caps["interval"] == "M15"
    assert caps["candle_interval"] == "15minute"
    assert caps["max_duration_per_request_days"] == 90
    assert caps["history_available_from"] == "2020"
    assert caps["blocking_code"] == "CANDLE_BOUNDARY_UNVERIFIED"

    # Confirmed: Groww returns raw candle arrays when queried with valid access token
    # Confirmed: Timezone and candle boundary semantics are unverified in documentation
    assert caps["real_market_data_verified"] is False
    assert caps["forecast_ready"] is False


def test_m12_multi_month_raw_acquisition_preserves_immutable_hashes():
    """Verify the 6-month acquired chunks and original M9 quarantine dataset have immutable SHA-256 hashes."""
    # 1. Original M9 quarantine hash preservation
    m9_path = REPO_ROOT / "var" / "history" / "quarantine" / f"{M9_QUARANTINE_ID}.json"
    assert m9_path.is_file()
    actual_m9_sha = hashlib.sha256(m9_path.read_bytes()).hexdigest()
    assert actual_m9_sha == M9_EXPECTED_RAW_SHA256, "Original M9 quarantine hash was altered"

    # 2. 6-month chunk hashes preservation
    for qid, expected_sha in EXPECTED_CHUNK_HASHES.items():
        chunk_path = REPO_ROOT / "var" / "history" / "quarantine" / f"{qid}.json"
        assert chunk_path.is_file()
        actual_sha = hashlib.sha256(chunk_path.read_bytes()).hexdigest()
        assert actual_sha == expected_sha, f"Chunk {qid} hash altered"


def test_m12_multi_session_validation_detects_2026_09_29_session_gaps():
    """Verify validate_historical_dataset processes 6 months, excludes auction ticks, and detects gaps."""
    raw_candles = _load_6m_combined_candles()
    assert len(raw_candles) == 3491  # 3491 unique candles

    payload = {
        "instrument": "NIFTY",
        "interval": "15minute",
        "raw_candles": raw_candles,
    }
    val = validate_historical_dataset(payload, verified=True)
    assert val["ok"] is True
    assert val["code"] == "VALIDATED"
    assert val["total_candles_received"] == 3491
    assert val["regular_candle_count"] == 3367
    assert val["excluded_boundary_count"] == 124  # 15:30:00 closing auction ticks excluded
    assert val["session_count"] == 125  # 125 trading sessions from April to October 2026

    # Verify session gap detection: exactly 5 missing candles on 2026-09-29
    assert val["has_gaps"] is True
    assert val["missing_candles_count"] == 5
    missing_times = [m["expected_time"] for m in val["missing_candles"]]
    assert missing_times == ["14:15:00", "14:30:00", "14:45:00", "15:00:00", "15:15:00"]
    for m in val["missing_candles"]:
        assert m["date"] == "2026-09-29"

    # Invariants
    assert val["real_market_data_verified"] is False
    assert val["forecast_ready"] is False


def test_m12_independent_verification_blocks_without_external_reference():
    """Verify reconciliation halts with BLOCKED_REFERENCE_UNAVAILABLE when independent reference is absent."""
    raw_candles = _load_6m_combined_candles()
    payload = {
        "instrument": "NIFTY",
        "interval": "15minute",
        "raw_candles": raw_candles,
    }

    # No independent reference supplied and none present in repo
    res = reconcile_historical_dataset(payload, reference_data=None, reference_path=None)
    assert res["ok"] is False
    assert res["code"] == "BLOCKED_REFERENCE_UNAVAILABLE"
    assert res["status"] == "BLOCKED"
    assert res["raw_hash_unchanged"] is True
    assert res["total_candles_received"] == 3491
    assert res["regular_candles_count"] == 3367
    assert res["session_count"] == 125
    assert res["missing_candles_count"] == 5
    assert res["has_gaps"] is True
    assert res["promoted"] is False
    assert res["real_market_data_verified"] is False
    assert res["forecast_ready"] is False
    assert res["paper_approved"] is False
    assert res["live_approved"] is False


def test_m12_dataset_manifest_sealing_preserves_provenance_and_auditability():
    """Verify seal_historical_manifest produces deterministic audit trail with untouched raw files."""
    raw_candles = _load_6m_combined_candles()
    payload = {"instrument": "NIFTY", "interval": "15minute", "raw_candles": raw_candles}
    val = validate_historical_dataset(payload, verified=True)

    manifest = seal_historical_manifest(val, source_provider="groww")
    assert manifest["manifest_version"] == "m12-sealed-manifest-1"
    assert manifest["instrument"] == "NIFTY"
    assert manifest["exchange"] == "NSE"
    assert manifest["interval"] == "15minute"
    assert manifest["timezone"] == "Asia/Kolkata"
    assert manifest["coverage"]["regular_candle_count"] == 3367
    assert manifest["coverage"]["session_count"] == 125
    assert manifest["coverage"]["missing_candles_count"] == 5
    assert manifest["coverage"]["has_gaps"] is True
    assert manifest["verification"]["status"] == "UNVERIFIED"
    assert manifest["verification"]["independent_reference_verified"] is False
    assert manifest["checksum"] is not None

    # Safety flags
    assert manifest["real_market_data_verified"] is False
    assert manifest["forecast_ready"] is False
    assert manifest["paper_approved"] is False
    assert manifest["live_approved"] is False


def test_m12_walkforward_gate_strictly_refuses_unverified_dataset():
    """Verify evaluate_real_data_walkforward refuses unverified real datasets."""
    raw_candles = _load_6m_combined_candles()
    payload = {
        "instrument": "NIFTY",
        "interval": "15minute",
        "raw_candles": raw_candles,
        "real_market_data_verified": False,
    }
    val = validate_historical_dataset(payload, verified=True)

    # Calling walk-forward on unverified dataset must fail closed
    res = evaluate_real_data_walkforward(val)
    assert res["ok"] is False
    assert res["code"] == "BLOCKED_UNVERIFIED_DATA"
    assert res["status"] == "BLOCKED"
    assert res["real_market_data_verified"] is False
    assert res["forecast_ready"] is False
    assert res["paper_approved"] is False
    assert res["live_approved"] is False


def test_m12_safety_flags_strictly_false():
    """Verify all project safety invariant gates remain locked false."""
    caps = capabilities()
    assert caps["forecast_ready"] is False
    assert caps["paper_approved"] is False
    assert caps["live_approved"] is False
    assert caps["real_market_data_verified"] is False
