"""Append-only paper-accounting journal.

Rows replay explicit events. They do not update risk_sessions, paper cash,
positions, or reservations, and they cannot be marked broker-confirmed.

Replay order is the persisted occurred_at instant, then event_id. Insertion
order and the effect stored on an older row are not the book. A later insert
does not rewrite an earlier row.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain.tables import PaperAccountEvent
from app.execution.paper import PAPER_TRADING_ACTIVE
from app.risk.money import decimal_or_none
from app.risk.paper_accounting import _aware, _digest, _invalid, _money, replay_paper_accounts

JOURNAL_LOCK_NAMESPACE = 841106
_SOURCES = frozenset({"EXPLICIT_FIXTURE", "OPERATOR_ACTION", "REPLAY"})


def record_account_event(session: Session, event: dict, *, opening_cash: object = None, commit: bool = True) -> dict:
    """Store one explicit event and its replay effect, or store nothing."""
    if PAPER_TRADING_ACTIVE:
        return _closed("ACTIVATION_REFUSED")
    refusal = _invalid(event) if isinstance(event, dict) else "INVALID_EVENT"
    if refusal is not None:
        return _closed(refusal)
    if event.get("source") not in _SOURCES:
        return _closed("SOURCE_MISSING")
    if event.get("broker_confirmed") is True or event.get("source") == "BROKER":
        return _closed("BROKER_CONFIRMATION_REFUSED")
    basis = _basis(opening_cash)
    if opening_cash is not None and basis is None:
        return _closed("INVALID_OPENING_CASH")
    digest = _digest(event)
    _lock(session)
    existing = session.get(PaperAccountEvent, event["event_id"])
    if existing is not None:
        if existing.body_hash != digest or _same_basis(existing.opening_cash_inr, basis) is False:
            _abort(session, commit=commit)
            code = "OPENING_CASH_CONFLICT" if existing.body_hash == digest else "DUPLICATE_EVENT_CONFLICT"
            return _closed(code, event_id=event["event_id"], body_hash=existing.body_hash)
        return {
            "code": "DUPLICATE_EVENT",
            "recorded": False,
            "applied": False,
            "ledger_applied": False,
            "broker_confirmed": False,
            "event_id": event["event_id"],
            "body_hash": digest,
            "fill": None,
        }
    stored = _stored_rows(session)
    if stored and _same_basis(stored[0].opening_cash_inr, basis) is False:
        _abort(session, commit=commit)
        return _closed("OPENING_CASH_CONFLICT", event_id=event["event_id"])
    payload = _payload(event)
    replay = replay_paper_accounts([row.payload for row in stored] + [payload], opening_cash=opening_cash)
    if event["event_id"] not in replay.get("applied_event_ids", []):
        _abort(session, commit=commit)
        return _closed(replay.get("stop_reason") or "REJECTED", event_id=event["event_id"], replay=replay)
    effect = dict(replay)
    effect["ledger_applied"] = False
    effect["broker_confirmed"] = False
    session.add(
        PaperAccountEvent(
            event_id=event["event_id"],
            event_type=event["event_type"],
            occurred_at=_aware(event.get("occurred_at")),
            intent_id=event["intent_id"],
            source=event["source"],
            body_hash=digest,
            opening_cash_inr=basis,
            quantity=_money(event.get("quantity")),
            price=_money(event.get("price")),
            charges_inr=None if event.get("charges_inr") is None else _money(event.get("charges_inr")),
            payload=payload,
            effect=effect,
            ledger_applied=False,
            broker_confirmed=False,
            created_at=datetime.now(timezone.utc),
        )
    )
    if commit:
        session.commit()
    else:
        session.flush()
    return {
        "code": "RECORDED",
        "recorded": True,
        "applied": False,
        "ledger_applied": False,
        "broker_confirmed": False,
        "event_id": event["event_id"],
        "body_hash": digest,
        "fill": None,
        "replay": effect,
    }


def current_book(session: Session, *, opening_cash: object = None) -> dict:
    """Replay committed journal rows by time, then event id. This does not write or lock."""
    stored = _stored_rows(session)
    basis = opening_cash
    if stored and opening_cash is None:
        basis = None if stored[0].opening_cash_inr is None else str(stored[0].opening_cash_inr)
    replay = replay_paper_accounts([row.payload for row in stored], opening_cash=basis)
    replay["ledger_applied"] = False
    replay["broker_confirmed"] = False
    return replay


def _stored_rows(session: Session) -> list[PaperAccountEvent]:
    return list(session.scalars(select(PaperAccountEvent).order_by(PaperAccountEvent.occurred_at, PaperAccountEvent.event_id)).all())


def _lock(session: Session) -> None:
    session.execute(text("SELECT pg_advisory_xact_lock(:namespace, 1)"), {"namespace": JOURNAL_LOCK_NAMESPACE})


def _abort(session: Session, *, commit: bool) -> None:
    if commit:
        session.rollback()


def _basis(value: object) -> Decimal | None:
    if value is None:
        return None
    return decimal_or_none(value)


def _same_basis(stored: Decimal | None, basis: Decimal | None) -> bool:
    if stored is None and basis is None:
        return True
    if stored is None or basis is None:
        return False
    return stored == basis


def _payload(event: dict) -> dict:
    body = dict(event)
    for key in ("occurred_at", "statement_as_of"):
        if isinstance(body.get(key), datetime):
            body[key] = body[key].isoformat()
    return body


def _closed(code: str, **extra) -> dict:
    return {
        "code": code,
        "recorded": False,
        "applied": False,
        "ledger_applied": False,
        "broker_confirmed": False,
        "fill": None,
        **extra,
    }
