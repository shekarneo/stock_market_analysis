"""The simulated-fill boundary records a refusal and does not apply a fill."""

from __future__ import annotations

import threading

from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from app.db import get_session_factory
from app.domain.tables import AuditEvent, PaperTransition, RiskEvent, RiskSession
from app.execution.boundary import propose_simulated_fill, unchanged_financial_state
from app.execution.orders import live_order_calls
from app.execution.paper import PAPER_TRADING_ACTIVE
from app.execution.simulation import replay_simulation_decision, session_loop_status
from app.settings import REPO_ROOT
from tests.conftest import login
from tests.test_paper_simulation import AT, _body, _dataset, _run

_FLAGS = (
    "forecast_ready",
    "paper_approved",
    "live_approved",
    "real_market_data_verified",
    "live_trading_enabled",
)


def _event(intent_id: str, audit_id: int, body_hash: str, **extra) -> dict:
    payload = {
        "event_type": "SIMULATED_FILL",
        "event_id": "fill-1",
        "intent_id": intent_id,
        "decision_audit_id": audit_id,
        "body_hash": body_hash,
        "side": "BUY",
        "underlying": "NIFTY",
        "expiry": "2026-10-16",
        "strike": "22500",
        "option_type": "CE",
        "quantity": "65",
        "price": "10",
        "occurred_at": AT,
        "price_source": "caller",
        "charges_inr": "1",
        "slippage_inr": "0.5",
        "paper_approved": True,
        "risk_passed": True,
    }
    payload.update(extra)
    return payload


def _decision(intent_id: str) -> tuple[int, str]:
    session = get_session_factory()()
    try:
        replay = replay_simulation_decision(session, intent_id)
        attempt = next(item for item in replay["attempts"] if item["decision_attempt"] is True)
        return attempt["audit_id"], replay["body_hash"]
    finally:
        session.close()


def _book(session) -> dict:
    return {
        "sessions": session.scalar(select(func.count()).select_from(RiskSession)),
        "events": session.scalar(select(func.count()).select_from(RiskEvent)),
        "fills": session.scalar(
            select(func.count()).select_from(PaperTransition).where(
                PaperTransition.to_state.in_(("FILLED", "PARTIALLY_FILLED", "CLOSED")),
                PaperTransition.applied.is_(True),
            )
        ),
        "refusals": session.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "paper.execution_refused")
        ),
    }


def test_disabled_execution_ignores_caller_approval_and_leaves_the_book(db):
    live_order_calls.clear()
    assert _run(_body(_dataset(), "exec-off"))["code"] == "VETOED"
    audit_id, body_hash = _decision("exec-off")
    session = get_session_factory()()
    try:
        before = _book(session)
        refused = propose_simulated_fill(session, _event("exec-off", audit_id, body_hash), actor="tester")
        assert refused["applied"] is False
        assert refused["persisted_fill"] is False
        assert refused["fill"] is None
        assert refused["simulated_fill"] is None
        assert refused["financial_mutation"] is False
        assert refused["code"] == "EXECUTION_DISABLED"
        assert "STORED_DECISION_NOT_PASS" in refused["reasons"]
        assert "GATES_NOT_PASSED" in refused["reasons"]
        assert "IGNORED_CALLER_FLAG" in refused["reasons"]
        assert "MISSING_RISK_CAPITAL" in refused["reasons"]
        assert "CASH_UNKNOWN" in refused["reasons"]
        assert "CHARGES_UNVERIFIED" in refused["reasons"]
        assert "TICK_SIZE_MISSING" in refused["reasons"]
        assert "LOT_SIZE_UNVERIFIED" in refused["reasons"]
        assert "RECONCILIATION_UNAVAILABLE" in refused["reasons"]
        assert "PRICE_SOURCE_UNVERIFIED" in refused["reasons"]
        for name in _FLAGS:
            assert refused[name] is False
        assert PAPER_TRADING_ACTIVE is False
        assert session_loop_status()["ran"] is False
        after = _book(session)
        assert after["sessions"] == before["sessions"]
        assert after["events"] == before["events"]
        assert after["fills"] == 0
        assert after["refusals"] == before["refusals"] + 1
        assert unchanged_financial_state(session) is True
        assert live_order_calls == []
    finally:
        session.close()


def test_missing_snapshot_invalid_contract_and_unknown_charges_do_not_fill(db):
    live_order_calls.clear()
    assert _run(_body(_dataset(), "exec-contract"))["state"] == "VETOED"
    audit_id, body_hash = _decision("exec-contract")
    session = get_session_factory()()
    try:
        missing = propose_simulated_fill(session, _event("exec-absent", 1, "a" * 64, event_id="missing-snap"), actor="tester")
        assert missing["code"] == "SNAPSHOT_MISSING"
        assert missing["applied"] is False
        assert "DECISION_MISSING" in missing["reasons"]
        stale = propose_simulated_fill(
            session,
            _event("exec-contract", audit_id, "b" * 64, event_id="stale-hash"),
            actor="tester",
        )
        assert stale["code"] == "STALE_DECISION"
        wrong_attempt = propose_simulated_fill(
            session,
            _event("exec-contract", audit_id + 1000, body_hash, event_id="stale-id"),
            actor="tester",
        )
        assert wrong_attempt["code"] == "STALE_DECISION"
        invalid = propose_simulated_fill(
            session,
            _event("exec-contract", audit_id, body_hash, event_id="bad-shape", quantity="0", price="-1", side="HOLD", tick_size="0", lot_size="0"),
            actor="tester",
        )
        assert invalid["code"] == "INVALID_SIDE"
        assert "INVALID_QUANTITY" in invalid["reasons"]
        assert "INVALID_PRICE" in invalid["reasons"]
        assert "INVALID_TICK_SIZE" in invalid["reasons"]
        assert "INVALID_LOT_SIZE" in invalid["reasons"]
        unknown = propose_simulated_fill(
            session,
            _event("exec-contract", audit_id, body_hash, event_id="no-charge", charges_inr=None, slippage_inr=None),
            actor="tester",
        )
        assert unknown["applied"] is False
        assert "CHARGES_UNKNOWN" in unknown["reasons"]
        assert "SLIPPAGE_UNKNOWN" in unknown["reasons"]
        assert "CHARGES_UNVERIFIED" not in unknown["reasons"]
        supplied_tick = propose_simulated_fill(
            session,
            _event("exec-contract", audit_id, body_hash, event_id="tick-supplied", tick_size="0.05", lot_size="65"),
            actor="tester",
        )
        assert supplied_tick["applied"] is False
        assert "TICK_UNIT_UNVERIFIED" in supplied_tick["reasons"]
        assert "TICK_CONFLICT" in supplied_tick["reasons"]
        assert "LOT_CONFLICT" in supplied_tick["reasons"]
        ledger_fill = propose_simulated_fill(session, {"event_type": "FILL", "event_id": "ledger", "intent_id": "exec-contract"}, actor="tester")
        assert ledger_fill["code"] == "INVALID_EVENT_TYPE"
        assert ledger_fill["recorded_refusal"] is False
        assert unchanged_financial_state(session) is True
        assert session.scalar(select(func.count()).select_from(RiskEvent)) == 0
    finally:
        session.close()


def test_duplicate_event_is_idempotent_and_a_changed_payload_conflicts(db):
    assert _run(_body(_dataset(), "exec-idem"))["state"] == "VETOED"
    audit_id, body_hash = _decision("exec-idem")
    event = _event("exec-idem", audit_id, body_hash, event_id="same-fill")
    session = get_session_factory()()
    try:
        first = propose_simulated_fill(session, event, actor="tester")
        second = propose_simulated_fill(session, event, actor="tester")
        conflict = propose_simulated_fill(session, {**event, "price": "11"}, actor="tester")
        assert first["applied"] is False
        assert second["code"] == "DUPLICATE_EVENT"
        assert second["applied"] is False
        assert second["payload_hash"] == first["payload_hash"]
        assert conflict["code"] == "DUPLICATE_EVENT_CONFLICT"
        assert conflict["applied"] is False
        assert session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "paper.execution_refused")) == 1
        assert session.scalar(select(func.count()).select_from(RiskEvent)) == 0
        assert unchanged_financial_state(session) is True
    finally:
        session.close()


def test_concurrent_refusals_and_a_failed_commit_leave_no_fill(db, monkeypatch):
    assert _run(_body(_dataset(), "exec-race"))["state"] == "VETOED"
    audit_id, body_hash = _decision("exec-race")
    event = _event("exec-race", audit_id, body_hash, event_id="race-fill")
    barrier = threading.Barrier(2)
    results = []

    def worker() -> None:
        barrier.wait(timeout=5)
        local = get_session_factory()()
        try:
            results.append(propose_simulated_fill(local, event, actor="tester"))
        finally:
            local.close()

    threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert len(results) == 2
    assert {item["applied"] for item in results} == {False}
    assert {item["fill"] for item in results} == {None}
    check = get_session_factory()()
    try:
        assert check.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "paper.execution_refused")) == 1
        assert check.scalar(select(func.count()).select_from(RiskEvent)) == 0
        assert unchanged_financial_state(check) is True
    finally:
        check.close()

    real = OrmSession.commit

    def fail(self):
        if getattr(self, "_fail_commit", False):
            raise RuntimeError("commit interrupted")
        return real(self)

    monkeypatch.setattr(OrmSession, "commit", fail)
    session = get_session_factory()()
    session._fail_commit = True
    try:
        interrupted = propose_simulated_fill(
            session,
            _event("exec-race", audit_id, body_hash, event_id="rolled-back"),
            actor="tester",
        )
        assert interrupted["code"] == "EXECUTION_INTERRUPTED"
        assert interrupted["recorded_refusal"] is False
        assert interrupted["applied"] is False
    finally:
        session.close()
    fresh = get_session_factory()()
    try:
        assert fresh.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "paper.execution_refused", AuditEvent.entity == "paper_intent:exec-race")
        ) == 1
        assert fresh.scalar(select(func.count()).select_from(RiskSession)) == 0
        assert unchanged_financial_state(fresh) is True
        assert "place_live_order" not in (REPO_ROOT / "apps" / "api" / "app" / "execution" / "boundary.py").read_text(encoding="utf-8")
        assert "apply_event" not in (REPO_ROOT / "apps" / "api" / "app" / "execution" / "boundary.py").read_text(encoding="utf-8")
    finally:
        fresh.close()


def test_execution_route_stays_unapproved(client, db):
    live_order_calls.clear()
    assert _run(_body(_dataset(), "exec-route"))["code"] == "VETOED"
    audit_id, body_hash = _decision("exec-route")
    token = login(client)
    response = client.post(
        "/api/paper/executions",
        headers={"x-csrf-token": token},
        json={
            **_event("exec-route", audit_id, body_hash, event_id="route-fill"),
            "occurred_at": AT.isoformat(),
            "paper_approved": True,
            "live_approved": True,
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["applied"] is False
    assert body["paper_approved"] is False
    assert body["live_trading_enabled"] is False
    assert body["fill"] is None
    assert "IGNORED_CALLER_FLAG" in body["reasons"]
    assert live_order_calls == []
    assert PAPER_TRADING_ACTIVE is False
