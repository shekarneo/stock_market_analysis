"""Tests for worker process, PostgreSQL row leases, and scheduler loops."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.market.schemas import IST
from app.notifier import LoggingNotifier
from app.worker import Worker
from app.worker_lease import (
    acquire_lease,
    read_lease,
    release_lease,
    renew_lease,
)


def test_acquire_and_renew_lease(db):
    session = get_session_factory()()
    try:
        now = datetime.now(timezone.utc)
        res1 = acquire_lease(session, "test_intent_1", "worker_a", duration_seconds=10, now=now)
        assert res1["acquired"] is True
        assert res1["owner_id"] == "worker_a"
        assert res1["fencing_token"] == 1

        # Second worker attempts to acquire the same lease while active
        res2 = acquire_lease(session, "test_intent_1", "worker_b", duration_seconds=10, now=now)
        assert res2["acquired"] is False
        assert res2["reason"] == "LEASE_HELD_BY_ANOTHER_OWNER"
        assert res2["current_owner"] == "worker_a"

        # Worker A renews the lease
        renewed = renew_lease(session, "test_intent_1", "worker_a", duration_seconds=20, now=now + timedelta(seconds=5))
        assert renewed["renewed"] is True
        assert renewed["fencing_token"] == 1

        # Read active lease
        info = read_lease(session, "test_intent_1", now=now + timedelta(seconds=5))
        assert info is not None
        assert info["owner_id"] == "worker_a"
        assert info["is_active"] is True
    finally:
        session.close()


def test_expired_lease_takeover(db):
    session = get_session_factory()()
    try:
        t0 = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)
        # Worker A acquires lease for 5 seconds
        res1 = acquire_lease(session, "intent_timeout", "worker_a", duration_seconds=5, now=t0)
        assert res1["acquired"] is True
        assert res1["fencing_token"] == 1

        # 10 seconds later, Worker B attempts takeover
        t1 = t0 + timedelta(seconds=10)
        res2 = acquire_lease(session, "intent_timeout", "worker_b", duration_seconds=15, now=t1)
        assert res2["acquired"] is True
        assert res2.get("takeover") is True
        assert res2["owner_id"] == "worker_b"
        assert res2["fencing_token"] == 2

        # Worker A tries to renew after losing lease
        lost = renew_lease(session, "intent_timeout", "worker_a", duration_seconds=10, now=t1)
        assert lost["renewed"] is False
        assert lost["reason"] == "LEASE_NOT_FOUND_OR_NOT_OWNED"
    finally:
        session.close()


def test_release_lease(db):
    session = get_session_factory()()
    try:
        acquire_lease(session, "intent_to_release", "worker_a", duration_seconds=30)

        # Worker B cannot release Worker A's lease
        rel_other = release_lease(session, "intent_to_release", "worker_b")
        assert rel_other is False

        # Worker A releases lease
        rel_owner = release_lease(session, "intent_to_release", "worker_a")
        assert rel_owner is True

        # Lease is now gone
        info = read_lease(session, "intent_to_release")
        assert info is None
    finally:
        session.close()


def test_logging_notifier():
    notifier = LoggingNotifier()
    # Emits without raising exceptions
    notifier.notify("info", "Test Notification", "Checking logging notifier", {"key": "val"})
    notifier.notify("error", "Error Notification", "Something failed", {"error": "test"})


def test_worker_startup_reconciliation(db):
    session = get_session_factory()()
    try:
        worker = Worker("worker-test-1")
        assert worker.reconciled is False
        rec = worker.startup_reconciliation(session)
        assert rec["reconciled"] is True
        assert rec["unclosed_intents_count"] == 0
        assert worker.reconciled is True
    finally:
        session.close()


def test_worker_leader_election_and_tick(db):
    w1 = Worker("worker-1", lease_duration=10)
    w2 = Worker("worker-2", lease_duration=10)

    # Worker 1 runs once and acquires leader
    tick1 = w1.run_once()
    assert tick1["is_leader"] is True
    assert tick1["status"] == "LEADER_TICK_COMPLETED"
    assert "results" in tick1

    # Worker 2 runs concurrently and sees Worker 1 holding the lease
    tick2 = w2.run_once()
    assert tick2["is_leader"] is False
    assert tick2["status"] == "FOLLOWER_IDLE"

    # Worker 1 releases leader
    session = get_session_factory()()
    try:
        w1.release_leader(session)
    finally:
        session.close()

    # Now Worker 2 can acquire leadership
    tick2_after = w2.run_once()
    assert tick2_after["is_leader"] is True
    assert tick2_after["status"] == "LEADER_TICK_COMPLETED"


def test_worker_calendar_and_fail_closed(db):
    worker = Worker("worker-failclosed")
    session = get_session_factory()()
    try:
        # Default config has no authoritative holiday calendar
        t_session = datetime(2026, 10, 15, 10, 30, tzinfo=IST)
        cal = worker.check_calendar_status(session, t_session)
        assert cal["authoritative"] is False
        assert cal["reason"] == "CALENDAR_NOT_AUTHORITATIVE"

        # Pre/post market loop fails closed
        pre_post = worker.run_pre_post_market_loop(session, t_session)
        assert pre_post["report_written"] is False
        assert pre_post["blocked_reason"] == "CALENDAR_NOT_AUTHORITATIVE"

        # Analysis loop fails closed: no trades invented, verdict INSUFFICIENT DATA
        analysis = worker.run_analysis_loop(session, t_session)
        assert analysis["proposals_generated"] == 0
        assert analysis["decision"] == "NO_TRADE"
        assert analysis["blocked_reason"] == "CALENDAR_NOT_AUTHORITATIVE"
        assert analysis["verdict"] == "INSUFFICIENT DATA"
    finally:
        session.close()
