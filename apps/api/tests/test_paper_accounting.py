"""Offline paper-accounting replay. It is not wired to the simulation or the ledger."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.db import get_session_factory
from app.domain.tables import RiskEvent, RiskSession
from app.execution.orders import live_order_calls
from app.execution.paper import PAPER_TRADING_ACTIVE
from app.risk.ledger import apply_event
from app.risk.paper_accounting import reconcile_paper_accounts, replay_paper_accounts
from app.settings import REPO_ROOT
from tests.test_paper_simulation import _body, _dataset, _run
from tests.test_risk_ledger import _config

AT = datetime(2026, 10, 14, 4, 30, tzinfo=timezone.utc)


def _fill(event_id: str, **extra) -> dict:
    payload = {
        "event_id": event_id,
        "fill_id": event_id,
        "event_type": "FILL",
        "intent_id": "intent-1",
        "occurred_at": AT,
        "side": "BUY",
        "quantity": "2",
        "price": "10",
        "charges_inr": "5",
        "underlying": "NIFTY",
        "expiry": "2026-10-16",
        "strike": "22500",
        "option_type": "CE",
    }
    payload.update(extra)
    return payload


def test_duplicate_fill_ids_do_not_double_count_and_conflicts_stop_replay():
    first = replay_paper_accounts([_fill("f1"), _fill("f1")], opening_cash="1000")
    assert first["stopped"] is False
    assert first["applied_fill_ids"] == ["f1"]
    assert first["positions"][0]["quantity"] == "2"
    assert first["cash_inr"] == "975"
    assert first["charges_booked_inr"] == "5"
    assert first["persisted"] is False
    conflict = replay_paper_accounts([_fill("f1"), _fill("f1b", fill_id="f1", price="11")], opening_cash="1000")
    assert conflict["stopped"] is True
    assert conflict["stop_reason"] == "DUPLICATE_FILL_CONFLICT"
    assert conflict["positions"][0]["quantity"] == "2"
    assert conflict["applied_fill_ids"] == ["f1"]
    reversed_order = replay_paper_accounts(
        [_fill("later", occurred_at=AT + timedelta(seconds=5), quantity="1", price="20", charges_inr="1", fill_id="later"), _fill("earlier")],
        opening_cash="1000",
    )
    chronological = replay_paper_accounts(
        [_fill("earlier"), _fill("later", occurred_at=AT + timedelta(seconds=5), quantity="1", price="20", charges_inr="1", fill_id="later")],
        opening_cash="1000",
    )
    assert reversed_order["positions"] == chronological["positions"]
    assert reversed_order["cash_inr"] == chronological["cash_inr"]


def test_incomplete_inputs_and_missing_charges_do_not_fabricate_balances():
    missing_price = replay_paper_accounts(
        [_fill("bad", price=None), _fill("after", fill_id="after", occurred_at=AT + timedelta(seconds=1))],
        opening_cash="1000",
    )
    assert missing_price["stopped"] is True
    assert missing_price["stop_reason"] == "INCOMPLETE_FILL"
    assert missing_price["positions"] == []
    assert missing_price["cash_inr"] == "1000"
    assert missing_price["applied_fill_ids"] == []
    unknown_charge = replay_paper_accounts([_fill("open", charges_inr=None)], opening_cash="1000")
    assert unknown_charge["charges_booked_inr"] is None
    assert unknown_charge["charges_known"] is False
    assert unknown_charge["cash_inr"] is None
    assert unknown_charge["positions"][0]["quantity"] == "2"
    assert unknown_charge["positions"][0]["average_entry_ask"] == "10"
    assert unknown_charge["session_pnl_inr"] is None
    no_opening_cash = replay_paper_accounts([_fill("priced")])
    assert no_opening_cash["cash_inr"] is None
    assert no_opening_cash["charges_booked_inr"] == "5"
    assert no_opening_cash["positions"][0]["open_premium_inr"] == "20"


def test_partial_fill_cancel_and_failed_tail_leave_a_declared_book():
    partial = _fill("part", quantity="4", order_quantity="10", charges_inr="2")
    cancel = {
        "event_id": "cancel",
        "event_type": "CANCEL",
        "intent_id": "intent-1",
        "occurred_at": AT + timedelta(seconds=1),
    }
    later = _fill("tail", fill_id="tail", occurred_at=AT + timedelta(seconds=3), quantity="1")
    broken = _fill("broken", fill_id="broken", occurred_at=AT + timedelta(seconds=2), price=None)
    replay = replay_paper_accounts([partial, cancel, broken, later], opening_cash="1000")
    assert replay["stopped"] is True
    assert replay["stop_reason"] == "INCOMPLETE_FILL"
    assert replay["applied_fill_ids"] == ["part"]
    assert "tail" not in replay["applied_fill_ids"]
    assert replay["positions"][0]["quantity"] == "4"
    assert replay["intents"]["intent-1"]["status"] == "CANCELLED"
    assert replay["intents"]["intent-1"]["filled_quantity"] == "4"
    assert replay["intents"]["intent-1"]["unfilled_quantity"] == "6"
    unknown_remainder = replay_paper_accounts(
        [_fill("only", quantity="4", order_quantity=None), {**cancel, "event_id": "cancel-2"}],
        opening_cash="500",
    )
    assert unknown_remainder["intents"]["intent-1"]["unfilled_quantity"] is None
    oversell = replay_paper_accounts(
        [_fill("long", quantity="1"), _fill("short", fill_id="short", side="SELL", quantity="2", occurred_at=AT + timedelta(seconds=1))],
        opening_cash="1000",
    )
    assert oversell["stop_reason"] == "OVERSELL"
    assert oversell["positions"][0]["quantity"] == "1"


def test_reconciliation_does_not_treat_absent_records_as_zero():
    replay = replay_paper_accounts([_fill("f1")], opening_cash="1000")
    absent = reconcile_paper_accounts(replay=replay, statement={})
    assert absent["consistent"] is False
    assert "POSITION_STATEMENT_ABSENT" in absent["reasons"]
    assert "CASH_ABSENT" in absent["reasons"]
    assert "CHARGES_ABSENT" in absent["reasons"]
    assert "FILL_STATEMENT_ABSENT" in absent["reasons"]
    matched = reconcile_paper_accounts(
        replay=replay,
        tolerance="0",
        max_age_seconds=60,
        as_of=AT,
        statement={
            "positions": replay["positions"],
            "cash_inr": replay["cash_inr"],
            "charges_booked_inr": replay["charges_booked_inr"],
            "fill_ids": replay["applied_fill_ids"],
            "as_of": AT.isoformat(),
            "source": "EXPLICIT_FIXTURE",
            "verified": True,
            "completeness": "COMPLETE",
        },
    )
    assert matched["consistent"] is True
    assert matched["broker_orders"] == 0
    mismatched = reconcile_paper_accounts(
        replay=replay,
        statement={
            "positions": [],
            "cash_inr": "0",
            "charges_booked_inr": "0",
            "fill_ids": [],
        },
    )
    assert mismatched["consistent"] is False
    assert "POSITION_ABSENT" in mismatched["reasons"]
    assert "CASH_MISMATCH" in mismatched["reasons"]
    assert "FILL_ID_MISMATCH" in mismatched["reasons"]
    unknown = reconcile_paper_accounts(replay=replay_paper_accounts([_fill("bare", charges_inr=None)], opening_cash="1000"), statement={"positions": [], "cash_inr": None, "charges_booked_inr": None, "fill_ids": ["bare"]})
    assert unknown["consistent"] is False
    assert "CASH_UNKNOWN" in unknown["reasons"]
    assert "CHARGES_UNKNOWN" in unknown["reasons"]
    null_statement = reconcile_paper_accounts(
        replay=replay,
        statement={
            "positions": replay["positions"],
            "cash_inr": None,
            "charges_booked_inr": None,
            "fill_ids": replay["applied_fill_ids"],
        },
    )
    assert null_statement["consistent"] is False
    assert "CASH_STATEMENT_UNKNOWN" in null_statement["reasons"]
    assert "CHARGES_STATEMENT_UNKNOWN" in null_statement["reasons"]
    invalid_statement = reconcile_paper_accounts(
        replay=replay,
        statement={
            "positions": replay["positions"],
            "cash_inr": "not-money",
            "charges_booked_inr": replay["charges_booked_inr"],
            "fill_ids": replay["applied_fill_ids"],
        },
    )
    assert invalid_statement["consistent"] is False
    assert "CASH_STATEMENT_INVALID" in invalid_statement["reasons"]
    omitted = reconcile_paper_accounts(
        replay={key: value for key, value in replay.items() if key != "positions"},
        statement={
            "positions": [],
            "cash_inr": replay["cash_inr"],
            "charges_booked_inr": replay["charges_booked_inr"],
            "fill_ids": replay["applied_fill_ids"],
        },
    )
    assert omitted["consistent"] is False
    assert "POSITION_REPLAY_ABSENT" in omitted["reasons"]
    missing_tolerance = reconcile_paper_accounts(
        replay=replay,
        statement={
            "positions": replay["positions"],
            "cash_inr": replay["cash_inr"],
            "charges_booked_inr": replay["charges_booked_inr"],
            "fill_ids": replay["applied_fill_ids"],
            "as_of": AT.isoformat(),
            "source": "EXPLICIT_FIXTURE",
        },
    )
    assert missing_tolerance["consistent"] is False
    assert "TOLERANCE_MISSING" in missing_tolerance["reasons"]
    broker = reconcile_paper_accounts(
        replay=replay,
        tolerance="0",
        max_age_seconds=60,
        as_of=AT,
        statement={
            "positions": replay["positions"],
            "cash_inr": replay["cash_inr"],
            "charges_booked_inr": replay["charges_booked_inr"],
            "fill_ids": replay["applied_fill_ids"],
            "as_of": AT.isoformat(),
            "source": "BROKER",
            "verified": False,
        },
    )
    assert "BROKER_EVIDENCE_UNVERIFIED" in broker["reasons"]
    stale = reconcile_paper_accounts(
        replay=replay,
        tolerance="0",
        max_age_seconds=1,
        as_of=AT,
        statement={
            "positions": replay["positions"],
            "cash_inr": replay["cash_inr"],
            "charges_booked_inr": replay["charges_booked_inr"],
            "fill_ids": replay["applied_fill_ids"],
            "as_of": (AT - timedelta(seconds=30)).isoformat(),
            "source": "EXPLICIT_FIXTURE",
        },
    )
    assert "STATEMENT_STALE" in stale["reasons"]


def test_replay_is_not_a_ledger_fill_and_a_veto_still_posts_nothing(db):
    live_order_calls.clear()
    session = get_session_factory()()
    try:
        refused = apply_event(
            session,
            {
                "event_id": "fill-event",
                "event_type": "FILL",
                "occurred_at": AT,
                "session_date": "2026-10-14",
                "provenance": "LEDGER",
                "intent_id": "intent-1",
                "amount_inr": "10",
            },
            _config(),
        )
        assert refused["applied"] is False
        assert refused["detail"] == "INVALID_EVENT_TYPE"
        assert session.scalar(select(func.count()).select_from(RiskSession)) == 0
        assert session.scalar(select(func.count()).select_from(RiskEvent)) == 0
    finally:
        session.close()
    vetoed = _run(_body(_dataset(), "accounting-veto"))
    assert vetoed["code"] == "VETOED"
    assert vetoed["simulated_fill"] is None
    assert "MODEL_NOT_APPROVED" in vetoed["reasons"]
    assert "MISSING_ENTRY_PLAN" in vetoed["reasons"]
    stale = _run(
        _body(
            _dataset(),
            "accounting-stale",
            quote={"bid": "100", "ask": "102", "quote_timestamp": (AT - timedelta(seconds=16)).isoformat()},
            entry_plan={"entry_trigger": "t", "invalidation": "i", "exit_plan": "e", "time_stop": "s"},
        )
    )
    assert "STALE_QUOTE" in stale["reasons"]
    assert "MISSING_ENTRY_PLAN" not in stale["reasons"]
    assert stale["simulated_fill"] is None
    source = (REPO_ROOT / "apps" / "api" / "app" / "execution" / "simulation.py").read_text(encoding="utf-8")
    assert "paper_accounting" not in source
    assert "place_live_order" not in source
    assert PAPER_TRADING_ACTIVE is False
    assert live_order_calls == []
    session = get_session_factory()()
    try:
        assert session.scalar(select(func.count()).select_from(RiskEvent)) == 0
        assert session.scalar(select(func.count()).select_from(RiskSession)) == 0
    finally:
        session.close()
