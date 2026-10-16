"""Milestone M16 Tests: Groww Ingestion Correction and Dataset Preparation.

Tests:
- Raw quarantine SHA-256 hash preservation and integrity
- Chunk boundary conflict detection and reconciliation (July 15 and October 13, 2026)
- Session classification (regular session vs pre-market vs post-market)
- Missing interval and session completeness detection (September 29, 2026 gap)
- Clean derived regular-session dataset construction and sealing
- Safety invariant preservation and disabled broker routing
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from app.execution.orders import live_order_calls
from app.market.groww_ingestion import (
    M12_CHUNK_IDS,
    M9_QUARANTINE_ID,
    RECORDED_RAW_HASHES,
    audit_session_completeness,
    build_derived_nifty_regular_dataset,
    classify_market_session_observations,
    load_raw_quarantine_chunks,
    reconcile_chunk_boundaries,
    verify_raw_quarantine_integrity,
)
from app.market.history import capabilities
from app.settings import REPO_ROOT


def test_m16_phase1_raw_quarantine_integrity():
    """Phase 1: Recalculate all 4 recorded M9/M12 SHA-256 hashes and verify 100% match."""
    integrity = verify_raw_quarantine_integrity()
    assert integrity["ok"] is True
    assert integrity["total_files"] == 4

    for qid, res in integrity["results"].items():
        assert res["status"] == "MATCH"
        assert res["actual"] == RECORDED_RAW_HASHES[qid]


def test_m16_phase2_boundary_discrepancy_and_conflict_reconciliation():
    """Phase 2: Detect and reconcile July 15 and October 13 boundary discrepancies."""
    chunks = load_raw_quarantine_chunks()
    reconciled = reconcile_chunk_boundaries(chunks)

    assert reconciled["ok"] is True
    assert reconciled["duplicates_count"] == 2
    assert reconciled["conflicts_count"] == 2

    # Discrepancy 1: 2026-07-15T09:15:00 between Chunk 1 (trailing) and Chunk 2 (leading)
    c1 = next(c for c in reconciled["conflicts"] if c["timestamp"] == "2026-07-15T09:15:00")
    assert c1["trailing_chunk_idx"] == 1
    assert c1["leading_chunk_idx"] == 2
    # Open and Low match
    assert c1["trailing_ohlc"][0] == c1["leading_ohlc"][0] == 24082.45
    assert c1["trailing_ohlc"][2] == c1["leading_ohlc"][2] == 24074.70
    # High and Close differ due to request cutoff in Chunk 1
    assert c1["trailing_ohlc"][1] == 24114.60  # Truncated
    assert c1["leading_ohlc"][1] == 24211.70   # Complete
    assert c1["deltas"]["high_delta"] == pytest.approx(97.10, abs=0.01)
    assert c1["deltas"]["close_delta"] == pytest.approx(95.35, abs=0.01)
    assert c1["resolution"] == "RETAIN_LEADING_CHUNK_CANDLE"

    # Discrepancy 2: 2026-10-13T09:15:00 between Chunk 2 (trailing) and Chunk 3 (leading)
    c2 = next(c for c in reconciled["conflicts"] if c["timestamp"] == "2026-10-13T09:15:00")
    assert c2["trailing_chunk_idx"] == 2
    assert c2["leading_chunk_idx"] == 3
    assert c2["trailing_ohlc"][0] == c2["leading_ohlc"][0] == 22367.25
    assert c2["trailing_ohlc"][2] == c2["leading_ohlc"][2] == 22288.70
    assert c2["trailing_ohlc"][1] == 22373.35  # Truncated
    assert c2["leading_ohlc"][1] == 22478.05   # Complete
    assert c2["deltas"]["high_delta"] == pytest.approx(104.70, abs=0.01)
    assert c2["deltas"]["close_delta"] == pytest.approx(150.25, abs=0.01)
    assert c2["resolution"] == "RETAIN_LEADING_CHUNK_CANDLE"


def test_m16_phase3_session_classification_rules():
    """Phase 3: Classify regular session candles vs pre-market (09:00) and post-market (15:30/15:45)."""
    chunks = load_raw_quarantine_chunks()
    reconciled = reconcile_chunk_boundaries(chunks)
    classified = classify_market_session_observations(reconciled["reconciled_candles"])

    assert classified["regular_count"] == 3120
    assert classified["excluded_count"] == 371
    assert classified["pre_market_count"] == 124
    assert classified["post_market_30_count"] == 124
    assert classified["post_market_45_count"] == 123
    assert classified["regular_count"] + classified["excluded_count"] == 3491

    # Verify all excluded observations carry explicit reasons
    for exc in classified["excluded_observations"]:
        assert "exclusion_reason" in exc
        assert "exclusion_detail" in exc
        assert exc["session_type"] in ("PRE_MARKET", "POST_MARKET_AUCTION", "POST_MARKET_SETTLED_MARK")


def test_m16_phase4_missing_data_and_session_gaps():
    """Phase 4: Detect September 29, 2026 session gap and record in data quality manifest."""
    chunks = load_raw_quarantine_chunks()
    reconciled = reconcile_chunk_boundaries(chunks)
    classified = classify_market_session_observations(reconciled["reconciled_candles"])
    completeness = audit_session_completeness(classified["regular_candles"])

    assert completeness["total_sessions"] == 125
    assert completeness["complete_sessions_count"] == 124
    assert completeness["incomplete_sessions_count"] == 1
    assert completeness["total_missing_bars_count"] == 5

    # Check the specific incomplete session on 2026-09-29
    sep29 = completeness["sessions"]["2026-09-29"]
    assert sep29["is_complete"] is False
    assert sep29["observed_count"] == 20
    assert sep29["expected_count"] == 25
    assert sep29["missing_count"] == 5
    assert sep29["missing_times"] == ["14:15:00", "14:30:00", "14:45:00", "15:00:00", "15:15:00"]


def test_m16_phase5_derived_regular_dataset_build_and_sealing(tmp_path: Path):
    """Phase 5: Build derived regular session dataset with full lineage, metadata, and artifacts."""
    result = build_derived_nifty_regular_dataset(save_artifact=True, destination_dir=tmp_path)

    assert result["ok"] is True
    assert result["status"] == "INTERNALLY_VALIDATED_EXTERNALLY_UNVERIFIED"
    assert result["regular_candles_count"] == 3120
    assert result["excluded_observations_count"] == 371
    assert result["complete_sessions"] == 124
    assert result["incomplete_sessions"] == 1
    assert result["missing_bars"] == 5

    # Verify artifact was created on disk
    art_path = Path(result["artifact_path"])
    assert art_path.is_file()
    saved = json.loads(art_path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == "m16-derived-regular-dataset-1"
    assert saved["instrument"] == "NIFTY"
    assert saved["interval"] == "15minute"
    assert saved["bar_start_semantics"] == "BAR_START"
    assert saved["timezone"] == "Asia/Kolkata"
    assert len(saved["regular_candles"]) == 3120

    # Verify safety flags inside dataset
    assert saved["safety_invariants"]["real_market_data_verified"] is False
    assert saved["safety_invariants"]["forecast_ready"] is False
    assert saved["safety_invariants"]["paper_approved"] is False
    assert saved["safety_invariants"]["live_approved"] is False


def test_m16_phase6_safety_invariants_and_broker_routing_disabled():
    """Phase 6: All trading and forecasting readiness flags remain false; broker routing disabled."""
    caps = capabilities()
    assert caps["forecast_ready"] is False
    assert caps["real_market_data_verified"] is False
    assert caps["paper_approved"] is False
    assert caps["live_approved"] is False
    assert len(live_order_calls) == 0
