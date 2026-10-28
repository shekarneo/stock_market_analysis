"""Milestone M35 Test Suite: Production Operational Runbook & System Synthesis.

Verifies:
1. Operational runbook documentation integrity and standard operating procedure completeness.
2. System health endpoint behavior under normal vs tripped operational kill-switch state.
3. Worker lease lifecycle, distributed row lease mutual exclusion, and monotonic fencing tokens.
4. Daily IST operational execution timeline: normal trading, entry cutoff, auto square-off, and market close.
5. Daily pre-market 8-gate paper-trading readiness audit integration.
6. Absolute enforcement of all 5 hard financial safety invariants.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from sqlalchemy import select

from app.db import get_session_factory
from app.domain.tables import AuditEvent
from app.research.paper_readiness_audit import (
    PaperReadinessReport,
    audit_paper_trading_readiness,
)
from app.risk.ledger import set_kill_switch
from app.risk.portfolio_risk import assess_intraday_square_off
from app.settings import REPO_ROOT
from app.worker_lease import (
    acquire_lease,
    read_lease,
    release_lease,
    renew_lease,
)


def test_runbook_documentation_completeness():
    """Verify that PRODUCTION_OPERATIONAL_RUNBOOK.md exists and contains all required SOP sections."""
    runbook_path = REPO_ROOT / "docs" / "PRODUCTION_OPERATIONAL_RUNBOOK.md"
    assert runbook_path.exists(), "PRODUCTION_OPERATIONAL_RUNBOOK.md must exist in docs/"

    content = runbook_path.read_text(encoding="utf-8")

    # Required Operational Sections
    assert "System Architecture & Component Topology" in content
    assert "Daily Operational Schedule (Indian Standard Time — Asia/Kolkata)" in content
    assert "08:30 – 08:45" in content
    assert "15:10 – 15:15" in content
    assert "15:15 – 15:25" in content
    assert "15:45 – 16:15" in content
    assert "16:15 – 16:45" in content
    assert "Emergency Operator Controls & Remediation Procedures" in content
    assert "Tripping the Operational Kill Switch Manually" in content
    assert "Market Data Provenance & Bhavcopy Reconciliation SOP" in content
    assert "Indian Statutory Regulatory Taxation & Fee Reference" in content
    assert "Live-Trading Authorization Protocol" in content
    assert "Dual-Key Authorization" in content

    # Financial Safety Invariants mentioned
    assert "forecast_ready" in content or "FINANCIAL SAFETY INVARIANTS" in content
    assert "STRICT_NO_GO_LOCKED" in content or "live_approved" in content


def test_operational_health_reflects_kill_switch_state(client, db):
    """Verify that /health accurately mirrors database kill-switch state and logs audit events."""
    session = get_session_factory()()
    try:
        # 1. Baseline state
        set_kill_switch(session, False, actor="test.setup", reason="reset_baseline")
        res1 = client.get("/health")
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["status"] == "ok"
        assert data1["process"] is True
        assert data1["database"] is True
        assert data1["kill_switch"] is False
        assert data1["live_trading_enabled"] is False

        # 2. Trip kill switch (emergency SOP)
        set_kill_switch(session, True, actor="operator.emergency", reason="DRIFT_BREACH_DETECTED")
        res2 = client.get("/health")
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["kill_switch"] is True

        # 3. Verify immutable audit log in database
        audit = session.execute(
            select(AuditEvent)
            .where(AuditEvent.action == "risk.kill_switch")
            .order_by(AuditEvent.id.desc())
        ).scalars().first()
        assert audit is not None
        assert audit.actor == "operator.emergency"
        assert audit.after["kill_switch"] is True
        assert audit.after["reason"] == "DRIFT_BREACH_DETECTED"

        # 4. Remediation: clear kill switch
        set_kill_switch(session, False, actor="operator.remediated", reason="RECALIBRATED_BASELINE")
        res3 = client.get("/health")
        assert res3.status_code == 200
        data3 = res3.json()
        assert data3["kill_switch"] is False
    finally:
        session.close()


def test_worker_lease_lifecycle_and_monotonic_fencing(db):
    """Verify distributed worker lease acquisition, renewal, mutual exclusion, and monotonic fencing tokens."""
    session = get_session_factory()()
    try:
        t0 = datetime(2026, 10, 17, 9, 15, 0, tzinfo=timezone.utc)
        lease_key = "scheduler:runbook_leader"

        # 1. Worker A acquires initial lease
        res_a1 = acquire_lease(session, lease_key, "worker_node_A", duration_seconds=30, now=t0)
        assert res_a1["acquired"] is True
        assert res_a1["fencing_token"] == 1
        assert res_a1["owner_id"] == "worker_node_A"

        # 2. Worker A renews lease at t0 + 10s
        t1 = t0 + timedelta(seconds=10)
        renew_a = renew_lease(session, lease_key, "worker_node_A", duration_seconds=30, now=t1)
        assert renew_a["renewed"] is True
        assert renew_a["fencing_token"] == 1

        # 3. Worker B attempts to acquire while active at t0 + 15s -> must be rejected
        t2 = t0 + timedelta(seconds=15)
        res_b1 = acquire_lease(session, lease_key, "worker_node_B", duration_seconds=30, now=t2)
        assert res_b1["acquired"] is False
        assert res_b1["reason"] == "LEASE_HELD_BY_ANOTHER_OWNER"
        assert res_b1["current_owner"] == "worker_node_A"

        # 4. Advance time past expiration (t1 + 35s = t0 + 45s) -> Worker B takes over lease
        t3 = t0 + timedelta(seconds=45)
        res_b2 = acquire_lease(session, lease_key, "worker_node_B", duration_seconds=30, now=t3)
        assert res_b2["acquired"] is True
        assert res_b2["takeover"] is True
        assert res_b2["owner_id"] == "worker_node_B"
        # Monotonic fencing token must increment to 2
        assert res_b2["fencing_token"] == 2

        # 5. Stale Worker A attempts renewal -> must fail because lease was taken over
        renew_stale = renew_lease(session, lease_key, "worker_node_A", duration_seconds=30, now=t3)
        assert renew_stale["renewed"] is False
        assert renew_stale["reason"] == "LEASE_NOT_FOUND_OR_NOT_OWNED"

        # 6. Read lease
        readout = read_lease(session, lease_key, now=t3)
        assert readout is not None
        assert readout["owner_id"] == "worker_node_B"
        assert readout["fencing_token"] == 2
        assert readout["is_active"] is True

        # 7. Worker B clean release
        released = release_lease(session, lease_key, "worker_node_B")
        assert released is True
        assert read_lease(session, lease_key, now=t3) is None
    finally:
        session.close()


def test_daily_ist_trading_timeline_enforcement():
    """Verify daily IST timeline stages match production operational runbook specifications."""
    # Pre-market (08:30 IST)
    p1 = assess_intraday_square_off("08:30:00")
    assert p1.status == "MARKET_CLOSED"
    assert p1.allow_new_entries is False

    # Normal session morning (10:00 IST)
    p2 = assess_intraday_square_off("10:00:00")
    assert p2.status == "NORMAL_TRADING"
    assert p2.allow_new_entries is True
    assert p2.force_square_off_now is False

    # Normal session afternoon (14:30 IST)
    p3 = assess_intraday_square_off("14:30:00")
    assert p3.status == "NORMAL_TRADING"
    assert p3.allow_new_entries is True
    assert p3.force_square_off_now is False

    # Entry cutoff window (15:12 IST)
    p4 = assess_intraday_square_off("15:12:00")
    assert p4.status == "ENTRY_CUTOFF"
    assert p4.allow_new_entries is False
    assert p4.force_square_off_now is False

    # Auto square-off window (15:18 IST)
    p5 = assess_intraday_square_off("15:18:00")
    assert p5.status == "MANDATORY_SQUARE_OFF"
    assert p5.allow_new_entries is False
    assert p5.force_square_off_now is True

    # Post-close (15:45 IST)
    p6 = assess_intraday_square_off("15:45:00")
    assert p6.status == "MARKET_CLOSED"
    assert p6.allow_new_entries is False
    assert p6.force_square_off_now is False


@pytest.mark.usefixtures("validated_edge")
def test_premarket_health_audit_gate_verification(db):
    """Verify daily pre-market checklist execution evaluates all 8 readiness gates successfully."""
    session = get_session_factory()()
    try:
        report = audit_paper_trading_readiness(session)
        assert isinstance(report, PaperReadinessReport)
        assert report.total_gates_evaluated == 8
        assert report.failed_gates == 0
        assert report.overall_readiness == "READY_FOR_PAPER_SIMULATION"
        assert report.live_trading_verdict == "STRICT_NO_GO_LOCKED"

        # Confirm all 5 safety invariants strictly False
        assert report.forecast_ready is False
        assert report.real_market_data_verified is False
        assert report.paper_approved is False
        assert report.live_approved is False
        assert report.live_broker_routing_enabled is False
    finally:
        session.close()
