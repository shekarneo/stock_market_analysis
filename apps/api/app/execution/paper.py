"""Paper state machine. Paper trading is not activated, and fills are not applied.

This module does not import the live order function or a broker client.
A transition that the specification names but this milestone cannot perform
is recorded as not applied. An unnamed transition is rejected and audited.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_locks import lock_intent
from app.domain.tables import AuditEvent, PaperTransition

PAPER_TRADING_ACTIVE = False
ALLOWED = frozenset(
    {
        ("PROPOSED", "RISK_APPROVED"),
        ("PROPOSED", "VETOED"),
        ("RISK_APPROVED", "AWAITING_APPROVAL"),
        ("RISK_APPROVED", "SUBMITTED"),
        ("AWAITING_APPROVAL", "SUBMITTED"),
        ("SUBMITTED", "PENDING"),
        ("SUBMITTED", "OPEN"),
        ("SUBMITTED", "UNKNOWN_REQUIRES_RECONCILIATION"),
        ("PENDING", "PARTIALLY_FILLED"),
        ("PENDING", "FILLED"),
        ("PENDING", "CANCELLED"),
        ("PENDING", "REJECTED"),
        ("OPEN", "PARTIALLY_FILLED"),
        ("OPEN", "FILLED"),
        ("OPEN", "CANCELLED"),
        ("OPEN", "REJECTED"),
        ("PARTIALLY_FILLED", "FILLED"),
        ("PARTIALLY_FILLED", "CANCELLED"),
        ("FILLED", "EXIT_PENDING"),
        ("EXIT_PENDING", "CLOSED"),
    }
)
_NOT_AVAILABLE = frozenset(
    {
        "SUBMITTED",
        "PENDING",
        "OPEN",
        "PARTIALLY_FILLED",
        "FILLED",
        "EXIT_PENDING",
        "CLOSED",
        "UNKNOWN_REQUIRES_RECONCILIATION",
        "AWAITING_APPROVAL",
    }
)
_FLAGS = {
    "forecast_ready": False,
    "paper_approved": False,
    "live_approved": False,
    "real_market_data_verified": False,
    "executable": False,
    "market_fill": False,
    "live_routed": False,
}


class PaperTransitionError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def open_intent(
    session: Session,
    intent_id: str,
    *,
    occurred_at: datetime,
    snapshot: dict | None = None,
    actor: str = "paper",
    commit: bool = True,
) -> dict:
    """Commit PROPOSED. A snapshot is stored in the same transaction when supplied."""
    if not isinstance(intent_id, str) or not intent_id.strip() or _aware(occurred_at) is None:
        _abort(session, commit=commit)
        return _result("INVALID_INTENT", applied=False, state=None)
    lock_intent(session, intent_id)
    if current_state(session, intent_id) is not None:
        _abort(session, commit=commit)
        return _result("DUPLICATE_INTENT", applied=False, state=current_state(session, intent_id))
    _write(session, intent_id, "NONE", "PROPOSED", occurred_at, "OPENED", applied=True)
    already_stored = session.scalar(
        select(AuditEvent.id).where(
            AuditEvent.entity == f"paper_intent:{intent_id}",
            AuditEvent.action == "paper.simulation_request",
        ).limit(1)
    )
    if snapshot is not None and already_stored is None:
        session.add(
            AuditEvent(
                actor=actor,
                action="paper.simulation_request",
                entity=f"paper_intent:{intent_id}",
                before=None,
                after=snapshot,
                created_at=datetime.now(timezone.utc),
            )
        )
    _finish_tx(session, commit=commit)
    return _result("PROPOSED", applied=True, state="PROPOSED")


def transition(
    session: Session,
    intent_id: str,
    to_state: str,
    *,
    occurred_at: datetime,
    reason: str,
    risk_passed: bool = False,
    commit: bool = True,
) -> dict:
    """Move one paper intent. Submission and fills stay unavailable."""
    if _aware(occurred_at) is None or not isinstance(reason, str) or not reason.strip():
        _abort(session, commit=commit)
        return _result("INVALID_TRANSITION", applied=False, state=None)
    lock_intent(session, intent_id)
    current = current_state(session, intent_id)
    if current is None:
        _abort(session, commit=commit)
        return _result("INVALID_TRANSITION", applied=False, state=None)
    if current == "VETOED" and to_state == "VETOED":
        return _result("VETOED", applied=False, state="VETOED")
    pair = (current, to_state)
    if pair not in ALLOWED:
        session.add(
            AuditEvent(
                actor="paper",
                action="paper.illegal_transition",
                entity=f"paper_intent:{intent_id}",
                before={"state": current},
                after={"to_state": to_state, "reason": reason},
                created_at=datetime.now(timezone.utc),
            )
        )
        _finish_tx(session, commit=commit)
        raise PaperTransitionError("ILLEGAL_TRANSITION")
    if to_state == "RISK_APPROVED":
        _write(session, intent_id, current, to_state, occurred_at, "RISK_NOT_PASSED", applied=False)
        _finish_tx(session, commit=commit)
        return _result("RISK_NOT_PASSED", applied=False, state=current)
    if to_state in _NOT_AVAILABLE or not PAPER_TRADING_ACTIVE:
        code = "PAPER_FILL_UNAVAILABLE" if to_state in {"FILLED", "PARTIALLY_FILLED", "CLOSED"} else "PAPER_NOT_ACTIVATED"
        if to_state == "VETOED":
            _write(session, intent_id, current, to_state, occurred_at, reason, applied=True)
            _finish_tx(session, commit=commit)
            return _result("VETOED", applied=True, state="VETOED")
        _write(session, intent_id, current, to_state, occurred_at, code, applied=False)
        _finish_tx(session, commit=commit)
        return _result(code, applied=False, state=current)
    _write(session, intent_id, current, to_state, occurred_at, reason, applied=True)
    _finish_tx(session, commit=commit)
    return _result(to_state, applied=True, state=to_state)


def _finish_tx(session: Session, *, commit: bool) -> None:
    """Commit a standalone call. A caller-owned transaction is only flushed."""
    if commit:
        session.commit()
    else:
        session.flush()


def _abort(session: Session, *, commit: bool) -> None:
    """Roll back a standalone call. A caller-owned transaction is left to the caller."""
    if commit:
        session.rollback()


def submit_paper(intent: dict) -> dict:
    """Refuse paper submission. No live function is called."""
    return {
        "status": "UNAVAILABLE",
        "reason": "PAPER_NOT_ACTIVATED",
        "fill": None,
        "simulated_fill": None,
        **_FLAGS,
    }


def current_state(session: Session, intent_id: str) -> str | None:
    rows = session.scalars(
        select(PaperTransition)
        .where(PaperTransition.intent_id == intent_id, PaperTransition.applied.is_(True))
        .order_by(PaperTransition.id)
    ).all()
    if not rows:
        return None
    return rows[-1].to_state


def _write(session: Session, intent_id: str, from_state: str, to_state: str, occurred_at: datetime, reason: str, *, applied: bool) -> None:
    session.add(
        PaperTransition(
            intent_id=intent_id,
            from_state=from_state,
            to_state=to_state,
            occurred_at=_aware(occurred_at),
            reason=reason,
            applied=applied,
            created_at=datetime.now(timezone.utc),
        )
    )


def _aware(value: datetime) -> datetime | None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return None
    return value.astimezone(timezone.utc)


def _result(detail: str, *, applied: bool, state: str | None) -> dict:
    return {"applied": applied, "detail": detail, "state": state, **_FLAGS}
