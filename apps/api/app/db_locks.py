"""One lock order for operational rows and paper intents.

PostgreSQL advisory locks are reentrant inside a transaction and end on
commit or rollback. The operational lock is a constant key in its own
namespace so it cannot collide with hashtext(intent_id).

Order, for every writer:
1. pg_advisory_xact_lock(841105, 1)
2. pg_advisory_xact_lock(841104, hashtext(intent_id)), when the work names an intent
3. ops_state id 1 FOR UPDATE, when that row is read or written
4. the risk_sessions row FOR UPDATE, when that date is read or written

A missing row is not inserted by a reader. The advisory lock is what stops
another transaction from inserting it until this transaction ends.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain.tables import OpsState, RiskSession

OPERATIONAL_LOCK_NAMESPACE = 841105
INTENT_LOCK_NAMESPACE = 841104


def lock_operational(session: Session) -> None:
    """Serialize ops_state and risk_sessions, including inserts of missing rows."""
    session.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, 1)"),
        {"namespace": OPERATIONAL_LOCK_NAMESPACE},
    )


def lock_intent(session: Session, intent_id: str) -> None:
    """Take the operational lock, then the intent lock. Never the reverse."""
    lock_operational(session)
    session.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, hashtext(:intent_id))"),
        {"namespace": INTENT_LOCK_NAMESPACE, "intent_id": intent_id},
    )


def lock_ops_row(session: Session) -> OpsState | None:
    """Lock the kill-switch row when it exists. A missing row stays missing."""
    lock_operational(session)
    return session.execute(select(OpsState).where(OpsState.id == 1).with_for_update()).scalar_one_or_none()


def lock_session_row(session: Session, session_date: date) -> RiskSession | None:
    """Lock one ledger row when it exists. A missing date stays missing."""
    lock_operational(session)
    return session.execute(
        select(RiskSession).where(RiskSession.session_date == session_date).with_for_update()
    ).scalar_one_or_none()
