"""Risk ledger, gates, and paper state machine. No broker calls."""

from datetime import date, datetime, timezone
from decimal import Decimal
import threading

import pytest
from sqlalchemy import func, select

from app.config.loader import load_defaults
from app.config.schemas import RiskConfig
from app.db import get_session_factory
from app.domain.tables import AuditEvent, PaperTransition, RiskEvent
from app.execution.orders import live_order_calls
import app.execution.paper as paper
from app.execution.paper import PaperTransitionError, current_state, open_intent, submit_paper, transition
from app.options.proposal import build_research_proposal
from app.risk.accounting import session_pnl, unrealized_mark
from app.risk.gates import evaluate
from app.risk.ledger import apply_event, open_session, read_session, set_kill_switch
from app.risk.review import review_proposal
from app.risk.sizing import size_position
from app.settings import REPO_ROOT

DAY = date(2026, 10, 14)
AT = datetime(2026, 10, 14, 4, 30, tzinfo=timezone.utc)


def _config(**updates) -> RiskConfig:
    risk = load_defaults(REPO_ROOT / "config" / "defaults.yaml").risk
    return risk.model_copy(update=updates)


def _session():
    return get_session_factory()()


def _event(event_id: str, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "event_type": "RESERVE",
        "occurred_at": AT,
        "session_date": DAY,
        "intent_id": "intent-1",
        "amount_inr": "700",
        "quantity": "50",
        "underlying": "NIFTY",
        "expiry": "2026-10-20",
        "strike": "25000",
        "option_type": "CE",
        "provenance": "CONFIGURED_INPUT",
    }
    payload.update(overrides)
    return payload


def test_missing_capital_does_not_invent_cash_and_duplicate_events_do_not_apply(db):
    session = _session()
    open_session(session, DAY, _config())
    first = apply_event(session, _event("evt-1"), _config())
    assert first["applied"] is False
    assert first["detail"] == "FUNDS_UNAVAILABLE"
    assert first["paper_approved"] is False
    assert Decimal(first["state"]["reserved_inr"]) == 0
    assert first["state"]["paper_cash_inr"] is None
    again = apply_event(session, _event("evt-1"), _config())
    assert again["detail"] == "DUPLICATE_EVENT"
    assert again["applied"] is False
    conflict = apply_event(session, _event("evt-1", amount_inr="701"), _config())
    assert conflict["detail"] == "DUPLICATE_EVENT_CONFLICT"
    assert Decimal(read_session(session, DAY)["reserved_inr"]) == 0
    session.close()


def test_invalid_identity_and_quantity_write_nothing(db):
    session = _session()
    open_session(session, DAY, _config())
    assert apply_event(session, _event(""), _config())["detail"] == "INVALID_EVENT_ID"
    assert apply_event(session, _event("evt-bad", quantity=-1), _config())["detail"] == "INVALID_QUANTITY"
    assert apply_event(session, _event("evt-synth", provenance="SYNTHETIC_FIXTURE"), _config())["detail"] == "PROVENANCE_REJECTED"
    assert session.scalar(select(func.count()).select_from(RiskEvent)) == 0
    session.close()


def test_second_reservation_sees_the_first(db):
    config = _config(risk_capital_inr=1000)
    session = _session()
    open_session(session, DAY, config)
    session.close()
    barrier = threading.Barrier(2)
    results = []

    def worker(event_id: str, intent_id: str) -> None:
        local = _session()
        barrier.wait()
        try:
            results.append(apply_event(local, _event(event_id, intent_id=intent_id), config))
        finally:
            local.close()

    threads = [
        threading.Thread(target=worker, args=("evt-a", "intent-a")),
        threading.Thread(target=worker, args=("evt-b", "intent-b")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    applied = [item for item in results if item["applied"]]
    refused = [item for item in results if item["detail"] == "INSUFFICIENT_PAPER_CASH"]
    assert len(applied) == 1
    assert len(refused) == 1
    check = _session()
    assert Decimal(read_session(check, DAY)["reserved_inr"]) == Decimal("700")
    check.close()


def test_lockout_survives_a_new_session_and_a_date_change_does_not_clear_it(db):
    config = _config()
    session = _session()
    open_session(session, DAY, config)
    applied = apply_event(
        session,
        _event(
            "lock-1",
            event_type="LOCKOUT_SET",
            amount_inr=None,
            quantity=None,
            intent_id=None,
            provenance="OPERATOR_ACTION",
            reason="session loss",
            config_revision=1,
        ),
        config,
    )
    assert applied["applied"] is True
    session.close()
    reopened = _session()
    assert read_session(reopened, DAY)["lockout_active"] is True
    refused = apply_event(
        reopened,
        _event(
            "lock-2",
            event_type="LOCKOUT_CLEAR",
            amount_inr=None,
            quantity=None,
            intent_id=None,
            provenance="LEDGER",
            reason="SESSION_DATE_CHANGED",
        ),
        config,
    )
    assert refused["detail"] == "CALENDAR_NOT_AUTHORITATIVE"
    assert read_session(reopened, DAY)["lockout_active"] is True
    reopened.close()


def test_unconfigured_gates_veto_and_kill_switch_blocks_entries_only(db):
    session = _session()
    set_kill_switch(session, True, actor="operator", reason="halt entries")
    entry = evaluate({"mode": "PAPER", "intent_purpose": "ENTRY", "session_date": DAY.isoformat()}, session=session)
    assert entry["result"] == "VETO"
    assert entry["passed"] is False
    assert entry["decision"] == "NO_TRADE"
    assert entry["executable"] is False
    assert "KILL_SWITCH" in entry["reasons"]
    assert "FUNDS_UNAVAILABLE" in entry["reasons"]
    assert "CALENDAR_NOT_EVALUATED" in entry["reasons"]
    assert "LIQUIDITY_FLOORS_NOT_CONFIGURED" in entry["reasons"]
    assert "RECONCILIATION_UNAVAILABLE" in entry["reasons"]
    assert "CHARGES_UNVERIFIED" in entry["reasons"]
    assert "SESSION_PNL_UNAVAILABLE" in entry["reasons"]
    names = {gate["name"]: gate for gate in entry["gates"]}
    assert names["liquidity_floors"]["state"] == "NOT_CONFIGURED"
    assert names["liquidity_floors"]["blocks"] is True
    assert names["reconciliation"]["state"] == "NOT_CONFIGURED"
    assert names["funds"]["state"] == "UNAVAILABLE"
    assert names["expected_net"]["state"] == "UNAVAILABLE"
    assert names["calendar"]["state"] == "NOT_EVALUATED"
    assert names["drawdown_lockout"]["state"] == "NOT_CONFIGURED"
    assert names["drawdown_lockout"]["blocks"] is False
    assert all(
        gate["blocks"] is True
        for gate in entry["gates"]
        if gate["state"] in {"UNAVAILABLE", "NOT_EVALUATED"} or (gate["state"] == "NOT_CONFIGURED" and gate["name"] != "drawdown_lockout")
    )
    exit_intent = evaluate({"mode": "PAPER", "intent_purpose": "EXIT"}, session=session)
    assert "KILL_SWITCH" not in exit_intent["reasons"]
    assert "NO_KNOWN_POSITION" in exit_intent["reasons"]
    assert exit_intent["paper_approved"] is False
    assert exit_intent["live_approved"] is False
    session.close()


def test_lot_count_below_one_is_no_trade_and_missing_charges_stay_missing():
    small = size_position(ask="122", lot_size="65", charges_per_lot="20", risk_capital="10000", max_risk_fraction_per_trade="0.01")
    assert small["decision"] == "NO_TRADE"
    assert small["lot_count"] == 0
    assert small["quantity"] is None
    assert small["reasons"] == ["LOT_COUNT_BELOW_ONE"]
    missing = size_position(ask="122", lot_size="65", charges_per_lot=None, risk_capital=None, max_risk_fraction_per_trade="0.01")
    assert missing["lot_count"] is None
    assert "MISSING_CHARGES" in missing["reasons"]
    assert "MISSING_RISK_CAPITAL" in missing["reasons"]
    assert missing["paper_approved"] is False


def test_paper_mode_cannot_submit_or_fill_and_illegal_transitions_are_audited(db):
    live_order_calls.clear()
    session = _session()
    opened = open_intent(session, "paper-1", occurred_at=AT)
    assert opened["state"] == "PROPOSED"
    assert opened["executable"] is False
    with pytest.raises(PaperTransitionError) as caught:
        transition(session, "paper-1", "FILLED", occurred_at=AT, reason="skip")
    assert caught.value.code == "ILLEGAL_TRANSITION"
    assert current_state(session, "paper-1") == "PROPOSED"
    assert session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "paper.illegal_transition")) == 1
    blocked = transition(session, "paper-1", "RISK_APPROVED", occurred_at=AT, reason="submit", risk_passed=True)
    assert blocked["detail"] == "RISK_NOT_PASSED"
    assert blocked["applied"] is False
    assert blocked["live_routed"] is False
    assert current_state(session, "paper-1") == "PROPOSED"
    vetoed = transition(session, "paper-1", "VETOED", occurred_at=AT, reason="risk veto")
    assert vetoed["state"] == "VETOED"
    submission = submit_paper({"intent_id": "paper-1"})
    assert submission["status"] == "UNAVAILABLE"
    assert submission["fill"] is None
    assert submission["market_fill"] is False
    assert live_order_calls == []
    assert paper.PAPER_TRADING_ACTIVE is False
    source = open(paper.__file__, encoding="utf-8").read()
    assert "place_live_order" not in source
    assert "groww" not in source.lower()
    session.close()


def test_research_proposal_does_not_become_executable(db):
    live_order_calls.clear()
    proposal = build_research_proposal(
        {"horizon": "M15", "promotion_state": "APPROVED_FOR_RESEARCH", "is_qualitative": False, "p_up": 0.6},
        {
            "origin": "UNVERIFIED_MARKET_INPUT",
            "underlying": "NIFTY",
            "option_type": "CE",
            "strike": 25000,
            "expiry": "2026-10-20",
            "underlying_price": 25100.5,
            "bid": 120.5,
            "ask": 122.0,
            "quote_timestamp": "2026-10-14T10:00:00+05:30",
            "greeks": {"delta": None, "gamma": None, "theta": None, "vega": None},
            "volatility": {"value": 12.5, "scale": "PERCENT"},
        },
        task_horizon="M15",
    )
    session = _session()
    reviewed = review_proposal(proposal, session=session)
    assert reviewed["executable"] is False
    assert reviewed["order_created"] is False
    assert reviewed["decision"] == "NO_TRADE"
    assert "RESEARCH_PROPOSAL_NOT_AN_ORDER" in reviewed["reasons"]
    assert reviewed["paper_approved"] is False
    assert reviewed["live_approved"] is False
    assert reviewed["forecast_ready"] is False
    assert reviewed["real_market_data_verified"] is False
    assert proposal["executable"] is False
    assert session.scalar(select(func.count()).select_from(PaperTransition)) == 0
    assert live_order_calls == []
    session.close()


def test_release_cannot_consume_another_reservation_or_precede_its_reserve(db):
    config = _config(risk_capital_inr=1000)
    session = _session()
    open_session(session, DAY, config)
    assert apply_event(session, _event("res-a", intent_id="intent-a", amount_inr="400"), config)["applied"] is True
    assert apply_event(session, _event("res-b", intent_id="intent-b", amount_inr="300"), config)["applied"] is True
    early = apply_event(
        session,
        _event("rel-early", event_type="RELEASE", intent_id="intent-a", amount_inr="400", occurred_at=AT.replace(minute=29)),
        config,
    )
    assert early["detail"] == "RELEASE_OUT_OF_ORDER"
    assert Decimal(read_session(session, DAY)["reserved_inr"]) == Decimal("700")
    released = apply_event(session, _event("rel-a", event_type="RELEASE", intent_id="intent-a", amount_inr="400"), config)
    assert released["applied"] is True
    again = apply_event(session, _event("rel-a2", event_type="RELEASE", intent_id="intent-a", amount_inr="400"), config)
    assert again["detail"] == "RESERVATION_NOT_FOUND"
    state = read_session(session, DAY)
    assert Decimal(state["reserved_inr"]) == Decimal("300")
    assert Decimal(state["open_premium_at_risk_inr"]) == 0
    assert Decimal(state["paper_cash_inr"]) == Decimal("1000")
    assert state["session_pnl_inr"] is None
    assert state["charges_booked_inr"] is None
    assert apply_event(session, _event("neg", amount_inr="-1"), config)["detail"] == "INVALID_AMOUNT"
    assert apply_event(session, _event("nan", amount_inr="NaN"), config)["detail"] == "INVALID_AMOUNT"
    later = AT.replace(hour=5)
    assert apply_event(session, _event("res-a2", intent_id="intent-a", amount_inr="400", occurred_at=later), config)["applied"] is True
    between = apply_event(
        session,
        _event("rel-between", event_type="RELEASE", intent_id="intent-a", amount_inr="400", occurred_at=AT.replace(minute=45)),
        config,
    )
    assert between["detail"] == "RELEASE_OUT_OF_ORDER"
    assert Decimal(read_session(session, DAY)["reserved_inr"]) == Decimal("700")
    assert apply_event(session, _event("rel-a3", event_type="RELEASE", intent_id="intent-a", amount_inr="400", occurred_at=later), config)["applied"] is True

    class _NoBuffer:
        risk_capital_inr = 1000
        cash_buffer_fraction = None

    refused = apply_event(session, _event("no-buffer", intent_id="intent-c", amount_inr="100"), _NoBuffer())
    assert refused["detail"] == "MISSING_CASH_BUFFER"
    assert refused["applied"] is False
    session.close()


def test_unknown_pnl_and_missing_charges_are_not_zero():
    unknown = session_pnl(realized_pnl=None, unrealized_mark_value=None, charges_booked=None, exit_charges=None)
    assert unknown["status"] == "UNAVAILABLE"
    assert unknown["value"] is None
    fresh = unrealized_mark(bid="8", average_entry_ask="10", filled_quantity="50", bid_fresh=True)
    assert fresh["value"] == Decimal("-100")
    stale = unrealized_mark(bid="8", average_entry_ask="10", filled_quantity="50", bid_fresh=False)
    assert stale["label"] == "FULL_PREMIUM_LOSS"
    assert stale["value"] == Decimal("-500")
    dead = unrealized_mark(bid=None, average_entry_ask="10", filled_quantity="50", bid_fresh=False)
    assert dead["label"] == "FULL_PREMIUM_LOSS"
    assert dead["value"] == Decimal("-500")
    combined = session_pnl(realized_pnl="0", unrealized_mark_value=fresh["value"], charges_booked="15", exit_charges="15")
    assert combined["value"] == Decimal("-130")
    omitted = session_pnl(realized_pnl="0", unrealized_mark_value="0", charges_booked=None, exit_charges="0")
    assert omitted["value"] is None
    assert "MISSING_CHARGES_BOOKED" in omitted["reasons"]


def test_prohibited_paper_transitions_and_tampered_proposal_flags(db):
    session = _session()
    open_intent(session, "paper-2", occurred_at=AT)
    for target in ("SUBMITTED", "CLOSED", "FILLED"):
        with pytest.raises(PaperTransitionError):
            transition(session, "paper-2", target, occurred_at=AT, reason="skip")
    assert current_state(session, "paper-2") == "PROPOSED"
    proposal = {"schema_version": "m8-proposal-1", "paper_approved": True, "live_approved": True, "executable": True, "status": "INCOMPLETE"}
    reviewed = review_proposal(proposal, session=session)
    assert reviewed["executable"] is False
    assert reviewed["paper_approved"] is False
    assert reviewed["live_approved"] is False
    assert reviewed["simulated_fill"] is None
    assert reviewed["market_fill"] is False
    assert "APPROVAL_FLAG_IGNORED" in reviewed["reasons"]
    assert proposal["paper_approved"] is True
    session.close()


def test_each_session_date_keeps_its_own_reservation(db):
    config = _config(risk_capital_inr=10000)
    later = date(2026, 10, 15)
    session = _session()
    open_session(session, DAY, config)
    open_session(session, later, config)
    assert apply_event(session, _event("day-1", amount_inr="100"), config)["applied"] is True
    second = apply_event(session, _event("day-2", intent_id="intent-2", session_date=later, amount_inr="150"), config)
    assert second["applied"] is True
    assert second["detail"] == "RESERVED"
    assert Decimal(read_session(session, DAY)["reserved_inr"]) == Decimal("100")
    assert Decimal(read_session(session, later)["reserved_inr"]) == Decimal("150")
    for day in (DAY, later):
        state = read_session(session, day)
        assert Decimal(state["paper_cash_inr"]) == Decimal("10000")
        assert Decimal(state["open_premium_at_risk_inr"]) == 0
        assert state["local_open_positions"] == 0
        assert state["session_pnl_inr"] is None
    refused = apply_event(
        session,
        _event("fill-1", event_type="FILL", intent_id="intent-3", session_date=later, amount_inr="10"),
        config,
    )
    assert refused["applied"] is False
    assert refused["detail"] == "INVALID_EVENT_TYPE"
    assert Decimal(read_session(session, later)["reserved_inr"]) == Decimal("150")
    session.close()


def test_caller_owned_ledger_transaction_is_invisible_until_commit(db):
    from sqlalchemy import func, select

    from app.domain.tables import RiskEvent, RiskSession
    from app.risk.ledger import reservation_release_for_fill

    owner = _session()
    try:
        opened = open_session(owner, DAY, _config(risk_capital_inr=1000), commit=False)
        assert opened["paper_cash_inr"] == "1000"
        reserved = apply_event(owner, _event("held", amount_inr="10"), _config(risk_capital_inr=1000), commit=False)
        assert reserved["applied"] is True
        other = _session()
        try:
            assert other.scalar(select(func.count()).select_from(RiskSession)) == 0
            assert other.scalar(select(func.count()).select_from(RiskEvent)) == 0
        finally:
            other.close()
        owner.rollback()
    finally:
        owner.close()
    check = _session()
    try:
        assert check.scalar(select(func.count()).select_from(RiskSession)) == 0
        assert check.scalar(select(func.count()).select_from(RiskEvent)) == 0
    finally:
        check.close()
    partial = reservation_release_for_fill(reserved_inr="100", charges_inr="1", order_quantity="10", filled_quantity="4")
    assert partial["persisted"] is False
    assert partial["release_inr"] is None
    assert "PARTIAL_RELEASE_UNDEFINED" in partial["reasons"]
    unknown = reservation_release_for_fill(reserved_inr="100", charges_inr=None, order_quantity="10", filled_quantity="10")
    assert unknown["release_inr"] is None
    assert "CHARGES_UNKNOWN" in unknown["reasons"]
    full = reservation_release_for_fill(reserved_inr="100", charges_inr="1", order_quantity="10", filled_quantity="10")
    assert full["applied"] is False
    assert full["persisted"] is False
    assert full["release_inr"] == "100"
    assert full["reasons"] == ["FILL_NOT_PERSISTED"]
    assert full["fill"] is None


def test_replay_cannot_trade_and_persistence_failure_is_not_a_pass():
    missing = evaluate({"mode": "PAPER", "intent_purpose": "ENTRY"}, session=None)
    assert missing["result"] == "VETO"
    assert "PERSISTENCE_UNAVAILABLE" in missing["reasons"]
    replay = evaluate({"mode": "REPLAY", "intent_purpose": "ENTRY"}, session=None)
    assert "REPLAY_CANNOT_TRADE" in replay["reasons"]
    assert replay["passed"] is False
