"""Milestone M36 Test Suite: Production Daemon & Operational Integration.

Verifies:
1. Production worker daemon pre-market loop runs the formal 8-Gate Paper Readiness Audit at 08:30 IST.
2. Production worker position monitor enforces the 15:15 IST intraday auto square-off lifecycle.
3. Production worker outcome drift loop trips operational kill switch upon critical feature drift (PSI >= 0.25).
4. Analysis loop enforces entry cutoffs and regime consensus gating.
5. Absolute enforcement of live-trading safety boundaries: ModeForbidden and LiveOrderDisabled guarantees.
6. Full leader tick execution across all four integrated operational loops.
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest
from sqlalchemy import select

from app.config.schemas import OperatingMode
from app.config.store import current_config, ensure_seed, replace_section
from app.db import get_session_factory
from app.domain.tables import OpsState
from app.errors import LiveOrderDisabled, ModeForbidden
from app.execution.orders import place_live_order, request_order
from app.market.schemas import IST
from app.notifier import LoggingNotifier
from app.risk.ledger import set_kill_switch
from app.settings import get_settings
from app.worker import Worker


class MockNotifier(LoggingNotifier):
    def __init__(self) -> None:
        super().__init__()
        self.notifications: list[dict] = []

    def notify(self, level: str, title: str, message: str, metadata: dict | None = None) -> None:
        super().notify(level, title, message, metadata)
        self.notifications.append({
            "level": level,
            "title": title,
            "message": message,
            "metadata": metadata or {},
        })


def _setup_authoritative_calendar(session) -> None:
    """Helper to configure holiday calendar so ExchangeCalendar is authoritative."""
    settings = get_settings()
    ensure_seed(session, settings)
    replace_section(
        session,
        settings,
        "schedule",
        {
            "analysis_cadence_seconds": 300,
            "holiday_calendar_source_id": "nse_official_calendar",
        },
        "tester",
    )
    session.commit()


def test_worker_pre_market_readiness_audit(db):
    """Verify that worker executes 8-gate paper readiness audit during pre-market (08:30 IST)."""
    session = get_session_factory()()
    try:
        _setup_authoritative_calendar(session)
        notifier = MockNotifier()
        worker = Worker("test-worker-premarket", notifier=notifier)

        t_pre = datetime(2026, 10, 16, 8, 30, 0, tzinfo=IST)
        report = worker.run_pre_post_market_loop(session, now=t_pre)

        assert report["loop"] == "pre_post_market"
        assert report["report_written"] is True
        assert report["phase"] == "PRE_MARKET"
        assert report["readiness_status"] == "READY_FOR_PAPER_SIMULATION"
        assert report["live_trading_verdict"] == "STRICT_NO_GO_LOCKED"
        assert report["gates_evaluated"] == 8
        assert report["failed_gates"] == 0

        # Verify notification emission
        assert any("Pre-Market Readiness Audit" in n["title"] for n in notifier.notifications)
    finally:
        session.close()


def test_worker_intraday_square_off_enforcement(db):
    """Verify position monitor enforces entry cutoffs, auto square-off alerts, and market freeze."""
    session = get_session_factory()()
    try:
        notifier = MockNotifier()
        worker = Worker("test-worker-squareoff", notifier=notifier)

        # 1. Normal session (10:30 IST)
        t_norm = datetime(2026, 10, 16, 10, 30, 0, tzinfo=IST)
        p1 = worker.run_position_monitor_loop(session, now=t_norm)
        assert p1["square_off_status"] == "NORMAL_TRADING"
        assert p1["allow_new_entries"] is True
        assert p1["force_square_off_now"] is False
        assert len(p1["actions_taken"]) == 0

        # 2. Entry cutoff window (15:12 IST)
        t_cutoff = datetime(2026, 10, 16, 15, 12, 0, tzinfo=IST)
        p2 = worker.run_position_monitor_loop(session, now=t_cutoff)
        assert p2["square_off_status"] == "ENTRY_CUTOFF"
        assert p2["allow_new_entries"] is False
        assert "ENTRY_CUTOFF_ENFORCED" in p2["actions_taken"]

        # 3. Mandatory square-off window (15:18 IST)
        t_sq = datetime(2026, 10, 16, 15, 18, 0, tzinfo=IST)
        p3 = worker.run_position_monitor_loop(session, now=t_sq)
        assert p3["square_off_status"] == "MANDATORY_SQUARE_OFF"
        assert p3["force_square_off_now"] is True
        assert "AUTO_SQUARE_OFF_TRIGGERED" in p3["actions_taken"]
        assert any("Mandatory Auto Square-Off" in n["title"] for n in notifier.notifications)

        # 4. Market closed (15:45 IST)
        t_close = datetime(2026, 10, 16, 15, 45, 0, tzinfo=IST)
        p4 = worker.run_position_monitor_loop(session, now=t_close)
        assert p4["square_off_status"] == "MARKET_CLOSED"
        assert "MARKET_CLOSED_FROZEN" in p4["actions_taken"]
    finally:
        session.close()


def test_worker_analysis_loop_enforces_intraday_cutoff(db):
    """Verify analysis loop suppresses new trade proposals once entry cutoff is reached."""
    session = get_session_factory()()
    try:
        _setup_authoritative_calendar(session)
        worker = Worker("test-worker-analysis")

        # 15:12 IST cutoff window
        t_cutoff = datetime(2026, 10, 16, 15, 12, 0, tzinfo=IST)
        res = worker.run_analysis_loop(session, now=t_cutoff)

        assert res["decision"] == "NO_TRADE"
        assert res["proposals_generated"] == 0
        assert "CUTOFF_ACTIVE" in res.get("blocked_reason", "")
    finally:
        session.close()


def test_worker_drift_circuit_breaker_trips_kill_switch(db):
    """Verify that worker drift loop automatically trips operational kill switch on severe drift."""
    session = get_session_factory()()
    try:
        # Reset kill switch to baseline False
        set_kill_switch(session, False, actor="test.setup", reason="reset_baseline")
        notifier = MockNotifier()
        worker = Worker("test-worker-drift", notifier=notifier)

        # 1. Stable feature matrices
        ref_matrix = {"atr": [50.0 + i * 0.1 for i in range(100)]}
        target_stable = {"atr": [50.2 + i * 0.1 for i in range(100)]}

        res_stable = worker.run_outcome_drift_loop(
            session,
            reference_matrix=ref_matrix,
            target_matrix=target_stable,
        )
        assert res_stable["drift_detected"] is False
        assert res_stable["kill_switch_tripped"] is False

        # OpsState should remain un-tripped
        ops = session.get(OpsState, 1)
        assert ops is not None and ops.kill_switch is False

        # 2. Critical distribution drift (5x volatility displacement)
        target_drift = {"atr": [250.0 + i * 2.0 for i in range(100)]}
        res_drift = worker.run_outcome_drift_loop(
            session,
            reference_matrix=ref_matrix,
            target_matrix=target_drift,
        )
        assert res_drift["drift_detected"] is True
        assert res_drift["kill_switch_tripped"] is True
        assert res_drift["overall_drift_status"] == "CRITICAL_DRIFT"

        # OpsState kill switch must be flipped to True in PostgreSQL
        session.refresh(ops)
        assert ops.kill_switch is True

        # Operator notification must have fired
        assert any(n["level"] == "critical" and "Circuit Breaker Tripped" in n["title"] for n in notifier.notifications)
    finally:
        session.close()


def test_worker_live_trading_hard_safety_locks():
    """Verify live broker order dispatch is permanently locked out under all caller configurations."""
    intent = {"underlying": "NIFTY", "quantity": 75, "price": 25000.0}

    # 1. Non-live mode raises ModeForbidden
    with pytest.raises(ModeForbidden):
        request_order(OperatingMode.PAPER, intent, live_trading_enabled=False, server_flag=False)

    # 2. LIVE_TRADING mode without server flags raises ModeForbidden
    with pytest.raises(ModeForbidden):
        request_order(OperatingMode.LIVE_TRADING, intent, live_trading_enabled=False, server_flag=False)

    with pytest.raises(ModeForbidden):
        request_order(OperatingMode.LIVE_TRADING, intent, live_trading_enabled=True, server_flag=False)

    with pytest.raises(ModeForbidden):
        request_order(OperatingMode.LIVE_TRADING, intent, live_trading_enabled=False, server_flag=True)

    # 3. Even if caller provides live flags = True, place_live_order raises LiveOrderDisabled
    with pytest.raises(LiveOrderDisabled):
        request_order(OperatingMode.LIVE_TRADING, intent, live_trading_enabled=True, server_flag=True)

    with pytest.raises(LiveOrderDisabled):
        place_live_order(intent)


def test_worker_full_leader_tick_with_integrated_loops(db):
    """Verify full end-to-end execution of worker run_once() with all 4 integrated loops."""
    session = get_session_factory()()
    try:
        _setup_authoritative_calendar(session)
    finally:
        session.close()

    worker = Worker("test-worker-full-tick", lease_duration=15)

    t_pre = datetime(2026, 10, 16, 8, 30, 0, tzinfo=IST)
    ref_matrix = {"atr": [50.0 + i * 0.1 for i in range(50)]}
    target_matrix = {"atr": [50.1 + i * 0.1 for i in range(50)]}

    tick_result = worker.run_once(
        now=t_pre,
        reference_matrix=ref_matrix,
        target_matrix=target_matrix,
    )

    assert tick_result["is_leader"] is True
    assert tick_result["status"] == "LEADER_TICK_COMPLETED"
    assert "results" in tick_result

    results = tick_result["results"]
    assert results["pre_post"]["loop"] == "pre_post_market"
    assert results["pre_post"]["readiness_status"] == "READY_FOR_PAPER_SIMULATION"
    assert results["analysis"]["loop"] == "analysis"
    assert results["positions"]["loop"] == "position_monitor"
    assert results["drift"]["loop"] == "outcome_drift"
    assert results["drift"]["drift_detected"] is False

    # Clean release
    session_cleanup = get_session_factory()()
    try:
        worker.release_leader(session_cleanup)
    finally:
        session_cleanup.close()

