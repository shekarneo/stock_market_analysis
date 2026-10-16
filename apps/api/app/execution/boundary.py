"""Validation boundary for a simulated fill. It does not apply one.

The caller cannot supply approval, a risk pass, a trusted price, or lineage.
The only inputs that identify the decision are the stored simulation snapshot
and the first completed decision attempt. Fill application is unreachable:
paper trading is inactive, and the intent advisory lock does not lock
ops_state or risk_sessions.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.tables import AuditEvent, PaperTransition, RiskEvent, RiskSession
from app.execution.paper import PAPER_TRADING_ACTIVE, lock_intent
from app.execution.simulation import _stored_request
from app.risk.money import decimal_or_none

_FLAGS = {
    "forecast_ready": False,
    "paper_approved": False,
    "live_approved": False,
    "real_market_data_verified": False,
    "live_trading_enabled": False,
    "executable": False,
    "market_fill": False,
    "live_routed": False,
}
_IGNORED = ("paper_approved", "live_approved", "real_market_data_verified", "forecast_ready", "live_trading_enabled", "risk_passed", "passed")
_IDENTITY = ("underlying", "expiry", "strike", "option_type")
_CLEAR_GATE_STATES = frozenset({"PASS", "NOT_APPLICABLE"})


def propose_simulated_fill(session: Session, event: object, *, actor: str, commit: bool = True) -> dict:
    """Refuse one simulated fill. No ledger row, cash change, or position is written."""
    structural = _structural(event)
    if structural is not None:
        return _refused(structural, reasons=[structural], recorded=False)
    payload = event if isinstance(event, dict) else {}
    intent_id = payload["intent_id"].strip()
    lock_intent(session, intent_id)
    digest = _payload_hash(payload)
    prior = _prior(session, payload["event_id"])
    if prior is not None:
        code = "DUPLICATE_EVENT" if prior.get("payload_hash") == digest else "DUPLICATE_EVENT_CONFLICT"
        reasons = list(prior.get("reasons") or [code])
        if code not in reasons:
            reasons.append(code)
        return _refused(code, reasons=reasons, recorded=True, payload_hash=prior.get("payload_hash"))
    stored = _stored_request(session, intent_id)
    decision = _decision(session, intent_id)
    reasons = _reasons(session, payload, stored, decision)
    if "EXECUTION_DISABLED" not in reasons:
        reasons.append("EXECUTION_DISABLED")
    code = _code(reasons)
    _record(session, actor, intent_id, payload["event_id"], digest, code, reasons)
    try:
        if commit:
            session.commit()
        else:
            session.flush()
    except Exception:
        if not commit:
            raise
        session.rollback()
        return _refused("EXECUTION_INTERRUPTED", reasons=["EXECUTION_INTERRUPTED"], recorded=False, payload_hash=digest)
    return _refused(code, reasons=reasons, recorded=commit, payload_hash=digest)


def _structural(event: object) -> str | None:
    if not isinstance(event, dict):
        return "INVALID_EVENT"
    if event.get("event_type") != "SIMULATED_FILL":
        return "INVALID_EVENT_TYPE"
    if not isinstance(event.get("event_id"), str) or not event["event_id"].strip():
        return "INVALID_EVENT_ID"
    if not isinstance(event.get("intent_id"), str) or not event["intent_id"].strip():
        return "INVALID_INTENT_ID"
    return None


def _reasons(session: Session, event: dict, stored: dict | None, decision: dict | None) -> list[str]:
    reasons: list[str] = []
    if any(event.get(name) is True for name in _IGNORED):
        reasons.append("IGNORED_CALLER_FLAG")
    if _snapshot_conflict(session, event["intent_id"].strip()):
        reasons.append("SNAPSHOT_CONFLICT")
    if stored is None:
        reasons.append("SNAPSHOT_MISSING")
    elif event.get("body_hash") != stored.get("body_hash"):
        reasons.append("STALE_DECISION")
    if decision is None:
        reasons.append("DECISION_MISSING")
    else:
        if event.get("decision_audit_id") != decision.get("audit_id"):
            reasons.append("STALE_DECISION")
        if decision.get("code") != "VETOED" and decision.get("reasons"):
            reasons.append("STORED_DECISION_NOT_PASS")
        if decision.get("code") != "RISK_PASSED_FILL_UNAVAILABLE":
            reasons.append("STORED_DECISION_NOT_PASS")
        gates = decision.get("gates")
        if not isinstance(gates, list) or not gates or any(not isinstance(gate, dict) or gate.get("state") not in _CLEAR_GATE_STATES for gate in gates):
            reasons.append("GATES_NOT_PASSED")
    reasons.extend(_contract_reasons(event, stored))
    reasons.extend(_prerequisite_reasons(stored, decision))
    if not PAPER_TRADING_ACTIVE:
        reasons.append("EXECUTION_DISABLED")
    return list(dict.fromkeys(reasons))


def _contract_reasons(event: dict, stored: dict | None) -> list[str]:
    reasons = []
    intent = stored.get("risk_intent") if isinstance(stored, dict) and isinstance(stored.get("risk_intent"), dict) else None
    if event.get("side") not in {"BUY", "SELL"}:
        reasons.append("INVALID_SIDE")
    if _aware(event.get("occurred_at")) is None:
        reasons.append("INVALID_TIMESTAMP")
    quantity = decimal_or_none(event.get("quantity"))
    if quantity is None or quantity <= 0:
        reasons.append("INVALID_QUANTITY")
    price = decimal_or_none(event.get("price"))
    if price is None or price <= 0:
        reasons.append("INVALID_PRICE")
    if not isinstance(event.get("price_source"), str) or not event["price_source"].strip():
        reasons.append("MISSING_PRICE_SOURCE")
    else:
        reasons.append("PRICE_SOURCE_UNVERIFIED")
    if "charges_inr" not in event or event.get("charges_inr") is None:
        reasons.append("CHARGES_UNKNOWN")
    elif decimal_or_none(event.get("charges_inr")) is None:
        reasons.append("INVALID_CHARGES")
    else:
        reasons.append("CHARGES_UNVERIFIED")
    if "slippage_inr" not in event or event.get("slippage_inr") is None:
        reasons.append("SLIPPAGE_UNKNOWN")
    elif decimal_or_none(event.get("slippage_inr")) is None:
        reasons.append("INVALID_SLIPPAGE")
    tick = event.get("tick_size", None if intent is None else intent.get("tick_size"))
    if tick in (None, ""):
        reasons.append("TICK_SIZE_MISSING")
    elif decimal_or_none(tick) is None or decimal_or_none(tick) <= 0:
        reasons.append("INVALID_TICK_SIZE")
    else:
        reasons.append("TICK_UNIT_UNVERIFIED")
    if intent is not None and "tick_size" in event and _text(event.get("tick_size")) != _text(intent.get("tick_size")):
        reasons.append("TICK_CONFLICT")
    lot = event.get("lot_size", None if intent is None else intent.get("lot_size"))
    lot_number = decimal_or_none(lot)
    if lot in (None, ""):
        reasons.append("LOT_SIZE_UNVERIFIED")
    elif lot_number is None or lot_number <= 0:
        reasons.append("INVALID_LOT_SIZE")
    elif quantity is not None and quantity > 0 and quantity % lot_number != 0:
        reasons.append("INVALID_QUANTITY")
    if intent is not None and "lot_size" in event and _text(event.get("lot_size")) != _text(intent.get("lot_size")):
        reasons.append("LOT_CONFLICT")
    if intent is None:
        reasons.append("IDENTITY_NOT_STORED")
    else:
        for field in _IDENTITY:
            if _text(event.get(field)) != _text(intent.get(field)):
                reasons.append("IDENTITY_MISMATCH")
                break
    supplied_lineage = event.get("lineage")
    stored_lineage = stored.get("lineage") if isinstance(stored, dict) else None
    if isinstance(supplied_lineage, dict):
        if not isinstance(stored_lineage, dict) or supplied_lineage != stored_lineage:
            reasons.append("LINEAGE_CONFLICT")
    if isinstance(stored_lineage, dict) and stored_lineage.get("origin") == "UNVERIFIED_PROVIDER":
        reasons.append("UNVERIFIED_LINEAGE")
    if isinstance(stored_lineage, dict) and stored_lineage.get("market_data_verified") is True:
        reasons.append("IGNORED_CALLER_FLAG")
    return reasons


def _prerequisite_reasons(stored: dict | None, decision: dict | None) -> list[str]:
    reasons = []
    inputs = decision.get("evaluator_inputs") if isinstance(decision, dict) else None
    if not isinstance(inputs, dict) or inputs.get("risk_capital_inr") is None:
        reasons.append("MISSING_RISK_CAPITAL")
    operational = decision.get("operational_state") if isinstance(decision, dict) else None
    funds = operational.get("funds") if isinstance(operational, dict) and isinstance(operational.get("funds"), dict) else None
    if not isinstance(funds, dict) or funds.get("paper_cash_known") is not True:
        reasons.append("CASH_UNKNOWN")
    position = operational.get("position") if isinstance(operational, dict) and isinstance(operational.get("position"), dict) else None
    if not isinstance(position, dict) or position.get("status") != "known" or position.get("lockout_active") is None:
        reasons.append("SESSION_STATE_UNAVAILABLE")
    elif position.get("lockout_active") is True:
        reasons.append("DAILY_LOSS_LOCKOUT")
    reasons.append("RECONCILIATION_UNAVAILABLE")
    return reasons


def _code(reasons: list[str]) -> str:
    preferred = (
        "SNAPSHOT_MISSING",
        "SNAPSHOT_CONFLICT",
        "DECISION_MISSING",
        "STALE_DECISION",
        "IDENTITY_MISMATCH",
        "INVALID_SIDE",
        "INVALID_TIMESTAMP",
        "INVALID_QUANTITY",
        "INVALID_PRICE",
        "INVALID_TICK_SIZE",
        "INVALID_LOT_SIZE",
        "INVALID_CHARGES",
        "INVALID_SLIPPAGE",
        "EXECUTION_DISABLED",
    )
    for name in preferred:
        if name in reasons:
            return name
    return reasons[0]


def _decision(session: Session, intent_id: str) -> dict | None:
    rows = session.scalars(
        select(AuditEvent)
        .where(AuditEvent.entity == f"paper_intent:{intent_id}", AuditEvent.action == "paper.simulation")
        .order_by(AuditEvent.id.asc())
    ).all()
    for row in rows:
        after = row.after if isinstance(row.after, dict) else {}
        if after.get("decision_attempt") is True:
            return {"audit_id": row.id, **after}
    return None


def _snapshot_conflict(session: Session, intent_id: str) -> bool:
    rows = session.scalars(
        select(AuditEvent)
        .where(AuditEvent.entity == f"paper_intent:{intent_id}", AuditEvent.action == "paper.simulation_request")
        .order_by(AuditEvent.id.asc())
    ).all()
    hashes = [row.after.get("body_hash") for row in rows if isinstance(row.after, dict) and isinstance(row.after.get("body_hash"), str)]
    return len(rows) > 1 or len(set(hashes)) > 1


def _prior(session: Session, event_id: str) -> dict | None:
    rows = session.scalars(select(AuditEvent).where(AuditEvent.action == "paper.execution_refused").order_by(AuditEvent.id.asc())).all()
    for row in rows:
        after = row.after if isinstance(row.after, dict) else {}
        if after.get("event_id") == event_id:
            return after
    return None


def _record(session: Session, actor: str, intent_id: str, event_id: str, digest: str, code: str, reasons: list[str]) -> None:
    session.add(
        AuditEvent(
            actor=actor,
            action="paper.execution_refused",
            entity=f"paper_intent:{intent_id}",
            before=None,
            after={
                "schema": "simulated-fill-refusal-1",
                "event_id": event_id,
                "payload_hash": digest,
                "code": code,
                "reasons": list(reasons),
                "applied": False,
                "fill": None,
                "simulated_fill": None,
                "financial_mutation": False,
            },
            created_at=datetime.now(timezone.utc),
        )
    )


def _payload_hash(event: dict) -> str:
    body = {
        "event_type": event.get("event_type"),
        "event_id": event.get("event_id"),
        "intent_id": event.get("intent_id").strip() if isinstance(event.get("intent_id"), str) else None,
        "decision_audit_id": event.get("decision_audit_id"),
        "body_hash": event.get("body_hash"),
        "side": event.get("side"),
        "underlying": _text(event.get("underlying")),
        "expiry": _text(event.get("expiry")),
        "strike": _text(event.get("strike")),
        "option_type": _text(event.get("option_type")),
        "quantity": _text(event.get("quantity")),
        "price": _text(event.get("price")),
        "occurred_at": None if _aware(event.get("occurred_at")) is None else _aware(event.get("occurred_at")).isoformat(),
        "price_source": event.get("price_source"),
        "charges_inr": None if "charges_inr" not in event or event.get("charges_inr") is None else _text(event.get("charges_inr")),
        "slippage_inr": None if "slippage_inr" not in event or event.get("slippage_inr") is None else _text(event.get("slippage_inr")),
        "tick_size": None if "tick_size" not in event else _text(event.get("tick_size")),
        "lot_size": None if "lot_size" not in event else _text(event.get("lot_size")),
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _refused(code: str, *, reasons: list[str], recorded: bool, payload_hash: str | None = None) -> dict:
    return {
        "ok": False,
        "applied": False,
        "persisted_fill": False,
        "recorded_refusal": recorded,
        "code": code,
        "reasons": reasons,
        "fill": None,
        "simulated_fill": None,
        "financial_mutation": False,
        "payload_hash": payload_hash,
        "broker_called": False,
        "order_created": False,
        **_FLAGS,
    }


def unchanged_financial_state(session: Session) -> bool:
    """True when this boundary has not created a fill or a ledger balance."""
    fills = session.scalar(
        select(RiskEvent.event_id).where(RiskEvent.event_type == "SIMULATED_FILL").limit(1)
    )
    positions = session.scalar(select(RiskSession.local_open_positions).where(RiskSession.local_open_positions != 0).limit(1))
    premium = session.scalar(select(RiskSession.open_premium_at_risk_inr).where(RiskSession.open_premium_at_risk_inr != 0).limit(1))
    applied = session.scalar(
        select(PaperTransition.id)
        .where(PaperTransition.to_state.in_(("FILLED", "PARTIALLY_FILLED", "CLOSED")), PaperTransition.applied.is_(True))
        .limit(1)
    )
    return fills is None and positions is None and premium is None and applied is None


def _aware(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return None
    return value.astimezone(timezone.utc)


def _text(value: object) -> str | None:
    number = decimal_or_none(value)
    if number is not None:
        return format(number.normalize(), "f")
    if value is None:
        return None
    return str(value)
