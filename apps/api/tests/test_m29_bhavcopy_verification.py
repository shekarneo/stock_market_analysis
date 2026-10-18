"""Unit and integration test suite for Milestone M29: Official NSE Bhavcopy Adapter & Reconciliation.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from sqlalchemy import select

from app.db import session_scope
from app.domain.tables import CandleConflictAudit
from app.market.bhavcopy_adapter import (
    BHAVCOPY_TOLERANCE_BPS,
    DailyBhavcopyRecord,
    aggregate_groww_candles_to_daily,
    parse_nse_cm_equity_bhavcopy_csv,
    parse_nse_index_bhavcopy_csv,
    reconcile_groww_with_bhavcopy,
    save_bhavcopy_raw_artifact,
)
from app.settings import REPO_ROOT


SAMPLE_NSE_INDEX_CSV = """
Index Name, Index Date, Open Index Value, High Index Value, Low Index Value, Closing Index Value, Points Change, Change(%), Volume, Turnover (Rs. Cr.), P/E, P/B, Div Yield
Nifty 50, 14-10-2026, 25260.00, 25350.50, 25210.20, 25320.80, 60.80, 0.24, 245000000, 28500.45, 22.4, 4.1, 1.25
Nifty Bank, 14-10-2026, 51800.00, 52100.00, 51750.00, 52050.00, 250.00, 0.48, 120000000, 15400.20, 18.2, 2.8, 0.95
Nifty 50, 15-10-2026, 25340.00, 25410.00, 25290.00, 25380.00, 59.20, 0.23, 230000000, 27100.10, 22.5, 4.1, 1.24
"""

SAMPLE_NSE_EQUITY_CSV = """
SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, LAST, PREVCLOSE, TOTTRDQTY, TOTTRDVAL, TIMESTAMP, TOTALTRADES, ISIN
RELIANCE, EQ, 2850.00, 2880.00, 2840.00, 2872.50, 2871.00, 2845.00, 5200000, 14800000000.00, 14-OCT-2026, 185000, INE002A01018
TCS, EQ, 4150.00, 4190.00, 4140.00, 4182.00, 4180.00, 4145.00, 2100000, 8750000000.00, 14-OCT-2026, 95000, INE467B01029
"""


def test_parse_nse_index_bhavcopy_csv():
    """Verify parsing of official NSE Index daily Bhavcopy format."""
    records = parse_nse_index_bhavcopy_csv(SAMPLE_NSE_INDEX_CSV, target_index="Nifty 50")

    assert len(records) == 2
    rec1 = records[0]
    assert rec1.symbol == "NIFTY"
    assert rec1.date_str == "2026-10-14"
    assert rec1.open == 25260.0
    assert rec1.high == 25350.50
    assert rec1.low == 25210.20
    assert rec1.close == 25320.80
    assert rec1.volume == 245000000.0
    assert rec1.turnover_inr > 0.0

    rec2 = records[1]
    assert rec2.date_str == "2026-10-15"
    assert rec2.close == 25380.0


def test_parse_nse_cm_equity_bhavcopy_csv():
    """Verify parsing of official NSE Capital Market equity Bhavcopy format."""
    records = parse_nse_cm_equity_bhavcopy_csv(SAMPLE_NSE_EQUITY_CSV, target_symbol="RELIANCE")

    assert len(records) == 1
    rel = records[0]
    assert rel.symbol == "RELIANCE"
    assert rel.date_str == "2026-10-14"
    assert rel.open == 2850.0
    assert rel.high == 2880.0
    assert rel.low == 2840.0
    assert rel.close == 2872.50
    assert rel.volume == 5200000.0


def test_groww_daily_session_aggregation():
    """Verify that 15m intraday candles aggregate into mathematically exact daily session OHLCV."""
    candles_15m = [
        # Bar 0: 09:15
        ["2026-10-14 09:15:00", 25260.0, 25290.0, 25250.0, 25280.0, 1000.0, 0.0],
        # Bar 1: 09:30
        ["2026-10-14 09:30:00", 25280.0, 25350.5, 25270.0, 25340.0, 1500.0, 0.0],
        # Bar 2: 12:00
        ["2026-10-14 12:00:00", 25340.0, 25345.0, 25210.2, 25230.0, 2000.0, 0.0],
        # Bar 3: 15:15 (Final regular bar)
        ["2026-10-14 15:15:00", 25300.0, 25330.0, 25290.0, 25320.8, 3000.0, 0.0],
    ]

    daily = aggregate_groww_candles_to_daily(candles_15m)
    assert "2026-10-14" in daily
    d = daily["2026-10-14"]

    assert d["open"] == 25260.0        # First bar open
    assert d["high"] == 25350.5        # Max high across bars
    assert d["low"] == 25210.2         # Min low across bars
    assert d["close"] == 25320.8       # Last bar close
    assert d["volume"] == 7500.0       # Sum of volumes
    assert d["bar_count"] == 4


def test_bhavcopy_reconciliation_exact_match():
    """Verify reconciliation succeeds with 0 conflicts when candles match within tolerance."""
    candles_15m = [
        ["2026-10-14 09:15:00", 25260.0, 25350.5, 25210.2, 25320.8, 1000.0, 0.0],
        ["2026-10-14 15:15:00", 25300.0, 25325.0, 25280.0, 25320.8, 2000.0, 0.0],
    ]

    bhavcopy_records = parse_nse_index_bhavcopy_csv(SAMPLE_NSE_INDEX_CSV, target_index="Nifty 50")

    report = reconcile_groww_with_bhavcopy(
        groww_15m_candles=candles_15m,
        bhavcopy_records=bhavcopy_records,
        dataset_id="test_dataset_exact",
        tolerance_bps=5.0,
    )

    assert report.total_days_evaluated == 1
    assert report.matched_days_count == 1
    assert report.conflict_days_count == 0
    assert report.verification_status == "VERIFIED_MATCH"
    assert report.matches[0].is_match is True
    assert report.matches[0].status == "RECONCILED_MATCH"


def test_bhavcopy_reconciliation_conflict_detection_and_db_audit():
    """Verify that discrepancies exceeding tolerance_bps are flagged and logged to DB."""
    # Intentional discrepancy: Groww Close = 25450 (vs Bhavcopy 25320.8, diff ~51 bps > 5 bps)
    candles_15m = [
        ["2026-10-14 09:15:00", 25260.0, 25350.5, 25210.2, 25280.0, 1000.0, 0.0],
        ["2026-10-14 15:15:00", 25280.0, 25450.0, 25270.0, 25450.0, 2000.0, 0.0],
    ]

    bhavcopy_records = parse_nse_index_bhavcopy_csv(SAMPLE_NSE_INDEX_CSV, target_index="Nifty 50")

    with session_scope() as s:
        report = reconcile_groww_with_bhavcopy(
            groww_15m_candles=candles_15m,
            bhavcopy_records=bhavcopy_records,
            dataset_id="test_dataset_conflict",
            tolerance_bps=5.0,
            db_session=s,
        )

        assert report.conflict_days_count == 1
        assert report.matched_days_count == 0
        assert report.verification_status == "CONFLICT_FLAGGED"
        assert report.matches[0].is_match is False
        assert report.matches[0].status == "CONFLICT_DETECTED"

        # Verify record in PostgreSQL CandleConflictAudit table
        stmt = select(CandleConflictAudit).where(
            CandleConflictAudit.incoming_artifact_id == "bhavcopy_2026-10-14"
        )
        audit_row = s.execute(stmt).scalar_one_or_none()
        assert audit_row is not None
        assert audit_row.symbol == "NIFTY"
        assert audit_row.resolution == "FLAGGED_FOR_HUMAN_AUDIT"


def test_m29_safety_invariants_strictly_false():
    """Verify all 5 hard financial safety invariants remain False in M29 verification report."""
    bhavcopy_records = parse_nse_index_bhavcopy_csv(SAMPLE_NSE_INDEX_CSV, target_index="Nifty 50")
    report = reconcile_groww_with_bhavcopy(
        groww_15m_candles=[["2026-10-14 09:15:00", 25260.0, 25350.5, 25210.2, 25320.8, 1000.0, 0.0]],
        bhavcopy_records=bhavcopy_records,
        dataset_id="test_safety",
    )

    inv = report.safety_invariants
    assert inv["forecast_ready"] is False
    assert inv["real_market_data_verified"] is False
    assert inv["paper_approved"] is False
    assert inv["live_approved"] is False
    assert inv["live_broker_routing_enabled"] is False
