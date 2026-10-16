"""Milestone M14 Tests: Independent Historical Data Verification and Walk-Forward Research Benchmark."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

from app.market.provenance import quarantine_training_block
from app.market.verified_history import (
    INDEPENDENT_SOURCES,
    evaluate_real_data_walkforward,
    find_independent_chart_reference,
    reconcile_historical_dataset,
    reconcile_quarantine_nifty_dataset,
    seal_historical_manifest,
    validate_historical_dataset,
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


def _load_6m_raw_candles() -> list[list]:
    candles = []
    seen = set()
    for qid in CHUNK_IDS_6M:
        path = REPO_ROOT / "var" / "history" / "quarantine" / f"{qid}.json"
        assert path.is_file(), f"Missing quarantine chunk {qid}"
        record = json.loads(path.read_text(encoding="utf-8"))
        for c in (record.get("raw_candles") or []):
            if c[0] not in seen:
                seen.add(c[0])
                candles.append(c)
    return candles


def test_m14_phase1_audit_evidence_and_immutable_hashes():
    """Phase 1: Verify M9 and all M12 raw quarantine files retain exact immutable SHA-256 hashes."""
    # 1. Original M9 quarantine file
    m9_file = REPO_ROOT / "var" / "history" / "quarantine" / f"{M9_QUARANTINE_ID}.json"
    assert m9_file.is_file()
    actual_m9_sha = hashlib.sha256(m9_file.read_bytes()).hexdigest()
    assert actual_m9_sha == M9_EXPECTED_RAW_SHA256

    # 2. All 3 M12 raw chunks
    for qid, expected_sha in EXPECTED_CHUNK_HASHES.items():
        chunk_file = REPO_ROOT / "var" / "history" / "quarantine" / f"{qid}.json"
        assert chunk_file.is_file()
        actual_chunk_sha = hashlib.sha256(chunk_file.read_bytes()).hexdigest()
        assert actual_chunk_sha == expected_sha

    # 3. Verify no unverified real data has bypassed quarantine
    raw_candles = _load_6m_raw_candles()
    payload = {"raw_candles": raw_candles, "instrument": "NIFTY"}
    block_reason = quarantine_training_block(payload)
    assert block_reason is not None
    assert block_reason[0] == "QUARANTINE_REJECTED"


def test_m14_phase2_candidate_reference_audit_and_blockers():
    """Phase 2: Verify candidate independent sources are documented with unresolved blockers."""
    assert len(INDEPENDENT_SOURCES) >= 5

    providers = {s["provider"]: s for s in INDEPENDENT_SOURCES}

    # Upstox
    assert "Upstox" in providers
    assert providers["Upstox"]["verification_status"] == "BLOCKED"
    assert "credential_not_configured" in providers["Upstox"]["outstanding_blockers"]

    # Zerodha Kite Connect
    assert "Zerodha Kite Connect" in providers
    assert providers["Zerodha Kite Connect"]["verification_status"] == "BLOCKED"
    assert "credential_not_configured" in providers["Zerodha Kite Connect"]["outstanding_blockers"]

    # Angel One
    assert "Angel One SmartAPI" in providers
    assert providers["Angel One SmartAPI"]["verification_status"] == "BLOCKED"

    # DhanHQ
    assert "DhanHQ" in providers
    assert providers["DhanHQ"]["verification_status"] == "BLOCKED"

    # NSE Official
    assert "NSE" in providers
    assert providers["NSE"]["verification_status"] == "BLOCKED"
    assert "interval_is_daily" in providers["NSE"]["outstanding_blockers"]


def test_m14_phase3_reconciliation_fails_closed_when_reference_absent():
    """Phase 3: Verify reconciliation reports BLOCKED_REFERENCE_UNAVAILABLE when reference is absent."""
    raw_candles = _load_6m_raw_candles()
    payload = {
        "instrument": "NIFTY",
        "interval": "15minute",
        "raw_candles": raw_candles,
    }

    res = reconcile_historical_dataset(payload, reference_data=None, reference_path=None)
    assert res["ok"] is False
    assert res["code"] == "BLOCKED_REFERENCE_UNAVAILABLE"
    assert res["status"] == "BLOCKED"
    assert res["raw_hash_unchanged"] is True
    assert res["promoted"] is False
    assert res["real_market_data_verified"] is False
    assert res["forecast_ready"] is False
    assert res["paper_approved"] is False
    assert res["live_approved"] is False


def test_m14_phase3_reconciliation_detects_ohlc_discrepancy_and_matches_valid_reference():
    """Phase 3: Verify reconciliation algorithm correctly evaluates OHLC match against a reference fixture."""
    # Test slice of 3 candles
    raw_slice = [
        ["2026-10-14T09:15:00", 22715.30, 22751.35, 22664.05, 22686.95, None, None],
        ["2026-10-14T09:30:00", 22687.35, 22734.25, 22667.05, 22732.15, None, None],
        ["2026-10-14T09:45:00", 22731.70, 22757.80, 22699.65, 22708.70, None, None],
    ]
    payload = {"instrument": "NIFTY", "interval": "15minute", "raw_candles": raw_slice}

    # Case A: Reference matches perfectly within tolerance
    matching_reference = [
        {"timestamp": "2026-10-14T09:15:00+05:30", "open": 22715.30, "high": 22751.35, "low": 22664.05, "close": 22686.95},
        {"timestamp": "2026-10-14T09:30:00+05:30", "open": 22687.35, "high": 22734.25, "low": 22667.05, "close": 22732.15},
        {"timestamp": "2026-10-14T09:45:00+05:30", "open": 22731.70, "high": 22757.80, "low": 22699.65, "close": 22708.70},
    ]
    matched_res = reconcile_historical_dataset(payload, reference_data=matching_reference, tolerance=0.05)
    assert matched_res["ok"] is True
    assert matched_res["code"] == "RECONCILIATION_MATCHED"
    assert matched_res["matched_candles_count"] == 3
    assert matched_res["max_discrepancy"] == 0.0

    # Case B: Reference has OHLC discrepancy exceeding tolerance (e.g. 5 points higher close)
    mismatched_reference = [
        {"timestamp": "2026-10-14T09:15:00+05:30", "open": 22715.30, "high": 22751.35, "low": 22664.05, "close": 22691.95},
        {"timestamp": "2026-10-14T09:30:00+05:30", "open": 22687.35, "high": 22734.25, "low": 22667.05, "close": 22732.15},
        {"timestamp": "2026-10-14T09:45:00+05:30", "open": 22731.70, "high": 22757.80, "low": 22699.65, "close": 22708.70},
    ]
    mismatch_res = reconcile_historical_dataset(payload, reference_data=mismatched_reference, tolerance=0.05)
    assert mismatch_res["ok"] is False
    assert mismatch_res["code"] == "RECONCILIATION_FAILED"
    assert mismatch_res["matched_candles_count"] == 2
    assert any(d["type"] == "OHLC_MISMATCH" for d in mismatch_res["discrepancies"])


def test_m14_phase4_dataset_seal_marks_unverified_when_unreconciled():
    """Phase 4: Sealed manifest marks UNVERIFIED and preserves safety gates when reconciliation is incomplete."""
    raw_candles = _load_6m_raw_candles()
    payload = {"instrument": "NIFTY", "interval": "15minute", "raw_candles": raw_candles}
    val = validate_historical_dataset(payload, verified=True)

    manifest = seal_historical_manifest(val, source_provider="groww")
    assert manifest["verification"]["status"] == "UNVERIFIED"
    assert manifest["verification"]["independent_reference_verified"] is False
    assert manifest["real_market_data_verified"] is False
    assert manifest["forecast_ready"] is False
    assert manifest["paper_approved"] is False
    assert manifest["live_approved"] is False


def test_m14_phase5_walkforward_benchmark_strictly_blocks_unverified_data():
    """Phase 5: Real-data walk-forward benchmark strictly refuses unverified real datasets."""
    raw_candles = _load_6m_raw_candles()
    payload = {
        "instrument": "NIFTY",
        "interval": "15minute",
        "raw_candles": raw_candles,
        "real_market_data_verified": False,
    }
    val = validate_historical_dataset(payload, verified=True)

    # Calling walk-forward benchmark on unverified dataset fails closed
    benchmark_res = evaluate_real_data_walkforward(val)
    assert benchmark_res["ok"] is False
    assert benchmark_res["code"] == "BLOCKED_UNVERIFIED_DATA"
    assert benchmark_res["status"] == "BLOCKED"
    assert benchmark_res["real_market_data_verified"] is False
    assert benchmark_res["forecast_ready"] is False
    assert benchmark_res["paper_approved"] is False
    assert benchmark_res["live_approved"] is False


def test_m14_phase6_safety_invariants_and_broker_routing_disabled():
    """Phase 6: All safety flags remain false and broker order routing remains disabled."""
    from app.execution.orders import live_order_calls
    from app.market.history import capabilities

    caps = capabilities()
    assert caps["forecast_ready"] is False
    assert caps["real_market_data_verified"] is False
    assert caps["paper_approved"] is False
    assert caps["live_approved"] is False

    # Broker routing disabled
    assert len(live_order_calls) == 0
