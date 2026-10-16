"""Auditable local risk ledger.

Balances stay null when risk capital is not configured. A second copy of an
event does not change the row. This module does not call a broker.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config.schemas import RiskConfig
from app.db_locks import lock_intent, lock_operational, lock_ops_row
from app.domain.tables import AuditEvent, OpsState, RiskEvent, RiskSession
from app.risk.money import decimal_or_none

EVENT_TYPES = frozenset({"RESERVE", "RELEASE", "LOCKOUT_SET", "LOCKOUT_CLEAR"})
PROVENANCE = frozenset({"CONFIGURED_INPUT", "LEDGER", "OPERATOR_ACTION"})
_FLAGS = {
    "forecast_ready": False,
    "paper_approved": False,
    "live_approved": False,
    "real_market_data_verified": False,
}


def open_session(session: Session, session_date: date, config: RiskConfig, *, commit: bool = True) -> dict:
    """Create the session row once. Paper cash is the configured capital, or null."""
    lock_operational(session)
    row = session.get(RiskSession, session_date)
    if row is None:
        capital = decimal_or_none(config.risk_capital_inr)
        row = RiskSession(
            session_date=session_date,
            paper_cash_inr=capital,
            reserved_inr=Decimal("0"),
            open_premium_at_risk_inr=Decimal("0"),
            lockout_active=False,
            lockout_reason=None,
            config_revision=None,
            local_open_positions=0,
        )
        session.add(row)
        try:
            _finish_tx(session, commit=commit, applied=True)
        except IntegrityError:
            if not commit:
                raise
            session.rollback()
            row = session.get(RiskSession, session_date)
            if row is None:
                return _result("PERSISTENCE_CONFLICT", applied=False, state=None)
    return _state(row)


def apply_event(session: Session, event: dict, config: RiskConfig, *, commit: bool = True) -> dict:
    """Apply one ledger event inside a locked session row."""
    refusal = _invalid(event)
    if refusal is not None:
        _abort_tx(session, commit=commit)
        return _result(refusal, applied=False, state=None)
    lock_operational(session)
    intent_id = event.get("intent_id")
    if isinstance(intent_id, str) and intent_id.strip():
        lock_intent(session, intent_id.strip())
    day = _day(event["session_date"])
    occurred = _time(event["occurred_at"])
    identity = _identity(event)
    body_hash = _hash(event)
    row = session.execute(select(RiskSession).where(RiskSession.session_date == day).with_for_update()).scalar_one_or_none()
    if row is None:
        _abort_tx(session, commit=commit)
        return _result("SESSION_NOT_OPEN", applied=False, state=None)
    existing = session.get(RiskEvent, event["event_id"])
    if existing is not None:
        code = "DUPLICATE_EVENT" if existing.body_hash == body_hash else "DUPLICATE_EVENT_CONFLICT"
        prior = dict(existing.resulting_state)
        _abort_tx(session, commit=commit)
        return _result(code, applied=False, state=prior)
    outcome, detail = _mutate(session, row, event, config)
    problem = _invariant(row, config)
    if problem is not None:
        if commit:
            session.rollback()
            return _result(problem, applied=False, state=None)
        raise LedgerWriteError(problem)
    snapshot = _state(row)
    snapshot["outcome"] = outcome
    snapshot["detail"] = detail
    session.add(
        RiskEvent(
            event_id=event["event_id"],
            event_type=event["event_type"],
            occurred_at=occurred,
            session_date=day,
            intent_id=event.get("intent_id"),
            underlying=identity["underlying"],
            expiry=identity["expiry"],
            strike=identity["strike"],
            option_type=identity["option_type"],
            quantity=identity["quantity"],
            amount_inr=decimal_or_none(event.get("amount_inr")),
            provenance=event["provenance"],
            body_hash=body_hash,
            resulting_state=snapshot,
            created_at=datetime.now(timezone.utc),
        )
    )
    session.flush()
    if _reserved_total(session, row.session_date) != row.reserved_inr or row.open_premium_at_risk_inr != 0 or row.local_open_positions != 0:
        if commit:
            session.rollback()
            return _result("INVARIANT_VIOLATION", applied=False, state=None)
        raise LedgerWriteError("INVARIANT_VIOLATION")
    _finish_tx(session, commit=commit, applied=True)
    return _result(detail, applied=outcome == "APPLIED", state=snapshot)


def read_session(session: Session, session_date: date) -> dict | None:
    row = session.get(RiskSession, session_date)
    if row is None:
        return None
    session.refresh(row)
    return _state(row)


def read_kill_switch(session: Session) -> bool | None:
    row = session.get(OpsState, 1)
    if row is None:
        return None
    return bool(row.kill_switch)


def kill_switch_report(row: OpsState | None) -> bool | None:
    """A missing row is unknown. It is not reported as off."""
    if row is None:
        return None
    return bool(row.kill_switch)


def set_kill_switch(session: Session, enabled: bool, *, actor: str, reason: str, commit: bool = True) -> dict:
    if not isinstance(reason, str) or not reason.strip():
        _abort_tx(session, commit=commit)
        return _result("MISSING_KILL_SWITCH_REASON", applied=False, state=None)
    lock_operational(session)
    row = lock_ops_row(session)
    before = None if row is None else {"kill_switch": row.kill_switch}
    if row is None:
        row = OpsState(id=1, kill_switch=enabled, note=reason)
        session.add(row)
    else:
        row.kill_switch = enabled
        row.note = reason
    session.add(
        AuditEvent(
            actor=actor,
            action="risk.kill_switch",
            entity="ops_state:1",
            before=before,
            after={"kill_switch": enabled, "reason": reason},
            created_at=datetime.now(timezone.utc),
        )
    )
    _finish_tx(session, commit=commit, applied=True)
    return _result("APPLIED", applied=True, state={"kill_switch": enabled, **_FLAGS})


class LedgerWriteError(Exception):
    """A caller-owned transaction must roll back. Nothing was committed."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def unfilled_order_quantity(*, order_quantity: object, filled_quantity: object) -> dict:
    """Remaining order size. Both inputs must be explicit. This does not release cash."""
    order = decimal_or_none(order_quantity)
    filled = decimal_or_none(filled_quantity)
    if order_quantity is None or order is None or filled_quantity is None or filled is None:
        return {"unfilled_quantity": None, "reasons": ["UNFILLED_QUANTITY_UNKNOWN"], "persisted": False}
    if order <= 0 or filled < 0 or filled > order:
        return {"unfilled_quantity": None, "reasons": ["INVALID_QUANTITY"], "persisted": False}
    return {"unfilled_quantity": str(order - filled), "reasons": [], "persisted": False}


def classify_reservation_release(
    *,
    reserved_inr: object,
    charges_inr: object,
    order_quantity: object,
    filled_quantity: object,
) -> dict:
    """Classify a reservation release. No configured policy produces a rupee amount."""
    quantity = unfilled_order_quantity(order_quantity=order_quantity, filled_quantity=filled_quantity)
    if "INVALID_QUANTITY" in quantity["reasons"]:
        quantity_status = "INVALID_INPUT"
    elif quantity["reasons"]:
        quantity_status = "INPUTS_MISSING"
    else:
        quantity_status = "FULLY_COMPUTABLE"
    invalid = _release_input_invalid(reserved_inr, charges_inr, order_quantity, filled_quantity)
    missing = reserved_inr is None or order_quantity is None or filled_quantity is None
    if invalid:
        release_status = "INVALID_INPUT"
    elif missing:
        release_status = "INPUTS_MISSING"
    elif charges_inr is None:
        release_status = "CHARGES_UNKNOWN"
    else:
        release_status = "RULE_UNDEFINED"
    return {
        "release_status": release_status,
        "quantity_status": quantity_status,
        "release_inr": None,
        "unfilled_quantity": quantity["unfilled_quantity"],
        "persisted": False,
        "applied": False,
        "ledger_event": None,
        "policy": None,
    }


def _release_input_invalid(reserved_inr: object, charges_inr: object, order_quantity: object, filled_quantity: object) -> bool:
    if reserved_inr is not None and decimal_or_none(reserved_inr) is None:
        return True
    if charges_inr is not None and decimal_or_none(charges_inr) is None:
        return True
    order = None if order_quantity is None else decimal_or_none(order_quantity)
    filled = None if filled_quantity is None else decimal_or_none(filled_quantity)
    if order_quantity is not None and order is None:
        return True
    if filled_quantity is not None and filled is None:
        return True
    if order is not None and order <= 0:
        return True
    if filled is not None and filled <= 0:
        return True
    if reserved_inr is not None and decimal_or_none(reserved_inr) is not None and decimal_or_none(reserved_inr) < 0:
        return True
    if order is not None and filled is not None and filled > order:
        return True
    return False


def reservation_release_for_fill(
    *,
    reserved_inr: object,
    charges_inr: object,
    order_quantity: object,
    filled_quantity: object,
) -> dict:
    """Say what a fill would release. This does not write a reservation or a fill."""
    reasons: list[str] = []
    reserved = decimal_or_none(reserved_inr)
    if reserved_inr is not None and reserved is None:
        reasons.append("RESERVATION_INVALID")
    if reserved_inr is None or reserved is None:
        reasons.append("RESERVATION_UNKNOWN")
    if charges_inr is None:
        reasons.append("CHARGES_UNKNOWN")
    elif decimal_or_none(charges_inr) is None:
        reasons.append("INVALID_CHARGES")
    order = decimal_or_none(order_quantity)
    filled = decimal_or_none(filled_quantity)
    if order_quantity is None or order is None:
        reasons.append("UNFILLED_QUANTITY_UNKNOWN")
    elif order <= 0:
        reasons.append("INVALID_QUANTITY")
    if filled_quantity is None or filled is None or filled <= 0:
        reasons.append("INVALID_QUANTITY")
    elif order is not None and order > 0 and filled > order:
        reasons.append("OVERFILL")
    elif order is not None and filled < order:
        reasons.append("PARTIAL_RELEASE_UNDEFINED")
    if reserved is not None and reserved < 0:
        reasons.append("OVER_RELEASE")
    unique = list(dict.fromkeys(reasons))
    release = None
    if not unique and reserved is not None and filled is not None and order is not None and filled == order:
        release = str(reserved)
        unique = ["FILL_NOT_PERSISTED"]
    return {
        "applied": False,
        "persisted": False,
        "release_inr": release,
        "reasons": unique,
        "fill": None,
    }


def _finish_tx(session: Session, *, commit: bool, applied: bool) -> None:
    if not applied:
        return
    if commit:
        session.commit()
    else:
        session.flush()


def _abort_tx(session: Session, *, commit: bool) -> None:
    if commit:
        session.rollback()


def _mutate(session: Session, row: RiskSession, event: dict, config: RiskConfig) -> tuple[str, str]:
    kind = event["event_type"]
    if kind == "RESERVE":
        return _reserve(session, row, event, config)
    if kind == "RELEASE":
        return _release(session, row, event)
    if kind == "LOCKOUT_SET":
        row.lockout_active = True
        row.lockout_reason = event["reason"]
        row.config_revision = int(event["config_revision"])
        return "APPLIED", "LOCKOUT_SET"
    if event.get("reason") == "SESSION_DATE_CHANGED":
        return "VETO", "CALENDAR_NOT_AUTHORITATIVE"
    if not row.lockout_active:
        return "VETO", "LOCKOUT_NOT_ACTIVE"
    row.lockout_active = False
    row.lockout_reason = event["reason"]
    session.add(
        AuditEvent(
            actor="operator",
            action="risk.lockout_clear",
            entity=f"risk_session:{row.session_date.isoformat()}",
            before={"lockout_active": True},
            after={"lockout_active": False, "reason": event["reason"]},
            created_at=datetime.now(timezone.utc),
        )
    )
    return "APPLIED", "LOCKOUT_CLEARED"


def _reserve(session: Session, row: RiskSession, event: dict, config: RiskConfig) -> tuple[str, str]:
    if row.lockout_active:
        return "VETO", "DAILY_LOSS_LOCKOUT"
    amount = decimal_or_none(event.get("amount_inr"))
    capital = decimal_or_none(config.risk_capital_inr)
    if row.paper_cash_inr is None or capital is None:
        return "VETO", "FUNDS_UNAVAILABLE"
    if _intent_reserved(session, event["intent_id"]) > 0:
        return "VETO", "DUPLICATE_INTENT"
    buffer = decimal_or_none(config.cash_buffer_fraction)
    if buffer is None:
        return "VETO", "MISSING_CASH_BUFFER"
    deployable = row.paper_cash_inr * (Decimal("1") - buffer)
    remaining = capital - row.reserved_inr - row.open_premium_at_risk_inr
    if amount > deployable or amount > remaining:
        return "VETO", "INSUFFICIENT_PAPER_CASH"
    row.reserved_inr = row.reserved_inr + amount
    return "APPLIED", "RESERVED"


def _release(session: Session, row: RiskSession, event: dict) -> tuple[str, str]:
    amount = decimal_or_none(event.get("amount_inr"))
    remaining = _intent_reserved(session, event["intent_id"])
    if remaining <= 0:
        return "VETO", "RESERVATION_NOT_FOUND"
    if amount != remaining:
        return "VETO", "RELEASE_AMOUNT_MISMATCH"
    release_at = _time(event.get("occurred_at"))
    opened_at = _outstanding_reserve_time(session, event["intent_id"])
    if opened_at is not None and release_at is not None and release_at < opened_at:
        return "VETO", "RELEASE_OUT_OF_ORDER"
    if row.reserved_inr < amount:
        return "VETO", "INVARIANT_VIOLATION"
    row.reserved_inr = row.reserved_inr - amount
    return "APPLIED", "RELEASED"


def _outstanding_reserve_time(session: Session, intent_id: str) -> datetime | None:
    events = session.scalars(
        select(RiskEvent)
        .where(RiskEvent.intent_id == intent_id, RiskEvent.event_type.in_(("RESERVE", "RELEASE")))
        .order_by(RiskEvent.occurred_at, RiskEvent.created_at)
    ).all()
    outstanding = Decimal("0")
    opened_at = None
    for item in events:
        if item.resulting_state.get("outcome") != "APPLIED" or item.amount_inr is None:
            continue
        if item.event_type == "RESERVE":
            outstanding += item.amount_inr
            opened_at = item.occurred_at
        elif item.event_type == "RELEASE":
            outstanding -= item.amount_inr
            if outstanding == 0:
                opened_at = None
    return opened_at


def _intent_reserved(session: Session, intent_id: str) -> Decimal:
    return _sum_amounts(session.scalars(select(RiskEvent).where(RiskEvent.intent_id == intent_id)).all())


def _reserved_total(session: Session, session_date: date) -> Decimal:
    rows = session.scalars(select(RiskEvent).where(RiskEvent.session_date == session_date)).all()
    return _sum_amounts(rows)


def _sum_amounts(events: list[RiskEvent]) -> Decimal:
    total = Decimal("0")
    for item in events:
        if item.resulting_state.get("outcome") != "APPLIED" or item.amount_inr is None:
            continue
        if item.event_type == "RESERVE":
            total += item.amount_inr
        elif item.event_type == "RELEASE":
            total -= item.amount_inr
    return total


def _invariant(row: RiskSession, config: RiskConfig) -> str | None:
    if row.reserved_inr < 0 or row.open_premium_at_risk_inr < 0 or row.local_open_positions < 0:
        return "NEGATIVE_BALANCE"
    if row.paper_cash_inr is not None and row.paper_cash_inr < 0:
        return "NEGATIVE_BALANCE"
    capital = decimal_or_none(config.risk_capital_inr)
    if capital is None:
        if row.paper_cash_inr is not None:
            return "CASH_INCONSISTENT"
        return None
    if row.paper_cash_inr != capital:
        return "CASH_INCONSISTENT"
    if row.reserved_inr + row.open_premium_at_risk_inr > capital:
        return "EXPOSURE_EXCEEDS_CAPITAL"
    return None


def _invalid(event: dict) -> str | None:
    if not isinstance(event, dict):
        return "INVALID_EVENT"
    if not isinstance(event.get("event_id"), str) or not event["event_id"].strip():
        return "INVALID_EVENT_ID"
    if event.get("event_type") not in EVENT_TYPES:
        return "INVALID_EVENT_TYPE"
    if event.get("provenance") not in PROVENANCE:
        return "PROVENANCE_REJECTED"
    if _time(event.get("occurred_at")) is None:
        return "INVALID_TIMESTAMP"
    if _day(event.get("session_date")) is None:
        return "INVALID_SESSION_DATE"
    quantity = event.get("quantity")
    if quantity is not None and (decimal_or_none(quantity) is None or decimal_or_none(quantity) <= 0):
        return "INVALID_QUANTITY"
    if event["event_type"] in {"RESERVE", "RELEASE"}:
        amount = decimal_or_none(event.get("amount_inr"))
        if amount is None or amount <= 0:
            return "INVALID_AMOUNT"
        if not isinstance(event.get("intent_id"), str) or not event["intent_id"].strip():
            return "INVALID_INTENT_ID"
    if event["event_type"] == "LOCKOUT_SET":
        if not isinstance(event.get("reason"), str) or not event["reason"].strip():
            return "MISSING_LOCKOUT_REASON"
        if isinstance(event.get("config_revision"), bool) or not isinstance(event.get("config_revision"), int):
            return "MISSING_CONFIG_REVISION"
    if event["event_type"] == "LOCKOUT_CLEAR":
        if event.get("provenance") != "OPERATOR_ACTION" and event.get("reason") != "SESSION_DATE_CHANGED":
            return "LOCKOUT_CLEAR_UNAUDITED"
        if not isinstance(event.get("reason"), str) or not event["reason"].strip():
            return "MISSING_LOCKOUT_REASON"
    return None


def _identity(event: dict) -> dict:
    return {
        "underlying": event.get("underlying") if isinstance(event.get("underlying"), str) else None,
        "expiry": event.get("expiry") if isinstance(event.get("expiry"), str) else None,
        "strike": None if event.get("strike") is None else str(event.get("strike")),
        "option_type": event.get("option_type") if event.get("option_type") in {"CE", "PE"} else None,
        "quantity": None if event.get("quantity") is None else str(decimal_or_none(event.get("quantity"))),
    }


def _state(row: RiskSession) -> dict:
    return {
        "session_date": row.session_date.isoformat(),
        "paper_cash_inr": None if row.paper_cash_inr is None else str(row.paper_cash_inr),
        "reserved_inr": str(row.reserved_inr),
        "open_premium_at_risk_inr": str(row.open_premium_at_risk_inr),
        "lockout_active": row.lockout_active,
        "lockout_reason": row.lockout_reason,
        "config_revision": row.config_revision,
        "local_open_positions": row.local_open_positions,
        "broker_positions_known": False,
        "session_pnl_inr": None,
        "charges_booked_inr": None,
        "estimated_exit_charges_inr": None,
        **_FLAGS,
    }


def _result(detail: str, *, applied: bool, state: dict | None) -> dict:
    return {"applied": applied, "detail": detail, "state": state, "order_connected": False, **_FLAGS}


def _hash(event: dict) -> str:
    amount = decimal_or_none(event.get("amount_inr"))
    quantity = None if event.get("quantity") is None else decimal_or_none(event.get("quantity"))
    occurred = _time(event.get("occurred_at"))
    day = _day(event.get("session_date"))
    body = {
        "event_id": event.get("event_id"),
        "event_type": event.get("event_type"),
        "occurred_at": None if occurred is None else occurred.isoformat(),
        "session_date": None if day is None else day.isoformat(),
        "intent_id": event.get("intent_id"),
        "underlying": event.get("underlying"),
        "expiry": event.get("expiry"),
        "strike": None if event.get("strike") is None else str(event.get("strike")),
        "option_type": event.get("option_type"),
        "quantity": None if quantity is None else format(quantity.normalize(), "f"),
        "amount_inr": None if amount is None else format(amount.normalize(), "f"),
        "provenance": event.get("provenance"),
        "reason": event.get("reason"),
        "config_revision": event.get("config_revision"),
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _day(value: object) -> date | None:
    if isinstance(value, datetime):
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _time(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return None
    return value.astimezone(timezone.utc)
