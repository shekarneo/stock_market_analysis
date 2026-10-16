"""Read-only research projection of the paper-accounting journal.

The projection replays committed rows. It does not read or write the
operational ledger, and it is not an active paper account.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

from sqlalchemy.orm import Session

from app.execution.paper import PAPER_TRADING_ACTIVE
from app.risk.account_journal import _stored_rows
from app.risk.money import decimal_or_none
from app.risk.paper_accounting import replay_paper_accounts

PROJECTION_VERSION = "paper-account-projection-1"
_CHARGE_EVENTS = frozenset({"FILL", "PARTIAL_FILL", "CHARGE_ASSESSMENT", "CHARGE_CORRECTION"})


def project_journal(session: Session) -> dict:
    """Project the committed journal. The session is not flushed or committed here."""
    rows = _stored_rows(session)
    opening = None if not rows or rows[0].opening_cash_inr is None else str(rows[0].opening_cash_inr)
    replay = replay_paper_accounts([row.payload for row in rows], opening_cash=opening)
    return _project(replay, rows)


def _project(replay: dict, rows: list) -> dict:
    rejected = replay.get("rejected") or []
    first = rejected[0] if rejected else None
    applied = set(replay.get("applied_event_ids") or [])
    payloads = [row.payload for row in rows if isinstance(row.payload, dict)]
    return {
        "role": "research_projection",
        "projection_version": PROJECTION_VERSION,
        "journal_identity": _identity(rows),
        "event_ids": [row.event_id for row in rows],
        "active_paper_account": False,
        "paper_trading_active": PAPER_TRADING_ACTIVE,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
        "live_trading_enabled": False,
        "ledger_applied": False,
        "broker_called": False,
        "broker_confirmed": False,
        "cash": _cash(replay, rows),
        "charges": _charges(replay, payloads, applied),
        "open_premium": _premium(replay),
        "positions": _positions(replay),
        "pnl": {"status": "unavailable", "value": None},
        "stopped": replay.get("stopped") is True,
        "stop_reason": replay.get("stop_reason"),
        "first_invalid_event": first,
        "discrepancies": list(replay.get("discrepancies") or []),
        "discrepancies_do_not_adjust_balances": True,
    }


def _cash(replay: dict, rows: list) -> dict:
    if not rows:
        return {"status": "unavailable", "value": None}
    if replay.get("cash_inr") is None:
        return {"status": "unknown", "value": None}
    return {"status": "known", "value": replay["cash_inr"]}


def _charges(replay: dict, payloads: list[dict], applied: set[str]) -> dict:
    seen = [item for item in payloads if item.get("event_id") in applied and item.get("event_type") in _CHARGE_EVENTS]
    if any(item.get("event_type") in {"FILL", "PARTIAL_FILL"} and item.get("charges_inr") is None for item in seen):
        return {"status": "unknown", "value": None}
    explicit = [item for item in seen if item.get("charges_inr") is not None or item.get("event_type") in {"CHARGE_ASSESSMENT", "CHARGE_CORRECTION"}]
    if not explicit:
        return {"status": "unavailable", "value": None}
    if replay.get("charges_booked_inr") is None or replay.get("charges_known") is False:
        return {"status": "unknown", "value": None}
    return {"status": "known", "value": replay["charges_booked_inr"]}


def _premium(replay: dict) -> dict:
    positions = replay.get("positions")
    if not isinstance(positions, list) or not replay.get("applied_fill_ids"):
        return {"status": "unavailable", "value": None}
    total = Decimal("0")
    for row in positions:
        amount = None if not isinstance(row, dict) else decimal_or_none(row.get("open_premium_inr"))
        if amount is None:
            return {"status": "unknown", "value": None}
        total += amount
    return {"status": "known", "value": format(total.normalize(), "f")}


def _positions(replay: dict) -> dict:
    positions = replay.get("positions")
    if not isinstance(positions, list):
        return {"status": "unavailable", "value": None}
    if not replay.get("applied_event_ids"):
        return {"status": "unavailable", "value": None}
    return {"status": "known", "value": positions}


def _identity(rows: list) -> str:
    raw = "\n".join(f"{row.event_id}:{row.body_hash}" for row in rows)
    return hashlib.sha256(raw.encode()).hexdigest()
