"""The accounting journal records explicit events and does not move the ledger."""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.db import get_session_factory
from app.domain.tables import PaperAccountEvent, RiskEvent, RiskSession
from app.execution.paper import PAPER_TRADING_ACTIVE
from app.risk.account_journal import current_book, record_account_event
from app.config.loader import load_defaults
from app.execution.orders import live_order_calls
from app.risk.ledger import apply_event, classify_reservation_release, reservation_release_for_fill, unfilled_order_quantity
from app.risk.paper_accounting import reconcile_paper_accounts, replay_paper_accounts
from app.risk.projection import project_journal
from app.settings import REPO_ROOT

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
        "source": "EXPLICIT_FIXTURE",
    }
    payload.update(extra)
    return payload


def _counts(session) -> tuple:
    return (
        session.scalar(select(func.count()).select_from(RiskEvent)),
        session.scalar(select(func.count()).select_from(RiskEvent).where(RiskEvent.event_type == "FILL")),
        session.scalar(select(func.count()).select_from(RiskSession)),
        session.scalar(select(func.count()).select_from(PaperAccountEvent)),
    )


def test_partial_quantity_is_explicit_and_its_rupee_release_stays_undefined():
    assert PAPER_TRADING_ACTIVE is False
    remaining = unfilled_order_quantity(order_quantity="10", filled_quantity="4")
    assert remaining["unfilled_quantity"] == "6"
    assert remaining["persisted"] is False
    assert unfilled_order_quantity(order_quantity=None, filled_quantity="4")["reasons"] == ["UNFILLED_QUANTITY_UNKNOWN"]
    release = reservation_release_for_fill(reserved_inr="100", charges_inr="5", order_quantity="10", filled_quantity="4")
    assert release["release_inr"] is None
    assert "PARTIAL_RELEASE_UNDEFINED" in release["reasons"]
    assert release["persisted"] is False


def test_new_event_types_do_not_treat_unknown_charges_as_free():
    partial = replay_paper_accounts(
        [_fill("part", event_type="PARTIAL_FILL", quantity="4", order_quantity="10", fill_id="part")],
        opening_cash="1000",
    )
    assert partial["stopped"] is False
    assert partial["intents"]["intent-1"]["filled_quantity"] == "4"
    assert partial["intents"]["intent-1"]["unfilled_quantity"] == "6"
    assert partial["persisted"] is False
    missing = replay_paper_accounts(
        [
            _fill("open"),
            {
                "event_id": "charge",
                "event_type": "CHARGE_ASSESSMENT",
                "intent_id": "intent-1",
                "occurred_at": AT + timedelta(seconds=1),
                "charges_inr": None,
                "source": "EXPLICIT_FIXTURE",
            },
        ],
        opening_cash="1000",
    )
    assert missing["stop_reason"] == "CHARGES_UNKNOWN"
    assert missing["charges_booked_inr"] == "5"
    assert missing["cash_inr"] == "975"
    assessed = replay_paper_accounts(
        [
            _fill("open"),
            {
                "event_id": "charge",
                "event_type": "CHARGE_ASSESSMENT",
                "intent_id": "intent-1",
                "occurred_at": AT + timedelta(seconds=1),
                "charges_inr": "1",
                "source": "EXPLICIT_FIXTURE",
            },
            {
                "event_id": "correct",
                "event_type": "CHARGE_CORRECTION",
                "intent_id": "intent-1",
                "occurred_at": AT + timedelta(seconds=2),
                "prior_event_id": "charge",
                "charges_inr": "3",
                "source": "EXPLICIT_FIXTURE",
            },
        ],
        opening_cash="1000",
    )
    assert assessed["charges_booked_inr"] == "8"
    assert assessed["cash_inr"] == "972"
    unknown_prior = replay_paper_accounts(
        [_fill("bare", charges_inr=None), {"event_id": "later", "event_type": "CHARGE_ASSESSMENT", "intent_id": "intent-1", "occurred_at": AT + timedelta(seconds=1), "charges_inr": "1", "source": "EXPLICIT_FIXTURE"}],
        opening_cash="1000",
    )
    assert unknown_prior["stop_reason"] == "CHARGES_ALREADY_UNKNOWN"
    assert unknown_prior["cash_inr"] is None


def test_reconciliation_requires_source_completeness_and_tolerance():
    replay = replay_paper_accounts([_fill("f1")], opening_cash="1000")
    incomplete = reconcile_paper_accounts(
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
            "completeness": "INCOMPLETE",
        },
    )
    assert incomplete["consistent"] is False
    assert "COMPLETENESS_INCOMPLETE" in incomplete["reasons"]
    within = reconcile_paper_accounts(
        replay=replay,
        tolerance="1",
        max_age_seconds=60,
        as_of=AT,
        statement={
            "positions": replay["positions"],
            "cash_inr": "974.5",
            "charges_booked_inr": replay["charges_booked_inr"],
            "fill_ids": replay["applied_fill_ids"],
            "as_of": AT.isoformat(),
            "source": "EXPLICIT_FIXTURE",
            "completeness": "COMPLETE",
        },
    )
    assert "CASH_MISMATCH" not in within["reasons"]
    assert within["consistent"] is True
    outside = reconcile_paper_accounts(
        replay=replay,
        tolerance="1",
        max_age_seconds=60,
        as_of=AT,
        statement={
            "positions": replay["positions"],
            "cash_inr": "900",
            "charges_booked_inr": replay["charges_booked_inr"],
            "fill_ids": replay["applied_fill_ids"],
            "as_of": AT.isoformat(),
            "source": "EXPLICIT_FIXTURE",
            "completeness": "COMPLETE",
        },
    )
    assert "CASH_MISMATCH" in outside["reasons"]


def test_journal_records_a_partial_fill_and_keeps_it_after_cancel(db):
    session = get_session_factory()()
    try:
        assert _counts(session) == (0, 0, 0, 0)
        recorded = record_account_event(
            session,
            _fill("part", event_type="PARTIAL_FILL", quantity="4", order_quantity="10", fill_id="part"),
            opening_cash="1000",
        )
        assert recorded["code"] == "RECORDED"
        assert recorded["ledger_applied"] is False
        assert recorded["fill"] is None
        assert recorded["replay"]["cash_inr"] == "955"
        cancelled = record_account_event(
            session,
            {"event_id": "cancel", "event_type": "CANCEL", "intent_id": "intent-1", "occurred_at": AT + timedelta(seconds=1), "order_quantity": "10", "source": "EXPLICIT_FIXTURE"},
            opening_cash="1000",
        )
        assert cancelled["replay"]["intents"]["intent-1"]["status"] == "CANCELLED"
        assert cancelled["replay"]["intents"]["intent-1"]["filled_quantity"] == "4"
        assert _counts(session) == (0, 0, 0, 2)
        assert session.scalar(select(RiskSession.paper_cash_inr).limit(1)) is None
    finally:
        session.close()


def test_duplicate_conflict_invalid_and_oversell_do_not_change_stored_state(db):
    session = get_session_factory()()
    try:
        first = record_account_event(session, _fill("f1"), opening_cash="1000")
        assert first["code"] == "RECORDED"
        again = record_account_event(session, _fill("f1"), opening_cash="1000")
        assert again["code"] == "DUPLICATE_EVENT"
        assert again["recorded"] is False
        conflict = record_account_event(session, _fill("f1", price="11"), opening_cash="1000")
        assert conflict["code"] == "DUPLICATE_EVENT_CONFLICT"
        invalid = record_account_event(session, _fill("bad", price="-1"), opening_cash="1000")
        assert invalid["code"] == "INCOMPLETE_FILL"
        assert invalid["recorded"] is False
        oversell = record_account_event(session, _fill("short", fill_id="short", side="SELL", quantity="9", occurred_at=AT + timedelta(seconds=1)), opening_cash="1000")
        assert oversell["code"] == "OVERSELL"
        assert session.scalar(select(func.count()).select_from(PaperAccountEvent)) == 1
        stored = session.get(PaperAccountEvent, "f1")
        assert stored.price == Decimal("10")
        assert stored.ledger_applied is False
        assert stored.effect["cash_inr"] == "975"
        assert _counts(session)[:3] == (0, 0, 0)
    finally:
        session.close()


def test_out_of_order_insert_replays_by_time_and_does_not_rewrite_the_first_row(db):
    session = get_session_factory()()
    try:
        later = record_account_event(session, _fill("later", occurred_at=AT + timedelta(seconds=5), quantity="1", price="20", charges_inr="1", fill_id="later"), opening_cash="1000")
        assert later["code"] == "RECORDED"
        earlier = record_account_event(session, _fill("earlier"), opening_cash="1000")
        assert earlier["code"] == "RECORDED"
        assert earlier["replay"]["applied_fill_ids"] == ["earlier", "later"]
        assert current_book(session)["applied_fill_ids"] == ["earlier", "later"]
        session.refresh(session.get(PaperAccountEvent, "later"))
        assert session.get(PaperAccountEvent, "later").effect["applied_fill_ids"] == ["later"]
    finally:
        session.close()


def test_uncommitted_journal_row_is_invisible_and_a_constraint_rejects_an_applied_flag(db):
    session = get_session_factory()()
    other = get_session_factory()()
    try:
        held = record_account_event(session, _fill("held"), opening_cash="1000", commit=False)
        assert held["code"] == "RECORDED"
        assert other.scalar(select(func.count()).select_from(PaperAccountEvent)) == 0
        session.rollback()
        assert other.scalar(select(func.count()).select_from(PaperAccountEvent)) == 0
        other.add(
            PaperAccountEvent(
                event_id="forced",
                event_type="FILL",
                occurred_at=AT,
                intent_id="intent-1",
                source="EXPLICIT_FIXTURE",
                body_hash="abc",
                opening_cash_inr=None,
                quantity=None,
                price=None,
                charges_inr=None,
                payload={},
                effect={},
                ledger_applied=True,
                broker_confirmed=False,
                created_at=AT,
            )
        )
        try:
            other.flush()
            raised = False
        except IntegrityError:
            raised = True
            other.rollback()
        assert raised is True
        assert other.scalar(select(func.count()).select_from(PaperAccountEvent)) == 0
        columns = other.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'risk_events'")).scalars().all()
        assert "event_type" in columns
        assert other.scalar(select(func.count()).select_from(RiskEvent).where(RiskEvent.event_type == "FILL")) == 0
    finally:
        session.close()
        other.close()


def test_concurrent_identical_and_conflicting_events_leave_one_row(db):
    barrier = threading.Barrier(2)
    same: list[dict] = []

    def worker(price: str, bucket: list[dict]) -> None:
        barrier.wait(timeout=5)
        local = get_session_factory()()
        try:
            bucket.append(record_account_event(local, _fill("race", price=price), opening_cash="1000"))
        finally:
            local.close()

    threads = [threading.Thread(target=worker, args=("10", same)), threading.Thread(target=worker, args=("10", same))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert len(same) == 2
    assert {item["code"] for item in same} == {"RECORDED", "DUPLICATE_EVENT"}
    check = get_session_factory()()
    try:
        assert check.scalar(select(func.count()).select_from(PaperAccountEvent)) == 1
        assert _counts(check)[:3] == (0, 0, 0)
    finally:
        check.close()
    conflict_barrier = threading.Barrier(2)
    conflict: list[dict] = []

    def conflicting(price: str) -> None:
        conflict_barrier.wait(timeout=5)
        local = get_session_factory()()
        try:
            conflict.append(record_account_event(local, _fill("race-2", price=price), opening_cash="1000"))
        finally:
            local.close()

    threads = [threading.Thread(target=conflicting, args=("10",)), threading.Thread(target=conflicting, args=("11",))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert {item["code"] for item in conflict} == {"RECORDED", "DUPLICATE_EVENT_CONFLICT"}
    check = get_session_factory()()
    try:
        row = check.get(PaperAccountEvent, "race-2")
        assert row is not None
        assert row.ledger_applied is False
        assert check.scalar(select(func.count()).select_from(PaperAccountEvent).where(PaperAccountEvent.event_id == "race-2")) == 1
        assert _counts(check)[:3] == (0, 0, 0)
    finally:
        check.close()


def test_a_discrepancy_record_does_not_change_cash(db):
    session = get_session_factory()()
    try:
        record_account_event(session, _fill("f1"), opening_cash="1000")
        recorded = record_account_event(
            session,
            {
                "event_id": "gap",
                "event_type": "RECONCILIATION_DISCREPANCY",
                "intent_id": "intent-1",
                "occurred_at": AT + timedelta(seconds=1),
                "source": "EXPLICIT_FIXTURE",
                "statement_id": "statement-1",
                "statement_as_of": AT.isoformat(),
                "completeness": "INCOMPLETE",
            },
            opening_cash="1000",
        )
        assert recorded["code"] == "RECORDED"
        assert recorded["replay"]["cash_inr"] == "975"
        assert recorded["replay"]["discrepancies"][0]["statement_id"] == "statement-1"
        assert recorded["broker_confirmed"] is False
        assert _counts(session)[:3] == (0, 0, 0)
    finally:
        session.close()


def test_replay_order_follows_persisted_time_and_event_id(db):
    earlier = datetime(2026, 10, 14, 9, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    later = datetime(2026, 10, 14, 4, 0, tzinfo=timezone.utc)
    buy = _fill("buy", occurred_at=earlier, quantity="2", price="10", charges_inr="5", fill_id="buy")
    sell = _fill("sell", occurred_at=later, side="SELL", quantity="1", price="12", charges_inr="1", fill_id="sell")
    forward = replay_paper_accounts([sell, buy], opening_cash="1000")
    reverse = replay_paper_accounts([buy, sell], opening_cash="1000")
    assert forward["stopped"] is False
    assert forward["applied_event_ids"] == ["buy", "sell"]
    assert forward["cash_inr"] == "986"
    assert reverse == forward
    same_time = AT
    second = replay_paper_accounts([_fill("m", occurred_at=same_time, fill_id="m"), _fill("a", occurred_at=same_time, fill_id="a")], opening_cash="1000")
    first = replay_paper_accounts([_fill("a", occurred_at=same_time, fill_id="a"), _fill("m", occurred_at=same_time, fill_id="m")], opening_cash="1000")
    assert first["applied_event_ids"] == ["a", "m"]
    assert second == first
    session = get_session_factory()()
    try:
        assert record_account_event(session, sell, opening_cash="1000")["code"] == "OVERSELL"
        assert project_journal(session)["event_ids"] == []
        assert record_account_event(session, buy, opening_cash="1000")["code"] == "RECORDED"
        assert record_account_event(session, sell, opening_cash="1000")["code"] == "RECORDED"
        projected = project_journal(session)
        assert projected["event_ids"] == ["buy", "sell"]
        assert projected["cash"] == {"status": "known", "value": "986"}
        assert project_journal(session) == projected
        stored_sell = session.get(PaperAccountEvent, "sell")
        assert stored_sell.effect["applied_fill_ids"] == ["buy", "sell"]
        session.execute(text("DELETE FROM paper_account_events"))
        session.commit()
        assert record_account_event(session, _fill("m", occurred_at=same_time, fill_id="m"), opening_cash="1000")["code"] == "RECORDED"
        assert record_account_event(session, _fill("a", occurred_at=same_time, fill_id="a"), opening_cash="1000")["code"] == "RECORDED"
        assert project_journal(session)["event_ids"] == ["a", "m"]
        assert session.get(PaperAccountEvent, "m").effect["applied_fill_ids"] == ["m"]
        assert session.get(PaperAccountEvent, "m").effect["cash_inr"] == "975"
        assert project_journal(session)["cash"]["value"] == "950"
    finally:
        session.close()


def test_projection_reports_unknown_values_and_does_not_change_the_ledger(db):
    session = get_session_factory()()
    other = get_session_factory()()
    try:
        before = _counts(session)
        assert before == (0, 0, 0, 0)
        session.add(
            RiskSession(
                session_date=date(2026, 10, 14),
                paper_cash_inr=Decimal("500"),
                reserved_inr=Decimal("0"),
                open_premium_at_risk_inr=Decimal("0"),
                lockout_active=False,
                local_open_positions=3,
            )
        )
        session.commit()
        empty = project_journal(session)
        assert empty["cash"] == {"status": "unavailable", "value": None}
        assert empty["charges"]["value"] is None
        assert empty["open_premium"]["value"] is None
        assert empty["pnl"]["value"] is None
        assert empty["positions"]["value"] is None
        assert session.get(RiskSession, date(2026, 10, 14)).paper_cash_inr == Decimal("500")
        assert session.get(RiskSession, date(2026, 10, 14)).local_open_positions == 3
        held = record_account_event(session, _fill("held", charges_inr=None), opening_cash="1000", commit=False)
        assert held["code"] == "RECORDED"
        assert other.scalar(select(func.count()).select_from(PaperAccountEvent)) == 0
        assert project_journal(other)["event_ids"] == []
        session.rollback()
        missing = record_account_event(session, _fill("bad", quantity=None), opening_cash="1000")
        assert missing["code"] == "INCOMPLETE_FILL"
        conflict_first = record_account_event(session, _fill("f1", charges_inr=None), opening_cash="1000")
        assert conflict_first["code"] == "RECORDED"
        conflict = record_account_event(session, _fill("f1", price="11", charges_inr=None), opening_cash="1000")
        assert conflict["code"] == "DUPLICATE_EVENT_CONFLICT"
        unknown = project_journal(session)
        assert unknown["event_ids"] == ["f1"]
        assert unknown["cash"] == {"status": "unknown", "value": None}
        assert unknown["charges"] == {"status": "unknown", "value": None}
        assert unknown["open_premium"]["status"] == "known"
        assert unknown["open_premium"]["value"] != "0"
        assert unknown["pnl"] == {"status": "unavailable", "value": None}
        assert unknown["stopped"] is False
        assert unknown["first_invalid_event"] is None
        assert unknown["active_paper_account"] is False
        assert unknown["ledger_applied"] is False
        partial = record_account_event(
            session,
            _fill("part", event_type="PARTIAL_FILL", quantity="4", order_quantity="10", fill_id="part", occurred_at=AT + timedelta(seconds=1)),
            opening_cash="1000",
        )
        assert partial["code"] == "RECORDED"
        rejected = record_account_event(
            session,
            {"event_id": "reject", "event_type": "REJECT", "intent_id": "intent-1", "occurred_at": AT + timedelta(seconds=2), "order_quantity": "10", "source": "EXPLICIT_FIXTURE"},
            opening_cash="1000",
        )
        assert rejected["code"] == "RECORDED"
        after_reject = project_journal(session)
        assert after_reject["positions"]["value"][0]["quantity"] == "6"
        assert after_reject["cash"]["status"] == "unknown"
        assert "part" in after_reject["event_ids"]
        gap = record_account_event(
            session,
            {
                "event_id": "gap",
                "event_type": "RECONCILIATION_DISCREPANCY",
                "intent_id": "intent-1",
                "occurred_at": AT + timedelta(seconds=3),
                "source": "EXPLICIT_FIXTURE",
                "statement_id": "statement-1",
                "statement_as_of": AT.isoformat(),
                "completeness": "INCOMPLETE",
            },
            opening_cash="1000",
        )
        assert gap["code"] == "RECORDED"
        reported = project_journal(session)
        assert reported["discrepancies"][0]["statement_id"] == "statement-1"
        assert reported["discrepancies_do_not_adjust_balances"] is True
        assert reported["cash"] == after_reject["cash"]
        assert session.get(RiskSession, date(2026, 10, 14)).paper_cash_inr == Decimal("500")
        assert session.get(RiskSession, date(2026, 10, 14)).local_open_positions == 3
        assert session.get(RiskSession, date(2026, 10, 14)).open_premium_at_risk_inr == Decimal("0")
        assert _counts(session)[:3] == (0, 0, 1)
        assert live_order_calls == []
        assert PAPER_TRADING_ACTIVE is False
    finally:
        session.close()
        other.close()


def test_a_stored_invalid_payload_stops_the_projection_without_rewriting_rows(db):
    session = get_session_factory()()
    try:
        payload = _fill("short", side="SELL", quantity="1", fill_id="short")
        payload["occurred_at"] = AT.isoformat()
        session.add(
            PaperAccountEvent(
                event_id="short",
                event_type="FILL",
                occurred_at=AT,
                intent_id="intent-1",
                source="EXPLICIT_FIXTURE",
                body_hash="stored-invalid",
                opening_cash_inr=Decimal("1000"),
                quantity=Decimal("1"),
                price=Decimal("10"),
                charges_inr=Decimal("5"),
                payload=payload,
                effect={"cash_inr": "0"},
                ledger_applied=False,
                broker_confirmed=False,
                created_at=AT,
            )
        )
        session.commit()
        projected = project_journal(session)
        assert projected["stopped"] is True
        assert projected["stop_reason"] == "OVERSELL"
        assert projected["first_invalid_event"] == {"event_id": "short", "reason": "OVERSELL"}
        assert projected["cash"] == {"status": "known", "value": "1000"}
        assert session.get(PaperAccountEvent, "short").effect == {"cash_inr": "0"}
        assert _counts(session)[:3] == (0, 0, 0)
    finally:
        session.close()


def test_reservation_release_statuses_do_not_reach_the_ledger(db):
    cases = [
        classify_reservation_release(reserved_inr="100", charges_inr="5", order_quantity="10", filled_quantity="4"),
        classify_reservation_release(reserved_inr=None, charges_inr="5", order_quantity="10", filled_quantity="4"),
        classify_reservation_release(reserved_inr="100", charges_inr=None, order_quantity="10", filled_quantity="4"),
        classify_reservation_release(reserved_inr="100", charges_inr="5", order_quantity="10", filled_quantity="11"),
        classify_reservation_release(reserved_inr="100", charges_inr="5", order_quantity=None, filled_quantity="4"),
        classify_reservation_release(reserved_inr="100", charges_inr="5", order_quantity="10", filled_quantity="10"),
    ]
    assert {item["release_status"] for item in cases} == {"RULE_UNDEFINED", "INPUTS_MISSING", "CHARGES_UNKNOWN", "INVALID_INPUT"}
    assert {item["quantity_status"] for item in cases} == {"FULLY_COMPUTABLE", "INPUTS_MISSING", "INVALID_INPUT"}
    assert all(item["release_status"] != "FULLY_COMPUTABLE" for item in cases)
    assert all(item["release_inr"] is None and item["applied"] is False and item["persisted"] is False and item["ledger_event"] is None for item in cases)
    config = load_defaults(REPO_ROOT / "config" / "defaults.yaml").risk
    session = get_session_factory()()
    try:
        assert _counts(session) == (0, 0, 0, 0)
        for index, item in enumerate(cases):
            refused = apply_event(
                session,
                {
                    "event_id": f"fill-{index}",
                    "event_type": "FILL",
                    "occurred_at": AT,
                    "session_date": date(2026, 10, 14),
                    "intent_id": "intent-1",
                    "amount_inr": item["release_inr"],
                    "provenance": "CONFIGURED_INPUT",
                },
                config,
            )
            assert refused["applied"] is False
            assert refused["detail"] == "INVALID_EVENT_TYPE"
            release = apply_event(
                session,
                {
                    "event_id": f"release-{index}",
                    "event_type": "RELEASE",
                    "occurred_at": AT,
                    "session_date": date(2026, 10, 14),
                    "intent_id": "intent-1",
                    "amount_inr": item["release_inr"],
                    "provenance": "CONFIGURED_INPUT",
                },
                config,
            )
            assert release["applied"] is False
            assert release["detail"] == "INVALID_AMOUNT"
        assert _counts(session) == (0, 0, 0, 0)
        assert live_order_calls == []
        assert PAPER_TRADING_ACTIVE is False
    finally:
        session.close()
