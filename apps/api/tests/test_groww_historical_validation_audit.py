"""Groww Historical Data Validation Audit Tests.

Tests internal validation of Groww historical data against official Customer Success
confirmations, audits raw quarantine hashes, tests chunk boundary overlap defects,
verifies OHLC consistency, detects data gaps, and validates safety invariants.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

from app.market.timestamp_contract import contract, verified_contract
from app.settings import REPO_ROOT

CHUNK_FILES = {
    "m9": "0105c2cfde527068e24b576e089b4dabfccda734fd20167ae28419a3e2e98057",
    "chunk1": "2323f19618c15d4f4493c797dd07491b569454d1698adb8702ed355b0c072e90",
    "chunk2": "354548401cc1654c40cf62bb9174a4af34fe94f17e5aa6e93a62fdffc028e785",
    "chunk3": "db75f3f891652f6cf900bbb9cb0b5169f2a1237a3afe5cf2b62df588049edc33",
}

EXPECTED_HASHES = {
    "m9": "40ec5199e8a5f1059ce941d04a1a60ef15af6973286354ca1d8ecb7224f79075",
    "chunk1": "3834214245f4db55ba073db5390569f8ab385807e6ddcb6a094b737c6ed8f1a9",
    "chunk2": "f80fc96135752675ec9845b4af1079a73c87195ee5e7f78db7ccc923415fd964",
    "chunk3": "d6c92199e1697c34488feaed987046a6db3b39ef4dc3659b858a9d2a5f65983a",
}


def test_audit_customer_success_confirmation():
    """Verify official Customer Success evidence establishes IST bar-start semantics."""
    support_doc = REPO_ROOT / "docs" / "GROWW_CANDLE_TIMESTAMP_SUPPORT_RESPONSE.md"
    assert support_doc.is_file(), "Support response document must exist."
    content = support_doc.read_text(encoding="utf-8")
    assert "Indian Standard Time (IST)" in content
    assert "Each timestamp represents the beginning of the candle" in content
    assert "09:15:00" in content
    assert "15:15:00" in content

    # Test verified contract mapping
    v = verified_contract()
    assert v["established"] is True
    assert v["timestamp_timezone"] == "Asia/Kolkata"
    assert v["candle_boundary"] == "BAR_START"
    assert v["session_open_candle"] == "09:15:00"
    assert v["session_close_candle"] == "15:15:00"


def test_audit_quarantine_raw_hashes_preserved():
    """Verify all 4 quarantine raw files retain exact immutable SHA-256 digests."""
    for key, qid in CHUNK_FILES.items():
        p = REPO_ROOT / "var" / "history" / "quarantine" / f"{qid}.json"
        assert p.is_file(), f"Missing quarantine file {qid}"
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        assert digest == EXPECTED_HASHES[key]


def test_audit_chunk_overlap_discrepancy_detection():
    """Audit confirms pagination defect: boundary candle at end_time is truncated."""
    p1 = REPO_ROOT / "var" / "history" / "quarantine" / f"{CHUNK_FILES['chunk1']}.json"
    p2 = REPO_ROOT / "var" / "history" / "quarantine" / f"{CHUNK_FILES['chunk2']}.json"
    p3 = REPO_ROOT / "var" / "history" / "quarantine" / f"{CHUNK_FILES['chunk3']}.json"

    d1 = json.loads(p1.read_text())
    d2 = json.loads(p2.read_text())
    d3 = json.loads(p3.read_text())

    c1 = {r[0]: r for r in d1["raw_candles"]}
    c2 = {r[0]: r for r in d2["raw_candles"]}
    c3 = {r[0]: r for r in d3["raw_candles"]}

    # Overlap 1 & 2 at 2026-07-15T09:15:00
    ts1 = "2026-07-15T09:15:00"
    assert ts1 in c1 and ts1 in c2
    # Open and Low match, High and Close differ due to request end boundary cutoff
    assert c1[ts1][1] == c2[ts1][1] == 24082.45
    assert c1[ts1][3] == c2[ts1][3] == 24074.7
    assert c1[ts1][2] != c2[ts1][2]  # High differs (24114.6 in c1 vs 24211.7 in c2)
    assert c1[ts1][4] != c2[ts1][4]  # Close differs (24100.35 in c1 vs 24195.7 in c2)

    # Overlap 2 & 3 at 2026-10-13T09:15:00
    ts2 = "2026-10-13T09:15:00"
    assert ts2 in c2 and ts2 in c3
    assert c2[ts2][1] == c3[ts2][1] == 22367.25
    assert c2[ts2][3] == c3[ts2][3] == 22288.7
    assert c2[ts2][2] != c3[ts2][2]  # High differs (22373.35 in c2 vs 22478.05 in c3)
    assert c2[ts2][4] != c3[ts2][4]  # Close differs (22321.15 in c2 vs 22471.4 in c3)


def test_audit_ohlc_consistency_and_geometry():
    """Audit confirms 100% positive prices and geometric validity across all raw candles."""
    total_candles = 0
    for key in ("chunk1", "chunk2", "chunk3"):
        p = REPO_ROOT / "var" / "history" / "quarantine" / f"{CHUNK_FILES[key]}.json"
        data = json.loads(p.read_text())
        for c in data["raw_candles"]:
            total_candles += 1
            o, h, l, close_p = c[1], c[2], c[3], c[4]
            assert o > 0 and h > 0 and l > 0 and close_p > 0
            assert h >= max(o, close_p)
            assert l <= min(o, close_p)
            assert h >= l
    assert total_candles == 3493


def test_audit_detects_2026_09_29_session_gap():
    """Audit confirms data gap on 2026-09-29 where session terminates at 14:00:00."""
    p2 = REPO_ROOT / "var" / "history" / "quarantine" / f"{CHUNK_FILES['chunk2']}.json"
    d2 = json.loads(p2.read_text())
    day_candles = [c for c in d2["raw_candles"] if c[0].startswith("2026-09-29")]
    # Only 21 candles present instead of standard 28
    assert len(day_candles) == 21
    timestamps = [c[0][11:] for c in day_candles]
    assert timestamps[-1] == "14:00:00"
    # Missing continuous bars 14:15, 14:30, 14:45, 15:00, 15:15
    for missing_t in ("14:15:00", "14:30:00", "14:45:00", "15:00:00", "15:15:00"):
        assert missing_t not in timestamps


def test_audit_boundary_candles_0900_and_1530_and_1545():
    """Audit confirms pre-market (09:00) and post-market (15:30/15:45) distribution."""
    p1 = REPO_ROOT / "var" / "history" / "quarantine" / f"{CHUNK_FILES['chunk1']}.json"
    d1 = json.loads(p1.read_text())
    c_0900 = [c for c in d1["raw_candles"] if c[0].endswith("09:00:00")]
    c_1530 = [c for c in d1["raw_candles"] if c[0].endswith("15:30:00")]
    c_1545 = [c for c in d1["raw_candles"] if c[0].endswith("15:45:00")]

    assert len(c_0900) > 0  # Pre-market observations
    assert len(c_1530) > 0  # Post-market closing auction observations
    assert len(c_1545) > 0  # Post-market settled marks
    # 15:45 candles consistently have open == high == low == close
    for c in c_1545:
        assert c[1] == c[2] == c[3] == c[4]


def test_audit_safety_invariants_preserved():
    """Verify safety flags remain false and broker routing is disabled."""
    from app.execution.orders import live_order_calls
    from app.market.history import capabilities

    caps = capabilities()
    assert caps["forecast_ready"] is False
    assert caps["real_market_data_verified"] is False
    assert caps["paper_approved"] is False
    assert caps["live_approved"] is False
    assert len(live_order_calls) == 0
