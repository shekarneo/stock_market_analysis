"""Paper simulation records vetoes and does not place a broker order."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.db import get_session_factory
from app.domain.tables import AuditEvent, OpsState, PaperTransition, RiskEvent, RiskSession
from app.execution.orders import live_order_calls
from app.execution.paper import PAPER_TRADING_ACTIVE, PaperTransitionError, current_state, open_intent, transition
from app.execution.simulation import reconcile_intent, replay_simulation_decision, run_paper_simulation, session_loop_status, simulated_execution_price
from app.features.pipeline import build_dataset
from app.market.fixtures import fixture_calendar
from app.risk.accounting import session_pnl, unrealized_mark
from app.risk.ledger import open_session, read_session
from app.settings import REPO_ROOT
from tests.conftest import login
from tests.test_history import bars
from tests.test_risk_ledger import DAY, _config

AT = datetime(2026, 10, 14, 4, 30, tzinfo=timezone.utc)


def _dataset():
    built = build_dataset(bars(25), fixture_calendar())
    assert built.ok
    return built.artifact


def _body(dataset: dict, intent_id: str, **extra) -> dict:
    payload = {
        "confirm": True,
        "intent_id": intent_id,
        "occurred_at": AT,
        "session_date": "2026-10-14",
        "mode": "PAPER",
        "underlying": "NIFTY",
        "expiry": "2026-10-16",
        "strike": "22500",
        "option_type": "CE",
        "dataset": dataset,
        "forecast": {"promotion_state": "TRAINED"},
    }
    payload.update(extra)
    return payload


def _run(body: dict) -> dict:
    session = get_session_factory()()
    try:
        return run_paper_simulation(session, body, actor="tester")
    finally:
        session.close()


def test_synthetic_proposal_is_vetoed_without_a_fill_or_broker_call(db):
    live_order_calls.clear()
    result = _run(_body(_dataset(), "sim-valid"))
    assert result["completed"] is True
    assert result["code"] == "VETOED"
    assert result["state"] == "VETOED"
    assert result["decision"] == "NO_TRADE"
    assert "MODEL_NOT_APPROVED" in result["reasons"]
    assert result["simulated_fill"] is None
    assert result["fill"] is None
    assert result["broker_called"] is False
    assert result["forecast_ready"] is False
    assert result["paper_approved"] is False
    assert result["live_approved"] is False
    assert result["real_market_data_verified"] is False
    assert result["live_trading_enabled"] is False
    assert live_order_calls == []
    session = get_session_factory()()
    assert current_state(session, "sim-valid") == "VETOED"
    assert session.scalar(select(func.count()).select_from(RiskEvent).where(RiskEvent.intent_id == "sim-valid")) == 0
    session.close()


def test_quarantine_missing_lineage_and_incomplete_contracts_are_rejected(db):
    record = json.loads(
        (REPO_ROOT / "var" / "history" / "quarantine" / "0105c2cfde527068e24b576e089b4dabfccda734fd20167ae28419a3e2e98057.json").read_text(
            encoding="utf-8"
        )
    )
    quarantined = _run(_body(record, "sim-quarantine"))
    assert quarantined["code"] == "QUARANTINE_REJECTED"
    assert quarantined["simulated_fill"] is None
    altered = _dataset()
    altered["source_candles"][0]["close"] = altered["source_candles"][0]["close"] + 1
    mismatched = _run(_body(altered, "sim-lineage"))
    assert mismatched["code"] == "LINEAGE_MISMATCH"
    missing = _run(_body({}, "sim-missing-lineage"))
    assert missing["code"] == "LINEAGE_MISSING"
    incomplete = _run(_body(_dataset(), "sim-contract", strike=None))
    assert incomplete["code"] == "INCOMPLETE_CONTRACT"
    assert "MISSING_STRIKE" in incomplete["reasons"]
    session = get_session_factory()()
    assert current_state(session, "sim-quarantine") is None
    assert current_state(session, "sim-contract") is None
    assert session.scalar(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.entity == "paper_intent:sim-quarantine", AuditEvent.action == "paper.simulation_request")
    ) == 0
    session.close()


def test_risk_limits_missing_inputs_fills_duplicates_and_ledger(db):
    limited = _run(
        _body(
            _dataset(),
            "sim-limit",
            quote={"bid": "100", "ask": "10000", "quote_timestamp": AT.isoformat()},
            lot_size="65",
            charges_per_lot="1",
        )
    )
    assert limited["code"] == "VETOED"
    assert "CHARGES_UNVERIFIED" in limited["reasons"]
    assert "MISSING_RISK_CAPITAL" in limited["reasons"]
    missing_inputs = _run(_body(_dataset(), "sim-missing-inputs"))
    assert "FUNDS_UNAVAILABLE" in missing_inputs["reasons"]
    assert missing_inputs["simulated_fill"] is None
    priced = simulated_execution_price(side="BUY", bid="100", ask="102", haircut="half_spread", extra_tick_penalty=False)
    assert priced["reason"] == "BUY_AT_ASK"
    assert priced["price"] == "102"
    assert priced["fill_recorded"] is False
    sold = simulated_execution_price(side="SELL", bid="100", ask="102", haircut="half_spread", extra_tick_penalty=False)
    assert sold["reason"] == "SELL_AT_BID_MINUS_HALF_SPREAD"
    assert Decimal(sold["price"]) == Decimal("99")
    unavailable = simulated_execution_price(side="BUY", bid=None, ask=None, haircut="half_spread", extra_tick_penalty=False)
    assert unavailable["price"] is None
    assert unavailable["reason"] == "MISSING_ASK"
    session = get_session_factory()()
    try:
        opened = open_session(session, DAY, _config(risk_capital_inr=100000))
        before = read_session(session, DAY)["paper_cash_inr"]
        vetoed = _run(_body(_dataset(), "sim-ledger"))
        assert vetoed["state"] == "VETOED"
        assert read_session(session, DAY)["paper_cash_inr"] == before
        assert session.scalar(select(func.count()).select_from(RiskEvent).where(RiskEvent.intent_id == "sim-ledger")) == 0
        with pytest.raises(PaperTransitionError):
            transition(session, "sim-ledger", "FILLED", occurred_at=AT, reason="skip")
        assert current_state(session, "sim-ledger") == "VETOED"
        again = _run(_body(_dataset(), "sim-ledger"))
        assert again["code"] == "VETOED"
        assert again["simulated_fill"] is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(PaperTransition)
                .where(PaperTransition.intent_id == "sim-ledger", PaperTransition.applied.is_(True))
            )
            == 2
        )
        report = reconcile_intent(session, "sim-ledger")
        assert report["consistent"] is True
        assert report["applied_fills"] == 0
        assert report["broker_orders"] == 0
        assert report["pnl"]["value"] is None
        mark = unrealized_mark(bid="90", average_entry_ask="100", filled_quantity="1", bid_fresh=True)
        combined = session_pnl(realized_pnl="0", unrealized_mark_value=mark["value"], charges_booked=None, exit_charges="0")
        assert combined["value"] is None
        assert Decimal(opened["paper_cash_inr"]) == Decimal("100000")
    finally:
        session.close()
    loop = session_loop_status()
    assert loop["ran"] is False
    assert "HOLIDAY_CALENDAR_UNCONFIGURED" in loop["reasons"]
    assert "place_live_order" not in (REPO_ROOT / "apps" / "api" / "app" / "execution" / "simulation.py").read_text(encoding="utf-8")


def test_shipped_simulation_veto_reasons_and_supplied_inputs_still_fail(db):
    """Document the exact blockers. Supplied test inputs are not stored evidence."""
    default = _run(_body(_dataset(), "sim-blockers"))
    assert default["code"] == "VETOED"
    assert default["simulated_fill"] is None
    assert default["reasons"] == [
        "MASTER_NOT_TRADABLE",
        "CALENDAR_NOT_EVALUATED",
        "MISSING_QUOTE",
        "MISSING_MASTER",
        "MODEL_NOT_APPROVED",
        "FUNDS_UNAVAILABLE",
        "CHARGES_UNVERIFIED",
        "MISSING_ASK",
        "MISSING_LOT_SIZE",
        "MISSING_RISK_CAPITAL",
        "SESSION_PNL_UNAVAILABLE",
        "LIQUIDITY_FLOORS_NOT_CONFIGURED",
        "EXPECTED_NET_UNAVAILABLE",
        "MISSING_ENTRY_PLAN",
        "RECONCILIATION_UNAVAILABLE",
    ]
    quoted = _run(
        _body(
            _dataset(),
            "sim-quote-without-clock",
            quote={"bid": "100", "ask": "102", "quote_timestamp": AT.isoformat()},
        )
    )
    assert quoted["code"] == "VETOED"
    assert "MISSING_QUOTE" not in quoted["reasons"]
    assert "MISSING_QUOTE_TIME" not in quoted["reasons"]
    assert "STALE_QUOTE" not in quoted["reasons"]
    assert "MODEL_NOT_APPROVED" in quoted["reasons"]
    assert quoted["simulated_fill"] is None
    session = get_session_factory()()
    try:
        from app.config.loader import load_defaults
        from app.market.calendar import CalendarAssessment, CalendarState
        from app.risk.gates import evaluate
        from app.risk.ledger import set_kill_switch

        set_kill_switch(session, False, actor="tester", reason="audit")
        capital = load_defaults(REPO_ROOT / "config" / "defaults.yaml").risk.model_copy(update={"risk_capital_inr": 1000000})
        opened = open_session(session, DAY, capital)
        master = {
            "underlying": "NIFTY",
            "expiry": "2026-10-16",
            "strike": "22500",
            "option_type": "CE",
            "lot_size": "65",
            "tick_size": "0.05",
            "buy_allowed": True,
        }
        supplied = evaluate(
            {
                "mode": "PAPER",
                "intent_purpose": "ENTRY",
                "session_date": "2026-10-14",
                "forecast": {"promotion_state": "APPROVED_FOR_PAPER", "model_health": "HEALTHY"},
                "expected_net": "1",
                "ask": "102",
                "lot_size": "65",
                "charges_per_lot": "20",
                "quote": {"bid": "100", "ask": "102", "quote_timestamp": AT.isoformat()},
                "entry_plan": {"entry_trigger": "t", "invalidation": "i", "exit_plan": "e", "time_stop": "s"},
                **master,
                "master": master,
            },
            session=session,
            config=capital,
            calendar=CalendarAssessment(state=CalendarState.LISTED_SESSION, authoritative=True, limitation="caller"),
            as_of=AT,
        )
        assert supplied["passed"] is False
        assert supplied["result"] == "VETO"
        assert supplied["decision"] == "NO_TRADE"
        assert supplied["reasons"] == [
            "CALENDAR_NOT_AUTHORITATIVE",
            "TICK_UNIT_UNVERIFIED",
            "MODEL_NOT_APPROVED",
            "FUNDS_REQUIREMENT_UNAVAILABLE",
            "CHARGES_UNVERIFIED",
            "SESSION_PNL_UNAVAILABLE",
            "LIQUIDITY_FLOORS_NOT_CONFIGURED",
            "RECONCILIATION_UNAVAILABLE",
        ]
        assert supplied["forecast_ready"] is False
        assert supplied["paper_approved"] is False
        assert supplied["live_approved"] is False
        assert supplied["real_market_data_verified"] is False
        assert Decimal(read_session(session, DAY)["paper_cash_inr"]) == Decimal(opened["paper_cash_inr"])
    finally:
        session.close()


def test_kill_switch_entry_plan_and_quote_time_stay_inside_the_other_gates(db):
    from datetime import timedelta

    from app.execution.paper import PAPER_TRADING_ACTIVE
    from app.risk.gates import evaluate
    from app.risk.ledger import set_kill_switch

    unread_session = get_session_factory()()
    try:
        unread = evaluate({"mode": "PAPER", "intent_purpose": "ENTRY", "underlying": "NIFTY", "option_type": "CE"}, session=unread_session)
    finally:
        unread_session.close()
    assert unread["passed"] is False
    assert "KILL_SWITCH_NOT_READ" in unread["reasons"]
    assert "MISSING_FORECAST" in unread["reasons"]
    assert "RECONCILIATION_UNAVAILABLE" in unread["reasons"]

    plan = {"entry_trigger": "touch", "invalidation": "below", "exit_plan": "sell", "time_stop": "session"}
    session = get_session_factory()()
    try:
        set_kill_switch(session, False, actor="tester", reason="explicit off")
        off = _run(_body(_dataset(), "sim-switch-off", entry_plan=plan, quote={"bid": "100", "ask": "102", "quote_timestamp": AT.isoformat()}))
        assert off["code"] == "VETOED"
        assert "KILL_SWITCH" not in off["reasons"]
        assert "KILL_SWITCH_NOT_READ" not in off["reasons"]
        assert "MISSING_ENTRY_PLAN" not in off["reasons"]
        assert "MISSING_QUOTE_TIME" not in off["reasons"]
        assert "STALE_QUOTE" not in off["reasons"]
        assert "MODEL_NOT_APPROVED" in off["reasons"]
        assert "CHARGES_UNVERIFIED" in off["reasons"]
        assert "RECONCILIATION_UNAVAILABLE" in off["reasons"]
        assert off["simulated_fill"] is None
        assert off["paper_approved"] is False
        assert off["live_trading_enabled"] is False

        set_kill_switch(session, True, actor="tester", reason="explicit on")
        halted = _run(_body(_dataset(), "sim-switch-on", entry_plan=plan))
        assert "KILL_SWITCH" in halted["reasons"]
        assert "MODEL_NOT_APPROVED" in halted["reasons"]
        assert halted["simulated_fill"] is None
        assert session.scalar(select(func.count()).select_from(RiskEvent).where(RiskEvent.intent_id == "sim-switch-on")) == 0
    finally:
        session.close()

    missing_plan = _run(_body(_dataset(), "sim-plan-missing"))
    assert "MISSING_ENTRY_PLAN" in missing_plan["reasons"]
    assert "MODEL_NOT_APPROVED" in missing_plan["reasons"]
    blank_plan = _run(_body(_dataset(), "sim-plan-blank", entry_plan={**plan, "time_stop": "  "}))
    assert "MISSING_ENTRY_PLAN" in blank_plan["reasons"]
    assert "FUNDS_UNAVAILABLE" in blank_plan["reasons"]
    partial = _run(_body(_dataset(), "sim-plan-partial", entry_plan={"entry_trigger": "touch"}))
    assert "MISSING_ENTRY_PLAN" in partial["reasons"]
    assert partial["simulated_fill"] is None

    missing_time = _run(_body(_dataset(), "sim-quote-missing-time", quote={"bid": "100", "ask": "102"}))
    assert "MISSING_QUOTE_TIME" in missing_time["reasons"]
    invalid_time = _run(_body(_dataset(), "sim-quote-invalid-time", quote={"bid": "100", "ask": "102", "quote_timestamp": "yesterday"}))
    assert "MISSING_QUOTE_TIME" in invalid_time["reasons"]
    naive_time = _run(_body(_dataset(), "sim-quote-naive-time", quote={"bid": "100", "ask": "102", "quote_timestamp": "2026-10-14T04:30:00"}))
    assert "MISSING_QUOTE_TIME" in naive_time["reasons"]
    stale = _run(
        _body(
            _dataset(),
            "sim-quote-stale",
            quote={"bid": "100", "ask": "102", "quote_timestamp": (AT - timedelta(seconds=16)).isoformat()},
        )
    )
    assert "STALE_QUOTE" in stale["reasons"]
    assert "MODEL_NOT_APPROVED" in stale["reasons"]
    assert stale["forecast_ready"] is False
    assert stale["live_approved"] is False
    assert stale["real_market_data_verified"] is False
    assert PAPER_TRADING_ACTIVE is False


def test_paper_simulation_route_requires_confirmation_and_stays_unapproved(client):
    token = login(client)
    denied = client.post("/api/paper/simulations", headers={"x-csrf-token": token}, json={"intent_id": "api-1", "occurred_at": AT.isoformat(), "confirm": False})
    assert denied.status_code == 422
    assert denied.json()["code"] == "CONFIRMATION_REQUIRED"
    assert denied.json()["paper_approved"] is False
    assert denied.json()["live_trading_enabled"] is False
    assert denied.json()["broker_called"] is False
    invalid_plan = client.post(
        "/api/paper/simulations",
        headers={"x-csrf-token": token},
        json={
            "confirm": True,
            "intent_id": "api-plan",
            "occurred_at": AT.isoformat(),
            "entry_plan": {"entry_trigger": 1, "invalidation": "i", "exit_plan": "e", "time_stop": "s"},
        },
    )
    assert invalid_plan.status_code == 422
    assert invalid_plan.json().get("simulated_fill") is None


_PLAN = {"entry_trigger": "touch", "invalidation": "below", "exit_plan": "sell", "time_stop": "session"}
_QUARANTINE = {
    "0105c2cfde527068e24b576e089b4dabfccda734fd20167ae28419a3e2e98057.json": "40ec5199e8a5f1059ce941d04a1a60ef15af6973286354ca1d8ecb7224f79075",
    "5edd4d3543825aa3a385092b9d16b3938e5995e026cbf3b2ade0872c18414a5d.json": "878e6b0406f83c8009cd0e47f9cd1466662b7125ed06b065ad9c828bca4bea7b",
    "deca6478aa937dd12def145719a883f907f14c3bd52c06ff9a29a75e4f6e796d.json": "fa536f36a429fd165b1ed64a60ee16d83f640625feadcc2d1c77e154347e2cb6",
    "f161aeef9e2846e74a3d200f4507ec3a9948b5d50b528eac227242efe65ec8e8.json": "af2f5a8c73f16b40ed7b7b7744b58acea16264b32c6a6ac338829aa8d48c778e",
}


def _unchanged_book(session) -> None:
    assert session.scalar(select(func.count()).select_from(RiskSession)) == 0
    assert session.scalar(select(func.count()).select_from(RiskEvent)) == 0
    assert session.scalar(
        select(func.count()).select_from(PaperTransition).where(PaperTransition.to_state.in_(("FILLED", "PARTIALLY_FILLED", "CLOSED")), PaperTransition.applied.is_(True))
    ) == 0
    assert live_order_calls == []


def test_absent_kill_switch_is_seeded_then_read(db):
    live_order_calls.clear()
    before = get_session_factory()()
    try:
        assert before.get(OpsState, 1) is None
    finally:
        before.close()
    result = _run(_body(_dataset(), "sim-seed-switch"))
    after = get_session_factory()()
    try:
        row = after.get(OpsState, 1)
        assert row is not None
        assert row.kill_switch is False
        _unchanged_book(after)
    finally:
        after.close()
    assert result["code"] == "VETOED"
    assert "KILL_SWITCH_NOT_READ" not in result["reasons"]
    assert "KILL_SWITCH" not in result["reasons"]
    assert "MODEL_NOT_APPROVED" in result["reasons"]
    assert result["simulated_fill"] is None
    assert result["broker_called"] is False


def test_explicit_kill_switch_on_vetoes_the_entry(db):
    from app.risk.ledger import set_kill_switch

    live_order_calls.clear()
    session = get_session_factory()()
    try:
        set_kill_switch(session, True, actor="tester", reason="halt entries")
        result = _run(_body(_dataset(), "sim-switch-explicit-on", entry_plan=_PLAN))
        row = session.get(OpsState, 1)
        assert row is not None
        assert row.kill_switch is True
        assert session.scalar(select(func.count()).select_from(RiskEvent).where(RiskEvent.intent_id == "sim-switch-explicit-on")) == 0
    finally:
        session.close()
    assert result["code"] == "VETOED"
    assert "KILL_SWITCH" in result["reasons"]
    assert "MODEL_NOT_APPROVED" in result["reasons"]
    assert result["simulated_fill"] is None
    assert result["order_created"] is False
    assert live_order_calls == []


def test_kill_switch_storage_and_read_failures_fail_closed(db, monkeypatch):
    live_order_calls.clear()

    def _unread(session):
        return None

    monkeypatch.setattr("app.risk.gates.read_kill_switch", _unread)
    unread = _run(_body(_dataset(), "sim-switch-unread"))
    assert unread["code"] == "VETOED"
    assert "KILL_SWITCH_NOT_READ" in unread["reasons"]
    assert "MODEL_NOT_APPROVED" in unread["reasons"]
    assert unread["simulated_fill"] is None

    def _broken(session):
        raise RuntimeError("ops_state unreadable")

    monkeypatch.setattr("app.risk.gates.read_kill_switch", _broken)
    broken = _run(_body(_dataset(), "sim-switch-broken"))
    assert broken["code"] == "VETOED"
    assert "KILL_SWITCH_NOT_READ" in broken["reasons"]
    assert "RECONCILIATION_UNAVAILABLE" in broken["reasons"]
    assert broken["simulated_fill"] is None
    assert broken["broker_called"] is False

    def _seed_failed(session, settings):
        raise RuntimeError("ops_state unwritable")

    monkeypatch.setattr("app.execution.simulation.ensure_seed", _seed_failed)
    stored = _run(_body(_dataset(), "sim-switch-unstored"))
    assert stored["code"] == "VETOED"
    assert stored["reasons"] == ["KILL_SWITCH_NOT_READ"]
    assert stored["state"] == "VETOED"
    assert stored["simulated_fill"] is None
    assert stored["broker_called"] is False
    session = get_session_factory()()
    try:
        assert session.scalar(select(func.count()).select_from(RiskEvent)) == 0
        assert live_order_calls == []
    finally:
        session.close()


def test_entry_plan_clears_only_when_all_four_texts_are_present(db):
    assert _body(_dataset(), "unused").get("entry_plan") is None
    default = _run(_body(_dataset(), "sim-plan-default"))
    assert "MISSING_ENTRY_PLAN" in default["reasons"]
    complete = _run(_body(_dataset(), "sim-plan-complete", entry_plan=_PLAN))
    assert "MISSING_ENTRY_PLAN" not in complete["reasons"]
    assert set(complete["reasons"]) == set(default["reasons"]) - {"MISSING_ENTRY_PLAN"}
    assert "MODEL_NOT_APPROVED" in complete["reasons"]
    assert complete["simulated_fill"] is None
    for field in _PLAN:
        partial = _run(_body(_dataset(), f"sim-plan-drop-{field}", entry_plan={key: value for key, value in _PLAN.items() if key != field}))
        assert "MISSING_ENTRY_PLAN" in partial["reasons"]
        assert "FUNDS_UNAVAILABLE" in partial["reasons"]
    blank = _run(_body(_dataset(), "sim-plan-blank-field", entry_plan={**_PLAN, "invalidation": "   "}))
    assert "MISSING_ENTRY_PLAN" in blank["reasons"]
    non_text = _run(_body(_dataset(), "sim-plan-number", entry_plan={**_PLAN, "exit_plan": 1}))
    assert "MISSING_ENTRY_PLAN" in non_text["reasons"]
    assert non_text["simulated_fill"] is None
    assert "CHARGES_UNVERIFIED" in non_text["reasons"]


def test_quote_timestamps_are_judged_against_the_request_clock(db):
    assert datetime.now(timezone.utc) - AT > timedelta(seconds=15)
    fresh = _run(_body(_dataset(), "sim-quote-fresh", quote={"bid": "100", "ask": "102", "quote_timestamp": AT.isoformat()}))
    assert "MISSING_QUOTE" not in fresh["reasons"]
    assert "MISSING_QUOTE_TIME" not in fresh["reasons"]
    assert "STALE_QUOTE" not in fresh["reasons"]
    boundary = _run(
        _body(
            _dataset(),
            "sim-quote-boundary",
            quote={"bid": "100", "ask": "102", "quote_timestamp": (AT - timedelta(seconds=15)).isoformat()},
        )
    )
    assert "STALE_QUOTE" not in boundary["reasons"]
    stale = _run(
        _body(
            _dataset(),
            "sim-quote-age",
            quote={"bid": "100", "ask": "102", "quote_timestamp": (AT - timedelta(seconds=16)).isoformat()},
        )
    )
    assert "STALE_QUOTE" in stale["reasons"]
    missing = _run(_body(_dataset(), "sim-quote-no-stamp", quote={"bid": "100", "ask": "102"}))
    assert "MISSING_QUOTE_TIME" in missing["reasons"]
    naive = _run(_body(_dataset(), "sim-quote-naive", quote={"bid": "100", "ask": "102", "quote_timestamp": "2026-10-14T10:00:00"}))
    assert "MISSING_QUOTE_TIME" in naive["reasons"]
    invalid = _run(_body(_dataset(), "sim-quote-bad", quote={"bid": "100", "ask": "102", "quote_timestamp": "not-a-time"}))
    assert "MISSING_QUOTE_TIME" in invalid["reasons"]
    for result in (fresh, boundary, stale, missing, naive, invalid):
        assert "MODEL_NOT_APPROVED" in result["reasons"]
        assert result["simulated_fill"] is None
        assert result["broker_called"] is False


def test_populated_simulation_clears_only_the_gates_with_inputs(db):
    from app.execution.paper import PAPER_TRADING_ACTIVE

    live_order_calls.clear()
    master = {
        "underlying": "NIFTY",
        "expiry": "2026-10-16",
        "strike": "22500",
        "option_type": "CE",
        "lot_size": "65",
        "tick_size": "0.05",
        "buy_allowed": True,
    }
    result = _run(
        _body(
            _dataset(),
            "sim-populated",
            entry_plan=_PLAN,
            expected_net="1",
            lot_size="65",
            tick_size="0.05",
            charges_per_lot="20",
            forecast={"promotion_state": "APPROVED_FOR_PAPER", "model_health": "HEALTHY"},
            quote={"bid": "100", "ask": "102", "quote_timestamp": AT.isoformat()},
            master=master,
        )
    )
    assert result["code"] == "VETOED"
    assert result["decision"] == "NO_TRADE"
    assert result["reasons"] == [
        "CALENDAR_NOT_EVALUATED",
        "TICK_UNIT_UNVERIFIED",
        "MODEL_NOT_APPROVED",
        "FUNDS_UNAVAILABLE",
        "CHARGES_UNVERIFIED",
        "MISSING_RISK_CAPITAL",
        "SESSION_PNL_UNAVAILABLE",
        "LIQUIDITY_FLOORS_NOT_CONFIGURED",
        # The client's expected_net="1" is not trusted; the server's own EV is unavailable
        "EXPECTED_NET_UNAVAILABLE",
        "RECONCILIATION_UNAVAILABLE",
    ]
    assert result["simulated_fill"] is None
    assert result["fill"] is None
    assert result["order_created"] is False
    assert result["broker_called"] is False
    assert result["forecast_ready"] is False
    assert result["paper_approved"] is False
    assert result["live_approved"] is False
    assert result["real_market_data_verified"] is False
    assert result["live_trading_enabled"] is False
    assert PAPER_TRADING_ACTIVE is False
    loop = session_loop_status()
    assert loop["ran"] is False
    assert loop["entries_created"] == 0
    session = get_session_factory()()
    try:
        _unchanged_book(session)
        assert current_state(session, "sim-populated") == "VETOED"
    finally:
        session.close()


def test_quarantine_records_remain_unverified_provider():
    root = REPO_ROOT / "var" / "history" / "quarantine"
    for name, digest in _QUARANTINE.items():
        path = root / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        record = json.loads(path.read_text(encoding="utf-8"))
        assert record["label"] == "UNVERIFIED_PROVIDER"
        assert record["forecast_ready"] is False
        assert record["paper_approved"] is False
        assert record["live_approved"] is False
        assert record["real_market_data_verified"] is False


def _applied(session, intent_id: str) -> int:
    return session.scalar(
        select(func.count()).select_from(PaperTransition).where(PaperTransition.intent_id == intent_id, PaperTransition.applied.is_(True))
    )


def _safety(session, intent_id: str) -> None:
    _unchanged_book(session)
    assert PAPER_TRADING_ACTIVE is False
    assert session_loop_status()["ran"] is False
    row = current_state(session, intent_id)
    assert row in {None, "PROPOSED", "VETOED"}


def test_normal_evaluation_ends_vetoed(db):
    live_order_calls.clear()
    result = _run(_body(_dataset(), "sim-recover-a"))
    assert result["code"] == "VETOED"
    assert result["state"] == "VETOED"
    assert "MODEL_NOT_APPROVED" in result["reasons"]
    assert result["simulated_fill"] is None
    session = get_session_factory()()
    try:
        assert _applied(session, "sim-recover-a") == 2
        _safety(session, "sim-recover-a")
    finally:
        session.close()


def test_evaluation_exception_leaves_a_recoverable_proposal(db, monkeypatch):
    live_order_calls.clear()
    real = __import__("app.execution.simulation", fromlist=["evaluate"]).evaluate
    calls = {"n": 0}

    def flaky(intent, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("evaluation interrupted")
        return real(intent, **kwargs)

    monkeypatch.setattr("app.execution.simulation.evaluate", flaky)
    body = _body(_dataset(), "sim-recover-b")
    first = _run(body)
    assert first["code"] == "EVALUATION_INTERRUPTED"
    assert first["state"] == "PROPOSED"
    assert first["simulated_fill"] is None
    assert first["fill"] is None
    session = get_session_factory()()
    try:
        assert current_state(session, "sim-recover-b") == "PROPOSED"
        assert _applied(session, "sim-recover-b") == 1
        _safety(session, "sim-recover-b")
    finally:
        session.close()
    recovered = _run(body)
    assert recovered["code"] == "VETOED"
    assert "MODEL_NOT_APPROVED" in recovered["reasons"]
    assert calls["n"] == 2
    session = get_session_factory()()
    try:
        assert current_state(session, "sim-recover-b") == "VETOED"
        assert _applied(session, "sim-recover-b") == 2
        _safety(session, "sim-recover-b")
    finally:
        session.close()


def test_veto_transition_exception_stays_proposed_until_retry(db, monkeypatch):
    live_order_calls.clear()
    real = __import__("app.execution.simulation", fromlist=["transition"]).transition
    calls = {"n": 0}

    def flaky(session, intent_id, to_state, **kwargs):
        if to_state == "VETOED":
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("veto interrupted")
        return real(session, intent_id, to_state, **kwargs)

    monkeypatch.setattr("app.execution.simulation.transition", flaky)
    body = _body(_dataset(), "sim-recover-c")
    first = _run(body)
    assert first["code"] == "VETO_INTERRUPTED"
    assert first["state"] == "PROPOSED"
    assert first["simulated_fill"] is None
    session = get_session_factory()()
    try:
        assert current_state(session, "sim-recover-c") == "PROPOSED"
        assert _applied(session, "sim-recover-c") == 1
        _safety(session, "sim-recover-c")
    finally:
        session.close()
    recovered = _run(body)
    assert recovered["code"] == "VETOED"
    assert "MODEL_NOT_APPROVED" in recovered["reasons"]
    session = get_session_factory()()
    try:
        assert current_state(session, "sim-recover-c") == "VETOED"
        assert _applied(session, "sim-recover-c") == 2
        _safety(session, "sim-recover-c")
    finally:
        session.close()


def test_retry_after_interruption_does_not_duplicate_the_intent(db, monkeypatch):
    live_order_calls.clear()
    real = __import__("app.execution.simulation", fromlist=["evaluate"]).evaluate

    def fail_once(intent, **kwargs):
        fail_once.used = True
        monkeypatch.setattr("app.execution.simulation.evaluate", real)
        raise RuntimeError("evaluation interrupted")

    fail_once.used = False
    monkeypatch.setattr("app.execution.simulation.evaluate", fail_once)
    body = _body(_dataset(), "sim-recover-d")
    assert _run(body)["code"] == "EVALUATION_INTERRUPTED"
    recovered = _run(body)
    assert recovered["code"] == "VETOED"
    assert recovered["broker_called"] is False
    session = get_session_factory()()
    try:
        ids = session.scalars(select(PaperTransition.intent_id).where(PaperTransition.applied.is_(True), PaperTransition.to_state == "PROPOSED")).all()
        assert ids.count("sim-recover-d") == 1
        assert _applied(session, "sim-recover-d") == 2
        _safety(session, "sim-recover-d")
    finally:
        session.close()


def test_repeating_a_completed_veto_adds_no_transition_or_risk_event(db):
    live_order_calls.clear()
    body = _body(_dataset(), "sim-recover-e")
    assert _run(body)["code"] == "VETOED"
    again = _run(body)
    assert again["code"] == "VETOED"
    assert "MODEL_NOT_APPROVED" in again["reasons"]
    assert again["simulated_fill"] is None
    session = get_session_factory()()
    try:
        assert _applied(session, "sim-recover-e") == 2
        _safety(session, "sim-recover-e")
    finally:
        session.close()


def test_conflicting_idempotency_key_is_not_evaluated(db, monkeypatch):
    live_order_calls.clear()
    body = _body(_dataset(), "sim-recover-f")
    assert _run(body)["state"] == "VETOED"

    def forbidden(*args, **kwargs):
        raise AssertionError("conflicting payload must not be evaluated")

    monkeypatch.setattr("app.execution.simulation.evaluate", forbidden)
    conflict = _run(_body(_dataset(), "sim-recover-f", strike="1"))
    assert conflict["code"] == "INPUT_CONFLICT"
    assert conflict["state"] == "VETOED"
    assert conflict["simulated_fill"] is None
    session = get_session_factory()()
    try:
        assert current_state(session, "sim-recover-f") == "VETOED"
        assert _applied(session, "sim-recover-f") == 2
        _safety(session, "sim-recover-f")
    finally:
        session.close()


def test_proposal_without_stored_inputs_fails_closed(db, monkeypatch):
    live_order_calls.clear()

    def forbidden(*args, **kwargs):
        raise AssertionError("missing stored inputs must not be evaluated")

    monkeypatch.setattr("app.execution.simulation.evaluate", forbidden)
    session = get_session_factory()()
    try:
        opened = open_intent(session, "sim-recover-g", occurred_at=AT)
        assert opened["state"] == "PROPOSED"
    finally:
        session.close()
    result = _run(
        _body(
            _dataset(),
            "sim-recover-g",
            quote={"bid": "100", "ask": "101", "timestamp": AT.isoformat()},
            entry_plan={"entry_trigger": "a", "invalidation": "b", "exit_plan": "c", "time_stop": "d"},
        )
    )
    assert result["code"] == "INPUTS_NOT_STORED"
    assert result["reasons"] == ["INPUTS_NOT_STORED"]
    assert result["state"] == "VETOED"
    assert "MODEL_NOT_APPROVED" not in result["reasons"]
    assert result["simulated_fill"] is None
    session = get_session_factory()()
    try:
        assert current_state(session, "sim-recover-g") == "VETOED"
        assert _applied(session, "sim-recover-g") == 2
        _safety(session, "sim-recover-g")
    finally:
        session.close()


_DEFAULT_REASONS = [
    "MASTER_NOT_TRADABLE",
    "CALENDAR_NOT_EVALUATED",
    "MISSING_QUOTE",
    "MISSING_MASTER",
    "MODEL_NOT_APPROVED",
    "FUNDS_UNAVAILABLE",
    "CHARGES_UNVERIFIED",
    "MISSING_ASK",
    "MISSING_LOT_SIZE",
    "MISSING_RISK_CAPITAL",
    "SESSION_PNL_UNAVAILABLE",
    "LIQUIDITY_FLOORS_NOT_CONFIGURED",
    "EXPECTED_NET_UNAVAILABLE",
    "MISSING_ENTRY_PLAN",
    "RECONCILIATION_UNAVAILABLE",
]


def test_replay_reconstructs_the_stored_decision(db):
    live_order_calls.clear()
    dataset = _dataset()
    result = _run(_body(dataset, "sim-audit-a"))
    assert result["reasons"] == _DEFAULT_REASONS
    assert "KILL_SWITCH" not in result["reasons"]
    session = get_session_factory()()
    try:
        replay = replay_simulation_decision(session, "sim-audit-a")
        assert replay["reconstructed"] is True
        assert replay["state"] == "VETOED"
        assert replay["snapshot_conflict"] is False
        assert replay["snapshot_count"] == 1
        assert replay["request_occurred_at"] == AT.isoformat()
        assert replay["quote_timestamp"] is None
        assert "quote_timestamp" in replay["missing"]
        assert "lineage.forecast_model_id" in replay["missing"]
        assert replay["lineage"]["dataset_id"] == dataset["dataset_id"]
        assert replay["lineage"]["schema"] == "lineage-1"
        assert replay["lineage"]["source_row_sha256"] == dataset["lineage"]["source_row_sha256"]
        assert replay["lineage"]["forecast_promotion_state"] == "TRAINED"
        assert replay["attempts"][0]["reasons"] == _DEFAULT_REASONS
        assert replay["attempts"][0]["decision_attempt"] is True
        assert replay["attempts"][0]["duplicate_request"] is False
        assert replay["attempts"][0]["config_revision"] is None
        assert any(item.startswith("config_revision:") for item in replay["missing"])
        consumed = replay["attempts"][0]["evaluator_inputs"]
        assert consumed["risk_capital_inr"] is None
        assert consumed["calendar"] is None
        assert consumed["quote_max_age_seconds"] == 15
        assert "daily_loss_fraction" not in consumed
        assert "cash_buffer_fraction" not in consumed
        assert replay["lot_size"] is None
        assert "lot_size" in replay["missing"]
        assert "quote" in replay["missing"]
        details = [gate["detail"] for gate in replay["attempts"][0]["gates"]]
        assert "KILL_SWITCH_OFF" in details
        assert "MODEL_NOT_APPROVED" in details
        assert "MISSING_ENTRY_PLAN" in details
        assert replay["transitions"][0]["to_state"] == "PROPOSED"
        assert replay["transitions"][1]["to_state"] == "VETOED"
        assert replay["transitions"][1]["reason"] == "RISK_VETO"
        assert replay["fill"] is None
        assert replay["live_trading_enabled"] is False
        assert replay["paper_approved"] is False
        _safety(session, "sim-audit-a")
    finally:
        session.close()


def test_replay_preserves_request_and_quote_timestamps(db):
    live_order_calls.clear()
    quote_at = (AT - timedelta(seconds=1)).isoformat()
    stale_at = (AT - timedelta(seconds=16)).isoformat()
    fresh = _run(
        _body(
            _dataset(),
            "sim-audit-time",
            quote={"bid": "100", "ask": "101", "quote_timestamp": quote_at},
            entry_plan={"entry_trigger": "touch", "invalidation": "below", "exit_plan": "sell", "time_stop": "15:20"},
        )
    )
    assert "STALE_QUOTE" not in fresh["reasons"]
    assert "MISSING_QUOTE_TIME" not in fresh["reasons"]
    assert "MISSING_ENTRY_PLAN" not in fresh["reasons"]
    assert "MODEL_NOT_APPROVED" in fresh["reasons"]
    stale = _run(_body(_dataset(), "sim-audit-stale", quote={"bid": "100", "ask": "101", "quote_timestamp": stale_at}))
    assert "STALE_QUOTE" in stale["reasons"]
    session = get_session_factory()()
    try:
        fresh_replay = replay_simulation_decision(session, "sim-audit-time")
        stale_replay = replay_simulation_decision(session, "sim-audit-stale")
        assert fresh_replay["request_occurred_at"] == AT.isoformat()
        assert fresh_replay["quote_timestamp"] == quote_at
        assert fresh_replay["quote"]["bid"] == "100"
        assert fresh_replay["quote"]["ask"] == "101"
        assert fresh_replay["quote"]["quote_timestamp"] == quote_at
        assert fresh_replay["quote_timestamp"] != fresh_replay["request_occurred_at"]
        assert fresh_replay["entry_plan"]["entry_trigger"] == "touch"
        assert "entry_plan" not in fresh_replay["missing"]
        assert stale_replay["quote_timestamp"] == stale_at
        assert fresh_replay["attempts"][0]["reasons"] == fresh["reasons"]
        assert stale_replay["attempts"][0]["reasons"] == stale["reasons"]
        _safety(session, "sim-audit-time")
    finally:
        session.close()


def test_replay_keeps_each_attempt_and_the_original_snapshot(db, monkeypatch):
    live_order_calls.clear()
    real = __import__("app.execution.simulation", fromlist=["evaluate"]).evaluate
    calls = {"n": 0}

    def flaky(intent, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("evaluation interrupted")
        return real(intent, **kwargs)

    monkeypatch.setattr("app.execution.simulation.evaluate", flaky)
    quote_at = AT.isoformat()
    body = _body(_dataset(), "sim-audit-retry", quote={"bid": "100", "ask": "101", "quote_timestamp": quote_at})
    assert _run(body)["code"] == "EVALUATION_INTERRUPTED"
    recovered = _run(body)
    assert recovered["code"] == "VETOED"
    repeated = _run(body)
    assert repeated["code"] == "VETOED"
    session = get_session_factory()()
    try:
        replay = replay_simulation_decision(session, "sim-audit-retry")
        assert replay["snapshot_count"] == 1
        assert replay["quote_timestamp"] == quote_at
        assert replay["request_occurred_at"] == AT.isoformat()
        assert [item["code"] for item in replay["attempts"]] == ["EVALUATION_INTERRUPTED", "VETOED", "VETOED"]
        assert replay["attempts"][0]["decision_attempt"] is False
        assert replay["attempts"][1]["decision_attempt"] is True
        assert replay["attempts"][1]["duplicate_request"] is True
        assert replay["attempts"][1]["recovery"] is True
        assert replay["attempts"][1]["reasons"] == recovered["reasons"]
        assert replay["attempts"][2]["duplicate_request"] is True
        assert replay["attempts"][2]["recovery"] is False
        assert replay["attempts"][0]["reasons"] == ["EVALUATION_INTERRUPTED"]
        assert [item["to_state"] for item in replay["transitions"] if item["applied"]] == ["PROPOSED", "VETOED"]
        assert replay["body_hash"] == replay["attempts"][0]["body_hash"] == replay["attempts"][2]["body_hash"]
        _safety(session, "sim-audit-retry")
    finally:
        session.close()


def test_replay_reports_a_missing_or_conflicting_snapshot(db):
    live_order_calls.clear()
    body = _body(_dataset(), "sim-audit-conflict")
    assert _run(body)["state"] == "VETOED"
    conflict = _run(_body(_dataset(), "sim-audit-conflict", strike="1"))
    assert conflict["code"] == "INPUT_CONFLICT"
    session = get_session_factory()()
    try:
        opened = open_intent(session, "sim-audit-missing", occurred_at=AT)
        assert opened["state"] == "PROPOSED"
        closed = _run(
            _body(
                _dataset(),
                "sim-audit-missing",
                quote={"bid": "100", "ask": "101", "quote_timestamp": AT.isoformat()},
            )
        )
        assert closed["code"] == "INPUTS_NOT_STORED"
        assert closed["reasons"] == ["INPUTS_NOT_STORED"]
        missing = replay_simulation_decision(session, "sim-audit-missing")
        assert missing["reconstructed"] is False
        assert "snapshot" in missing["missing"]
        assert missing["quote_timestamp"] is None
        assert missing["request_occurred_at"] is None
        assert missing["attempts"][-1]["reasons"] == ["INPUTS_NOT_STORED"]
        assert missing["attempts"][-1]["decision_attempt"] is False
        before = replay_simulation_decision(session, "sim-audit-conflict")
        original_hash = before["body_hash"]
        session.add(
            AuditEvent(
                actor="tester",
                action="paper.simulation_request",
                entity="paper_intent:sim-audit-conflict",
                before=None,
                after={"body_hash": "f" * 64, "occurred_at": AT.isoformat(), "quote_timestamp": "2099-01-01T00:00:00+00:00", "risk_intent": {"strike": "1"}},
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        replaced = replay_simulation_decision(session, "sim-audit-conflict")
        assert replaced["snapshot_conflict"] is True
        assert replaced["snapshot_count"] == 2
        assert replaced["body_hash"] == original_hash
        assert replaced["quote_timestamp"] is None
        assert replaced["reconstructed"] is False
        assert replaced["attempts"][-1]["code"] == "INPUT_CONFLICT"
        assert replaced["attempts"][-1]["decision_attempt"] is False
        assert replaced["attempts"][-1]["presented_body_hash"] != original_hash
        _safety(session, "sim-audit-conflict")
    finally:
        session.close()
    again = _run(body)
    assert again["code"] == "VETOED"
    session = get_session_factory()()
    try:
        kept = replay_simulation_decision(session, "sim-audit-conflict")
        assert kept["body_hash"] == original_hash
        assert kept["snapshot_count"] == 2
        assert kept["quote_timestamp"] is None
    finally:
        session.close()


def test_concurrent_identical_requests_share_one_intent(db):
    live_order_calls.clear()
    body = _body(_dataset(), "sim-lock-same")

    def same(session):
        return run_paper_simulation(session, body, actor="tester")

    results = _barrier_workers([same, same])
    assert [item["code"] for item in results] == ["VETOED", "VETOED"]
    session = get_session_factory()()
    try:
        replay = replay_simulation_decision(session, "sim-lock-same")
        assert replay["snapshot_count"] == 1
        assert replay["snapshot_conflict"] is False
        assert [item["attempt"] for item in replay["attempts"]] == [1, 2]
        assert [item["to_state"] for item in replay["transitions"] if item["applied"]] == ["PROPOSED", "VETOED"]
        assert replay["attempts"][0]["reasons"] == _DEFAULT_REASONS
        assert replay["attempts"][1]["reasons"] == _DEFAULT_REASONS
        assert replay["fill"] is None
        _safety(session, "sim-lock-same")
    finally:
        session.close()


def test_concurrent_conflicts_do_not_replace_the_snapshot(db):
    live_order_calls.clear()
    first = _body(_dataset(), "sim-lock-conflict", strike="22500")
    second = _body(_dataset(), "sim-lock-conflict", strike="1")

    def run_first(session):
        return run_paper_simulation(session, first, actor="tester")

    def run_second(session):
        return run_paper_simulation(session, second, actor="tester")

    results = _barrier_workers([run_first, run_second])
    codes = sorted(item["code"] for item in results)
    assert codes == ["INPUT_CONFLICT", "VETOED"]
    session = get_session_factory()()
    try:
        replay = replay_simulation_decision(session, "sim-lock-conflict")
        assert replay["snapshot_count"] == 1
        assert replay["snapshot_conflict"] is False
        assert [item["to_state"] for item in replay["transitions"] if item["applied"]] == ["PROPOSED", "VETOED"]
        vetoed = next(item for item in results if item["code"] == "VETOED")
        conflict = next(item for item in results if item["code"] == "INPUT_CONFLICT")
        assert replay["body_hash"] == replay["attempts"][0]["body_hash"]
        assert conflict["reasons"] == ["INPUT_CONFLICT"]
        assert vetoed["reasons"]
        assert replay["fill"] is None
        _safety(session, "sim-lock-conflict")
    finally:
        session.close()


def test_concurrent_attempt_inserts_get_unique_numbers(db):
    live_order_calls.clear()
    body = _body(_dataset(), "sim-lock-attempts")
    assert _run(body)["code"] == "VETOED"

    def again(session):
        return run_paper_simulation(session, body, actor="tester")

    results = _barrier_workers([again, again])
    assert [item["code"] for item in results] == ["VETOED", "VETOED"]
    session = get_session_factory()()
    try:
        replay = replay_simulation_decision(session, "sim-lock-attempts")
        assert [item["attempt"] for item in replay["attempts"]] == [1, 2, 3]
        assert len({item["audit_id"] for item in replay["attempts"]}) == 3
        assert [item["to_state"] for item in replay["transitions"] if item["applied"]] == ["PROPOSED", "VETOED"]
        assert replay["snapshot_count"] == 1
        assert replay["fill"] is None
        _safety(session, "sim-lock-attempts")
    finally:
        session.close()


def test_failed_open_commits_neither_transition_nor_snapshot(db, monkeypatch):
    live_order_calls.clear()
    from sqlalchemy.orm import Session as OrmSession

    real = OrmSession.commit

    def fail(self):
        if getattr(self, "_fail_commit", False):
            raise RuntimeError("commit interrupted")
        return real(self)

    monkeypatch.setattr(OrmSession, "commit", fail)
    session = get_session_factory()()
    session._fail_commit = True
    try:
        with pytest.raises(RuntimeError, match="commit interrupted"):
            open_intent(
                session,
                "sim-lock-fail",
                occurred_at=AT,
                snapshot={"body_hash": "b" * 64, "occurred_at": AT.isoformat(), "risk_intent": {}},
                actor="tester",
            )
        session.rollback()
    finally:
        session.close()
    fresh = get_session_factory()()
    try:
        replay = replay_simulation_decision(fresh, "sim-lock-fail")
        assert replay["state"] is None
        assert replay["snapshot_count"] == 0
        assert replay["transitions"] == []
        assert replay["attempts"] == []
        assert replay["fill"] is None
        _safety(fresh, "sim-lock-fail")
    finally:
        fresh.close()


def test_replay_keeps_attempt_order_and_does_not_read_current_inputs(db, monkeypatch):
    live_order_calls.clear()
    real = __import__("app.execution.simulation", fromlist=["evaluate"]).evaluate
    calls = {"n": 0}

    def flaky(intent, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("evaluation interrupted")
        return real(intent, **kwargs)

    monkeypatch.setattr("app.execution.simulation.evaluate", flaky)
    body = _body(_dataset(), "sim-audit-order")
    assert _run(body)["code"] == "EVALUATION_INTERRUPTED"
    monkeypatch.setattr("app.execution.simulation.evaluate", real)
    vetoed = _run(body)
    repeated = _run(body)
    assert vetoed["reasons"] == repeated["reasons"] == _DEFAULT_REASONS
    assert list(vetoed["reasons"]) == _DEFAULT_REASONS

    def unavailable(*args, **kwargs):
        raise AssertionError("replay must not read current inputs")

    monkeypatch.setattr("app.execution.simulation.evaluate", unavailable)
    monkeypatch.setattr("app.risk.gates.load_defaults", unavailable)
    session = get_session_factory()()
    try:
        replay = replay_simulation_decision(session, "sim-audit-order")
        assert [item["attempt"] for item in replay["attempts"]] == [1, 2, 3]
        assert len({item["attempt"] for item in replay["attempts"]}) == 3
        assert replay["attempts"][0]["decision_attempt"] is False
        assert replay["attempts"][0]["gates"] is None
        assert replay["attempts"][0]["evaluator_inputs"] is None
        assert replay["attempts"][1]["evaluator_inputs"]["risk_capital_inr"] is None
        assert not any(item.startswith("evaluator_inputs:") and item.endswith(str(replay["attempts"][1]["audit_id"])) for item in replay["missing"])
        assert replay["attempts"][0]["reasons"] == ["EVALUATION_INTERRUPTED"]
        assert replay["attempts"][1]["reasons"] == _DEFAULT_REASONS
        assert replay["attempts"][2]["duplicate_request"] is True
        assert [item["to_state"] for item in replay["transitions"] if item["applied"]] == ["PROPOSED", "VETOED"]
        assert replay["quote_timestamp"] is None
        assert "quote_timestamp" in replay["missing"]
        assert "lineage.forecast_model_id" in replay["missing"]
        assert any(item.startswith("config_revision:") for item in replay["missing"])
        assert replay["fill"] is None
        _safety(session, "sim-audit-order")
    finally:
        session.close()


def test_replay_does_not_fill_missing_historical_risk_inputs(db, monkeypatch):
    live_order_calls.clear()
    assert _run(_body(_dataset(), "sim-audit-old"))["code"] == "VETOED"
    session = get_session_factory()()
    try:
        session.add(
            AuditEvent(
                actor="tester",
                action="paper.simulation",
                entity="paper_intent:sim-audit-old",
                before=None,
                after={"code": "VETOED", "reasons": ["MODEL_NOT_APPROVED"], "state": "VETOED", "attempt": 9, "decision_attempt": True, "gates": []},
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

        def unavailable(*args, **kwargs):
            raise AssertionError("replay must not read the current defaults")

        monkeypatch.setattr("app.risk.gates.load_defaults", unavailable)
        monkeypatch.setattr("app.execution.simulation.load_defaults", unavailable)
        replay = replay_simulation_decision(session, "sim-audit-old")
        old = replay["attempts"][-1]
        assert old["attempt"] == 9
        assert old["evaluator_inputs"] is None
        assert old["reasons"] == ["MODEL_NOT_APPROVED"]
        assert any(item.startswith("evaluator_inputs:") for item in replay["missing"])
        assert replay["fill"] is None
    finally:
        session.close()


def test_replay_keeps_historical_duplicate_attempt_numbers(db):
    """Rows inserted outside the intent lock are not renumbered."""
    live_order_calls.clear()
    assert _run(_body(_dataset(), "sim-audit-collide"))["state"] == "VETOED"
    from app.execution.simulation import _attempt_audit

    first = get_session_factory()()
    second = get_session_factory()()
    try:
        left = _attempt_audit(
            first,
            "sim-audit-collide",
            decision_attempt=False,
            duplicate_request=True,
            input_conflict=False,
            recovery=False,
            presented_body_hash=None,
            risk=None,
        )
        right = _attempt_audit(
            second,
            "sim-audit-collide",
            decision_attempt=False,
            duplicate_request=True,
            input_conflict=False,
            recovery=False,
            presented_body_hash=None,
            risk=None,
        )
        assert left["attempt"] == right["attempt"] == 2
        for holder, payload in ((first, left), (second, right)):
            holder.add(
                AuditEvent(
                    actor="tester",
                    action="paper.simulation",
                    entity="paper_intent:sim-audit-collide",
                    before=None,
                    after={"code": "VETOED", "reasons": ["MODEL_NOT_APPROVED", "CHARGES_UNVERIFIED"], "state": "VETOED", **payload},
                    created_at=datetime.now(timezone.utc),
                )
            )
            holder.commit()
        replay = replay_simulation_decision(first, "sim-audit-collide")
        assert [item["attempt"] for item in replay["attempts"]] == [1, 2, 2]
        assert replay["attempts"][1]["reasons"] == ["MODEL_NOT_APPROVED", "CHARGES_UNVERIFIED"]
        assert [item["to_state"] for item in replay["transitions"] if item["applied"]] == ["PROPOSED", "VETOED"]
        assert replay["fill"] is None
        _safety(first, "sim-audit-collide")
    finally:
        first.close()
        second.close()


def _barrier_workers(work) -> list:
    barrier = threading.Barrier(len(work))
    errors = []
    results = []

    def run(item) -> None:
        barrier.wait(timeout=5)
        session = get_session_factory()()
        try:
            results.append(item(session))
        except Exception as exc:
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=run, args=(item,)) for item in work]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert errors == []
    assert not any(thread.is_alive() for thread in threads)
    return results


def test_concurrent_opens_keep_one_snapshot(db):
    live_order_calls.clear()
    snapshot = {"body_hash": "a" * 64, "occurred_at": AT.isoformat(), "request_occurred_at": AT.isoformat(), "risk_intent": {"strike": "22500"}}

    def open_same(session):
        return open_intent(session, "sim-audit-race", occurred_at=AT, snapshot=snapshot, actor="tester")

    opened = _barrier_workers([open_same, open_same])
    assert sorted(item["detail"] for item in opened) == ["DUPLICATE_INTENT", "PROPOSED"]
    session = get_session_factory()()
    try:
        replay = replay_simulation_decision(session, "sim-audit-race")
        assert replay["snapshot_count"] == 1
        assert replay["snapshot_conflict"] is False
        assert replay["body_hash"] == "a" * 64
        proposed = [item for item in replay["transitions"] if item["applied"] and item["to_state"] == "PROPOSED"]
        assert len(proposed) == 1
        assert replay["fill"] is None
        _safety(session, "sim-audit-race")
    finally:
        session.close()
    conflict = _run(_body(_dataset(), "sim-audit-race", strike="1"))
    assert conflict["code"] == "INPUT_CONFLICT"
    session = get_session_factory()()
    try:
        kept = replay_simulation_decision(session, "sim-audit-race")
        assert kept["body_hash"] == "a" * 64
        assert kept["snapshot_count"] == 1
        assert kept["snapshot_conflict"] is False
        assert kept["quote_timestamp"] is None
        assert kept["fill"] is None
    finally:
        session.close()


def _capital_defaults(amount: int):
    from app.config.loader import load_defaults

    loaded = load_defaults(REPO_ROOT / "config" / "defaults.yaml")
    return loaded.model_copy(update={"risk": loaded.risk.model_copy(update={"risk_capital_inr": amount})})


def test_operational_state_records_the_kill_switch_that_was_read(db, monkeypatch):
    live_order_calls.clear()
    from app.risk.ledger import set_kill_switch

    session = get_session_factory()()
    try:
        set_kill_switch(session, False, actor="tester", reason="explicit off")
        assert _run(_body(_dataset(), "sim-ops-off"))["code"] == "VETOED"
        set_kill_switch(session, True, actor="tester", reason="explicit on")
        replay = replay_simulation_decision(session, "sim-ops-off")
        switch = replay["attempts"][0]["operational_state"]["kill_switch"]
        assert switch == {"status": "known", "row_present": True, "enabled": False}
        assert "KILL_SWITCH" not in replay["attempts"][0]["reasons"]
        assert replay["attempts"][0]["operational_state"]["funds"]["status"] == "not_read"
        assert replay["attempts"][0]["operational_state"]["funds"]["paper_cash_known"] is None
        assert replay["attempts"][0]["operational_state"]["position"]["status"] == "row_missing"
        assert replay["attempts"][0]["operational_state"]["position"]["lockout_active"] is None
    finally:
        session.close()

    halted = _run(_body(_dataset(), "sim-ops-on"))
    assert "KILL_SWITCH" in halted["reasons"]
    session = get_session_factory()()
    try:
        on = replay_simulation_decision(session, "sim-ops-on")["attempts"][0]["operational_state"]["kill_switch"]
        assert on["enabled"] is True
        assert on["status"] == "known"

        def fail_read(db_session):
            raise RuntimeError("current ops_state must not be read")

        monkeypatch.setattr("app.risk.gates.read_kill_switch", fail_read)
        monkeypatch.setattr("app.risk.ledger.read_session", fail_read)
        again = replay_simulation_decision(session, "sim-ops-off")
        assert again["attempts"][0]["operational_state"]["kill_switch"]["enabled"] is False
    finally:
        session.close()


def test_missing_and_failed_kill_switch_reads_are_not_off(db, monkeypatch):
    live_order_calls.clear()

    def no_seed(session, settings):
        return None

    monkeypatch.setattr("app.execution.simulation.ensure_seed", no_seed)
    missing = _run(_body(_dataset(), "sim-ops-absent"))
    assert "KILL_SWITCH_NOT_READ" in missing["reasons"]
    session = get_session_factory()()
    try:
        observed = replay_simulation_decision(session, "sim-ops-absent")["attempts"][0]["operational_state"]["kill_switch"]
        assert observed == {"status": "row_missing", "row_present": False, "enabled": None}
    finally:
        session.close()

    def broken(session):
        raise RuntimeError("ops_state unreadable")

    monkeypatch.setattr("app.risk.gates.read_kill_switch", broken)
    failed = _run(_body(_dataset(), "sim-ops-failed"))
    assert "KILL_SWITCH_NOT_READ" in failed["reasons"]
    session = get_session_factory()()
    try:
        observed = replay_simulation_decision(session, "sim-ops-failed")["attempts"][0]["operational_state"]["kill_switch"]
        assert observed["status"] == "read_failed"
        assert observed["enabled"] is None
        assert observed["row_present"] is None
    finally:
        session.close()


def test_operational_state_records_cash_and_lockout_from_the_read(db, monkeypatch):
    live_order_calls.clear()
    from app.risk.ledger import apply_event
    from tests.test_risk_ledger import _event

    monkeypatch.setattr("app.execution.simulation.load_defaults", lambda *args, **kwargs: _capital_defaults(100000))
    session = get_session_factory()()
    try:
        opened = open_session(session, DAY, _config(risk_capital_inr=100000))
        before = read_session(session, DAY)["paper_cash_inr"]
        assert _run(_body(_dataset(), "sim-ops-cash", session_date=DAY.isoformat()))["code"] == "VETOED"
        assert read_session(session, DAY)["paper_cash_inr"] == before
        state = replay_simulation_decision(session, "sim-ops-cash")["attempts"][0]["operational_state"]
        assert state["funds"]["status"] == "known"
        assert state["funds"]["paper_cash_known"] is True
        assert Decimal(state["funds"]["paper_cash_inr"]) == Decimal(opened["paper_cash_inr"])
        assert state["position"]["lockout_active"] is False
        assert state["position"]["lockout_reason"] is None
        session.get(RiskSession, DAY).paper_cash_inr = Decimal("1")
        session.commit()
        unchanged = replay_simulation_decision(session, "sim-ops-cash")["attempts"][0]["operational_state"]["funds"]["paper_cash_inr"]
        assert Decimal(unchanged) == Decimal(before)
    finally:
        session.close()

    absent = get_session_factory()()
    try:
        assert _run(_body(_dataset(), "sim-ops-no-row", session_date="2026-10-15"))["code"] == "VETOED"
        funds = replay_simulation_decision(absent, "sim-ops-no-row")["attempts"][0]["operational_state"]["funds"]
        assert funds["status"] == "row_missing"
        assert funds["paper_cash_known"] is False
        assert funds["paper_cash_inr"] is None
    finally:
        absent.close()

    blank = get_session_factory()()
    try:
        blank.add(
            RiskSession(
                session_date=date(2026, 10, 16),
                paper_cash_inr=None,
                reserved_inr=Decimal("0"),
                open_premium_at_risk_inr=Decimal("0"),
                lockout_active=False,
                lockout_reason=None,
                config_revision=None,
                local_open_positions=0,
            )
        )
        blank.commit()
        assert _run(_body(_dataset(), "sim-ops-null-cash", session_date="2026-10-16"))["code"] == "VETOED"
        funds = replay_simulation_decision(blank, "sim-ops-null-cash")["attempts"][0]["operational_state"]["funds"]
        assert funds["status"] == "known"
        assert funds["paper_cash_known"] is False
        assert funds["paper_cash_inr"] is None
    finally:
        blank.close()

    locked = get_session_factory()()
    try:
        capital = _config(risk_capital_inr=100000)
        lock_day = date(2026, 10, 17)
        open_session(locked, lock_day, capital)
        applied = apply_event(
            locked,
            _event("ops-lock", event_type="LOCKOUT_SET", amount_inr=None, quantity=None, intent_id=None, provenance="OPERATOR_ACTION", reason="session loss", config_revision=1, session_date=lock_day),
            capital,
        )
        assert applied["applied"] is True
        vetoed = _run(_body(_dataset(), "sim-ops-lockout", session_date=lock_day.isoformat()))
        assert "DAILY_LOSS_LOCKOUT" in vetoed["reasons"]
        position = replay_simulation_decision(locked, "sim-ops-lockout")["attempts"][0]["operational_state"]["position"]
        assert position["status"] == "known"
        assert position["lockout_active"] is True
        assert position["lockout_reason"] == "session loss"
        assert position["config_revision"] == 1
        assert replay_simulation_decision(locked, "sim-ops-lockout")["fill"] is None
    finally:
        locked.close()


def test_operational_lock_blocks_a_writer_during_evaluation(db, monkeypatch):
    """A kill-switch write waits until the evaluation transaction releases the operational lock."""
    live_order_calls.clear()
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    from app.risk.ledger import read_kill_switch, set_kill_switch

    probe = get_session_factory()()
    try:
        isolation = probe.execute(text("SHOW transaction_isolation")).scalar()
    finally:
        probe.close()
    assert isolation == "read committed"
    setup = get_session_factory()()
    try:
        set_kill_switch(setup, False, actor="tester", reason="explicit off")
    finally:
        setup.close()

    def read_while_writer_waits(db_session):
        seen = read_kill_switch(db_session)
        outcome = {}

        def writer() -> None:
            other = get_session_factory()()
            try:
                other.execute(text("SET LOCAL lock_timeout = '400ms'"))
                set_kill_switch(other, True, actor="tester", reason="must wait")
                outcome["acquired"] = True
            except OperationalError:
                outcome["acquired"] = False
                other.rollback()
            finally:
                other.close()

        thread = threading.Thread(target=writer)
        thread.start()
        thread.join(timeout=5)
        assert outcome.get("acquired") is False
        assert not thread.is_alive()
        return seen

    monkeypatch.setattr("app.risk.gates.read_kill_switch", read_while_writer_waits)
    vetoed = _run(_body(_dataset(), "sim-ops-lock"))
    assert vetoed["simulated_fill"] is None
    assert "KILL_SWITCH" not in vetoed["reasons"]
    check = get_session_factory()()
    try:
        assert read_kill_switch(check) is False
        stored = replay_simulation_decision(check, "sim-ops-lock")["attempts"][0]["operational_state"]
        assert stored["kill_switch"]["enabled"] is False
        assert stored["position"]["lockout_active"] is None
        assert replay_simulation_decision(check, "sim-ops-lock")["fill"] is None
    finally:
        check.close()


def test_legacy_and_interrupted_attempts_do_not_invent_operational_state(db, monkeypatch):
    live_order_calls.clear()
    real = __import__("app.execution.simulation", fromlist=["evaluate"]).evaluate

    def fail_once(intent, **kwargs):
        monkeypatch.setattr("app.execution.simulation.evaluate", real)
        raise RuntimeError("evaluation interrupted")

    monkeypatch.setattr("app.execution.simulation.evaluate", fail_once)
    assert _run(_body(_dataset(), "sim-ops-interrupt"))["code"] == "EVALUATION_INTERRUPTED"
    session = get_session_factory()()
    try:
        interrupted = replay_simulation_decision(session, "sim-ops-interrupt")["attempts"][0]
        assert interrupted["decision_attempt"] is False
        assert interrupted["operational_state"] is None
        session.add(
            AuditEvent(
                actor="tester",
                action="paper.simulation",
                entity="paper_intent:sim-ops-interrupt",
                before=None,
                after={"code": "VETOED", "reasons": ["MODEL_NOT_APPROVED"], "state": "VETOED", "attempt": 8, "decision_attempt": True, "gates": [], "evaluator_inputs": {}},
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        replay = replay_simulation_decision(session, "sim-ops-interrupt")
        assert replay["attempts"][-1]["operational_state"] is None
        assert any(item.startswith("operational_state:") for item in replay["missing"])
        assert replay["fill"] is None
    finally:
        session.close()
