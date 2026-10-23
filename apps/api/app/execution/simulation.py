"""Controlled paper simulation. It does not place a broker order or record a fill.

Risk gates are the existing evaluator. A veto is stored on the paper intent.
Submission and fills stay on the M9 state machine, which does not apply them.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config.loader import load_defaults
from app.config.schemas import RiskConfig
from app.config.store import ensure_seed
from app.db_locks import lock_ops_row, lock_session_row
from app.domain.tables import AuditEvent, PaperTransition, RiskEvent
from app.execution.paper import current_state, lock_intent, open_intent, transition
from app.market.provenance import lineage_block, quarantine_training_block
from app.risk.accounting import session_pnl
from app.risk.gates import evaluate
from app.settings import REPO_ROOT, get_settings

_FLAGS = {
    "forecast_ready": False,
    "paper_approved": False,
    "live_approved": False,
    "real_market_data_verified": False,
    "live_trading_enabled": False,
    "executable": False,
    "market_fill": False,
    "live_routed": False,
    "simulated": True,
}
_CONTRACT = ("underlying", "expiry", "strike", "option_type")
_ENTRY_FIELDS = ("entry_trigger", "invalidation", "exit_plan", "time_stop")
_CONSUMED_RISK_FIELDS = (
    "risk_capital_inr",
    "max_risk_fraction_per_trade",
    "drawdown_lockout_fraction",
    "allowed_underlyings",
    "allowed_structures",
    "quote_max_age_seconds",
)


def session_loop_status() -> dict:
    """The session loop does not run. The holiday calendar is not configured."""
    config = load_defaults(REPO_ROOT / "config" / "defaults.yaml")
    reasons = []
    if config.schedule.holiday_calendar_source_id is None:
        reasons.append("HOLIDAY_CALENDAR_UNCONFIGURED")
    if config.runtime.unattended_orders is not True:
        reasons.append("UNATTENDED_ORDERS_DISABLED")
    return {"ran": False, "reasons": reasons, "entries_created": 0, **_FLAGS}


def simulated_execution_price(*, side: str, bid: object, ask: object, haircut: str, extra_tick_penalty: bool) -> dict:
    """Quote the specified paper price. This does not record a fill."""
    if extra_tick_penalty:
        return _price(None, "TICK_UNIT_UNVERIFIED")
    if haircut != "half_spread":
        return _price(None, "UNKNOWN_HAIRCUT")
    ask_price = _decimal(ask)
    bid_price = _decimal(bid)
    if side == "BUY":
        if ask_price is None or ask_price <= 0:
            return _price(None, "MISSING_ASK")
        return _price(ask_price, "BUY_AT_ASK")
    if side == "SELL":
        if ask_price is None or bid_price is None or ask_price < bid_price:
            return _price(None, "MISSING_QUOTE")
        price = bid_price - (ask_price - bid_price) / Decimal("2")
        if price <= 0:
            return _price(None, "NON_POSITIVE_SELL_PRICE")
        return _price(price, "SELL_AT_BID_MINUS_HALF_SPREAD")
    return _price(None, "UNSUPPORTED_SIDE")


def run_paper_simulation(session: Session, body: dict, *, actor: str) -> dict:
    """Run one explicit simulation. A failed check does not reserve capital or fill."""
    if body.get("confirm") is not True:
        return _finish(session, actor, None, "CONFIRMATION_REQUIRED", ["CONFIRMATION_REQUIRED"], state=None, risk=None)
    if body.get("mode") not in {None, "PAPER"}:
        return _finish(session, actor, None, "MODE_NOT_PAPER", ["MODE_NOT_PAPER"], state=None, risk=None)
    if body.get("paper_approved") is True or body.get("live_approved") is True or body.get("real_market_data_verified") is True:
        return _finish(session, actor, None, "APPROVAL_FLAG_IGNORED", ["APPROVAL_FLAG_IGNORED"], state=None, risk=None)
    from app.risk.external_halt import external_halt_status

    halt = external_halt_status()
    if halt["halted"]:
        # Checked before any intent is opened, so a halted desk creates nothing
        return _finish(session, actor, None, "EXTERNAL_HALT", ["EXTERNAL_HALT", *halt["reasons"]], state=None, risk=None)
    dataset = body.get("dataset") if isinstance(body.get("dataset"), dict) else None
    if not isinstance(dataset, dict):
        return _finish(session, actor, None, "LINEAGE_MISSING", ["LINEAGE_MISSING"], state=None, risk=None)
    quarantined = quarantine_training_block(dataset)
    if quarantined is not None:
        return _finish(session, actor, None, quarantined[0], [quarantined[0]], state=None, risk=None)
    lineage = lineage_block(dataset)
    if lineage is not None:
        return _finish(session, actor, None, lineage[0], [lineage[0]], state=None, risk=None)
    missing = [name for name in _CONTRACT if not body.get(name)]
    if missing:
        return _finish(session, actor, None, "INCOMPLETE_CONTRACT", [f"MISSING_{name.upper()}" for name in missing], state=None, risk=None)
    intent_id = body.get("intent_id")
    occurred_at = body.get("occurred_at")
    if not isinstance(intent_id, str) or not isinstance(occurred_at, datetime):
        return _finish(session, actor, None, "INVALID_INTENT", ["INVALID_INTENT"], state=None, risk=None)
    # Never trust client-sent grants or EV; compute both from server state
    body = {key: value for key, value in body.items() if not str(key).startswith("_")}
    if body.get("execution_context") == "EXPERIMENTAL":
        body["_experimental_granted"] = _server_experimental(session)
    body["_server_expected_net"], body["_expected_net_basis"] = _server_expected_net(session, body)
    snapshot = _snapshot(body, occurred_at)
    if snapshot is None:
        return _finish(session, actor, intent_id, "INVALID_INTENT", ["INVALID_INTENT"], state=None, risk=None)
    existing = current_state(session, intent_id)
    if existing is None:
        opened = open_intent(session, intent_id, occurred_at=occurred_at, snapshot=snapshot, actor=actor)
        if opened["detail"] == "PROPOSED" and opened["applied"] is True:
            return _evaluate_stored(session, actor, intent_id, snapshot, recovery=False)
        existing = current_state(session, intent_id)
        if existing is None:
            return _finish(session, actor, intent_id, opened["detail"], [opened["detail"]], state=opened["state"], risk=None)
    return _recover(session, actor, intent_id, snapshot, existing)


def reconcile_intent(session: Session, intent_id: str) -> dict:
    """Compare local paper state with ledger reservations. No broker is read."""
    state = current_state(session, intent_id)
    fills = session.scalar(
        select(func.count())
        .select_from(PaperTransition)
        .where(
            PaperTransition.intent_id == intent_id,
            PaperTransition.applied.is_(True),
            PaperTransition.to_state.in_(("FILLED", "PARTIALLY_FILLED", "CLOSED")),
        )
    )
    reserves = session.scalar(select(func.count()).select_from(RiskEvent).where(RiskEvent.intent_id == intent_id))
    consistent = state in {None, "PROPOSED", "VETOED"} and fills == 0 and reserves == 0
    return {
        "consistent": consistent,
        "state": state,
        "applied_fills": fills,
        "ledger_events": reserves,
        "broker_orders": 0,
        "pnl": session_pnl(realized_pnl=None, unrealized_mark_value=None, charges_booked=None, exit_charges=None),
        **_FLAGS,
    }


def _server_expected_net(session: Session, body: dict) -> tuple[str | None, str]:
    """(expected_net, basis). The server's own EV, never the client's number.

    The EV module refuses to turn a direction probability into a premium, so today it
    returns no expected net and the expected_net gate vetoes. Only an operator config of
    experimental_requires_server_ev=false lets the client figure through, labelled as such.
    """
    from app.config.store import current_config
    from app.options.expected_value import evaluate_expected_value

    quote = body.get("quote") if isinstance(body.get("quote"), dict) else {}
    contract = {
        "underlying": body.get("underlying"),
        "expiry": body.get("expiry"),
        "strike": body.get("strike"),
        "option_type": body.get("option_type"),
        "bid": quote.get("bid"),
        "ask": quote.get("ask"),
        "quote_timestamp": quote.get("quote_timestamp"),
        "lot_size": body.get("lot_size"),
    }
    ev = evaluate_expected_value(body.get("forecast"), contract, None)
    if ev.get("expected_net") is not None:
        return str(ev["expected_net"]), "SERVER_EV"
    try:
        requires_server = current_config(session).risk.experimental_requires_server_ev
    except Exception:
        requires_server = True
    if not requires_server and body.get("expected_net") is not None:
        return str(body["expected_net"]), "CLIENT_SUPPLIED_OPERATOR_ALLOWED"
    reasons = ",".join((ev.get("reasons") or [])[:3]) or "UNAVAILABLE"
    return None, f"SERVER_EV_UNAVAILABLE:{reasons}"


def _server_experimental(session: Session) -> bool:
    """Experimental paper gates are granted only when the operator's own config allows them:
    PAPER mode, kill switch off, and every virtual risk control configured."""
    from app.config.store import current_config
    from app.risk.ledger import read_kill_switch

    from app.risk.external_halt import external_halt_status

    if external_halt_status()["halted"]:
        return False
    try:
        config = current_config(session)
    except Exception:
        return False
    risk = config.risk
    configured = (
        risk.risk_capital_inr is not None and float(risk.risk_capital_inr) > 0
        and risk.max_open_positions is not None and risk.max_open_positions > 0
        and risk.max_risk_fraction_per_trade is not None and risk.max_risk_fraction_per_trade > 0
        and risk.daily_loss_fraction is not None and risk.daily_loss_fraction > 0
    )
    return config.runtime.mode.value == "PAPER" and not bool(read_kill_switch(session)) and configured


def _risk_intent(body: dict) -> dict:
    quote = body.get("quote") if isinstance(body.get("quote"), dict) else None
    return {
        "mode": "PAPER",
        "intent_purpose": "ENTRY",
        "underlying": body.get("underlying"),
        "expiry": body.get("expiry"),
        "strike": body.get("strike"),
        "option_type": body.get("option_type"),
        "quote": quote,
        "forecast": body.get("forecast"),
        # expected_net is the server's figure; the client's number is only recorded
        "expected_net": body.get("_server_expected_net"),
        "expected_net_basis": body.get("_expected_net_basis"),
        "expected_net_client": body.get("expected_net"),
        "ask": None if quote is None else quote.get("ask"),
        "bid": None if quote is None else quote.get("bid"),
        "lots": body.get("lots"),
        "lot_size": body.get("lot_size"),
        "tick_size": body.get("tick_size"),
        "charges_per_lot": body.get("charges_per_lot"),
        "session_date": body.get("session_date"),
        "master": body.get("master"),
        "entry_plan": _entry_plan(body.get("entry_plan")),
        # What the client asked for is recorded; whether it is granted is decided server-side
        "execution_context": body.get("execution_context"),
        "experimental_requested": body.get("execution_context") == "EXPERIMENTAL",
        "experimental_granted": bool(body.get("_experimental_granted")),

        "side": body.get("side", "BUY"),
    }


def _finish(
    session: Session,
    actor: str,
    intent_id: str | None,
    code: str,
    reasons: list[str],
    *,
    state: str | None,
    risk: dict | None,
    decision_attempt: bool = False,
    duplicate_request: bool = False,
    input_conflict: bool = False,
    recovery: bool = False,
    presented_body_hash: str | None = None,
    evaluator_inputs: dict | None = None,
    simulated_fill: dict | None = None,
) -> dict:
    stored = None if intent_id is None else _stored_request(session, intent_id)
    lineage = stored.get("lineage") if isinstance(stored, dict) else None
    result = {
        "ok": code == "SIMULATED_FILL_APPLIED",
        "completed": True,
        "code": code,
        "reasons": reasons,
        "state": state,
        "intent_id": intent_id,
        "decision": "TRADE" if code == "SIMULATED_FILL_APPLIED" else ("NO_TRADE" if risk is None else risk["decision"]),
        "risk_result": None if risk is None else risk["result"],
        "simulated_fill": simulated_fill,
        "fill": None,
        "order_created": False,
        "broker_called": False,
        "lineage": lineage if isinstance(lineage, dict) else None,
        **_FLAGS,
    }
    after = {
        "code": code,
        "reasons": list(reasons),
        "state": state,
        "simulated_fill": simulated_fill,
        "broker_called": False,
        "fill": None,
        "order_created": False,
    }
    if intent_id is not None:
        lock_intent(session, intent_id)
        after.update(
            _attempt_audit(
                session,
                intent_id,
                decision_attempt=decision_attempt,
                duplicate_request=duplicate_request,
                input_conflict=input_conflict,
                recovery=recovery,
                presented_body_hash=presented_body_hash,
                risk=risk,
                evaluator_inputs=evaluator_inputs,
            )
        )
    session.add(
        AuditEvent(
            actor=actor,
            action="paper.simulation",
            entity=f"paper_intent:{intent_id or 'none'}",
            before=None,
            after=after,
            created_at=datetime.now(timezone.utc),
        )
    )
    session.commit()
    return result


def _recover(session: Session, actor: str, intent_id: str, snapshot: dict, state: str) -> dict:
    """Resume one existing intent. A different payload is not evaluated."""
    stored = _stored_request(session, intent_id)
    if stored is None:
        if state != "PROPOSED":
            return _finish(session, actor, intent_id, "INPUTS_NOT_STORED", ["INPUTS_NOT_STORED"], state=state, risk=None)
        try:
            vetoed = transition(session, intent_id, "VETOED", occurred_at=_clock_from_snapshot(snapshot), reason="INPUTS_NOT_STORED")
        except Exception:
            session.rollback()
            return _finish(session, actor, intent_id, "VETO_INTERRUPTED", ["VETO_INTERRUPTED"], state="PROPOSED", risk=None)
        return _finish(session, actor, intent_id, "INPUTS_NOT_STORED", ["INPUTS_NOT_STORED"], state=vetoed["state"], risk=None)
    if stored.get("body_hash") != snapshot["body_hash"]:
        return _finish(
            session,
            actor,
            intent_id,
            "INPUT_CONFLICT",
            ["INPUT_CONFLICT"],
            state=state,
            risk=None,
            input_conflict=True,
            presented_body_hash=snapshot.get("body_hash") if isinstance(snapshot.get("body_hash"), str) else None,
        )
    return _evaluate_stored(session, actor, intent_id, stored, recovery=True)


# Statutory charge schedules per exchange and instrument type, as fractions of turnover
# (premium turnover for options, notional for futures). Checked 2026-10-23 against the
# Zerodha exchange-charges and MCX charges pages: NSE totals include the IPFT levy
# (options 0.03503% + 0.0005%; futures 0.00173% + 0.0001%); BSE SENSEX options 0.0325%;
# MCX options 0.0418% exchange + 0.05% CTT on sells; MCX futures 0.0021% + 0.01% CTT.
# Re-check whenever SEBI or an exchange revises them.
CHARGES_REVIEWED_ON = "2026-10-23"
CHARGE_SCHEDULES: dict[tuple[str, str], dict] = {
    ("NSE", "OPTION"): {"stt_sell": "0.001", "stamp_buy": "0.00003", "exchange": "0.0003553", "verified": True, "tax_label": "STT"},
    ("BSE", "OPTION"): {"stt_sell": "0.001", "stamp_buy": "0.00003", "exchange": "0.000325", "verified": True, "tax_label": "STT"},
    ("NSE", "FUTURE"): {"stt_sell": "0.0002", "stamp_buy": "0.00002", "exchange": "0.0000183", "verified": True, "tax_label": "STT"},
    ("MCX", "OPTION"): {"stt_sell": "0.0005", "stamp_buy": "0.00003", "exchange": "0.000418", "verified": True, "tax_label": "CTT"},
    ("MCX", "FUTURE"): {"stt_sell": "0.0001", "stamp_buy": "0.00002", "exchange": "0.000021", "verified": True, "tax_label": "CTT"},
}
SEBI_FEE = Decimal("0.000001")  # Rs10 per crore
GST_RATE = Decimal("0.18")
BROKERAGE_PER_ORDER_INR = Decimal("20.00")


def charge_schedule_for(underlying: object, instrument_type: str = "OPTION") -> tuple[str, dict] | None:
    """Exchange and schedule for an underlying from the instrument master; None if unknown."""
    from app.instrument_specs import get_spec

    spec = get_spec(underlying if isinstance(underlying, str) else None)
    if spec is None:
        return None
    schedule = CHARGE_SCHEDULES.get((spec.exchange, instrument_type))
    return (spec.exchange, schedule) if schedule else None


def calculate_indian_regulatory_charges(
    *,
    side: str,
    price: Decimal,
    quantity: Decimal,
    charges_per_lot: Decimal | None = None,
    lot_size: Decimal | None = None,
    exchange: str = "NSE",
    instrument_type: str = "OPTION",
) -> dict:
    """Statutory and exchange charges for one fill on the given exchange and instrument type."""
    schedule = CHARGE_SCHEDULES.get((exchange.upper(), instrument_type.upper()))
    if schedule is None:
        raise ValueError(f"CHARGE_SCHEDULE_UNAVAILABLE: no charge schedule for {exchange} {instrument_type}.")
    turnover = (price * quantity).quantize(Decimal("0.01"))
    brokerage = BROKERAGE_PER_ORDER_INR
    is_sell = side.upper() == "SELL"
    # STT (equity derivatives) or CTT (commodity derivatives) on the sell side
    stt = (turnover * Decimal(schedule["stt_sell"])).quantize(Decimal("0.01")) if is_sell else Decimal("0.00")
    stamp_duty = (turnover * Decimal(schedule["stamp_buy"])).quantize(Decimal("0.01")) if not is_sell else Decimal("0.00")
    exchange_charges = (turnover * Decimal(schedule["exchange"])).quantize(Decimal("0.01"))
    sebi_charges = (turnover * SEBI_FEE).quantize(Decimal("0.01"))
    gst = ((brokerage + exchange_charges + sebi_charges) * GST_RATE).quantize(Decimal("0.01"))
    statutory_total = (brokerage + stt + stamp_duty + exchange_charges + sebi_charges + gst).quantize(Decimal("0.01"))
    if charges_per_lot is not None and lot_size is not None and lot_size > 0:
        lots = (quantity / lot_size).quantize(Decimal("1"))
        fallback_total = (charges_per_lot * lots).quantize(Decimal("0.01"))
        total = max(statutory_total, fallback_total)
    else:
        total = statutory_total
    return {
        "brokerage": str(brokerage),
        "stt": str(stt),
        "transaction_tax_label": schedule["tax_label"],
        "stamp_duty": str(stamp_duty),
        "exchange_charges": str(exchange_charges),
        "sebi_charges": str(sebi_charges),
        "gst": str(gst),
        "total_charges_inr": str(total),
        "exchange": exchange.upper(),
        "instrument_type": instrument_type.upper(),
        "rates_verified": bool(schedule["verified"]),
        "lot_size": str(lot_size) if lot_size is not None else None,
        "charges_per_lot": str(charges_per_lot) if charges_per_lot is not None else None,
    }


def _resolve_lot_size(explicit: object, underlying: object) -> Decimal:
    """Lot size from the request/entry, else the instrument master; never a hardcoded default."""
    from app.instrument_specs import lot_size_for

    if explicit not in (None, ""):
        return Decimal(str(explicit))
    master = lot_size_for(underlying if isinstance(underlying, str) else None)
    if master is None:
        raise ValueError(f"LOT_SIZE_UNAVAILABLE: no lot size supplied or known for underlying {underlying!r}.")
    return Decimal(master)


def _execute_simulated_paper_trade(
    session: Session,
    actor: str,
    intent_id: str,
    snapshot: dict,
    risk: dict,
    occurred_at: datetime,
    *,
    recovery: bool,
    evaluator_inputs: dict | None,
    risk_config: object,
) -> dict:
    from app.domain.tables import PaperAccountEvent
    from app.execution.paper import current_state, transition

    intent = snapshot["risk_intent"]
    side = intent.get("side", "BUY")
    bid = intent.get("bid")
    ask = intent.get("ask")
    haircut = "half_spread"
    priced = simulated_execution_price(side=side, bid=bid, ask=ask, haircut=haircut, extra_tick_penalty=False)
    if priced.get("price") is not None:
        fill_price = Decimal(str(priced["price"]))
    else:
        touch = ask if side == "BUY" else bid
        if touch is None:
            # A SELL needs a bid and a BUY needs an ask; never price a fill from nothing
            return _finish(session, actor, intent_id, "QUOTE_SIDE_UNAVAILABLE", ["QUOTE_SIDE_UNAVAILABLE"], state=current_state(session, intent_id), risk=risk)
        fill_price = Decimal(str(touch))
    lot_size = _resolve_lot_size(intent.get("lot_size"), intent.get("underlying"))
    lots = int(intent.get("lots") or 1)
    quantity = lot_size * lots
    schedule = charge_schedule_for(intent.get("underlying"), "OPTION" if intent.get("option_type") else "FUTURE")
    if schedule is None:
        return _finish(session, actor, intent_id, "CHARGE_SCHEDULE_UNAVAILABLE", ["CHARGE_SCHEDULE_UNAVAILABLE"], state=current_state(session, intent_id), risk=risk)

    charges_info = calculate_indian_regulatory_charges(
        side=side,
        price=fill_price,
        quantity=quantity,
        charges_per_lot=Decimal(str(intent["charges_per_lot"])) if intent.get("charges_per_lot") else None,
        lot_size=lot_size,
        exchange=schedule[0],
        instrument_type="OPTION" if intent.get("option_type") else "FUTURE",
    )
    total_charges = Decimal(charges_info["total_charges_inr"])

    state = current_state(session, intent_id)
    if state == "PROPOSED":
        transition(session, intent_id, "RISK_APPROVED", occurred_at=occurred_at, reason="EXPERIMENTAL_RISK_PASSED", risk_passed=True, experimental=True)
        transition(session, intent_id, "SUBMITTED", occurred_at=occurred_at, reason="EXPERIMENTAL_SUBMISSION", experimental=True)
        transition(session, intent_id, "PENDING", occurred_at=occurred_at, reason="EXPERIMENTAL_PENDING", experimental=True)
        transition(session, intent_id, "FILLED", occurred_at=occurred_at, reason="SIMULATED_FILL_APPLIED", experimental=True)
        state = "FILLED"
    elif state != "FILLED":
        if state == "SUBMITTED":
            transition(session, intent_id, "PENDING", occurred_at=occurred_at, reason="EXPERIMENTAL_PENDING", experimental=True)
            transition(session, intent_id, "FILLED", occurred_at=occurred_at, reason="SIMULATED_FILL_APPLIED", experimental=True)
        elif state == "PENDING":
            transition(session, intent_id, "FILLED", occurred_at=occurred_at, reason="SIMULATED_FILL_APPLIED", experimental=True)
        state = "FILLED"

    sim_fill = {
        "event_id": f"sim-fill-{intent_id}",
        "intent_id": intent_id,
        "side": side,
        "underlying": intent.get("underlying"),
        "expiry": intent.get("expiry"),
        "strike": intent.get("strike"),
        "option_type": intent.get("option_type"),
        "quantity": str(quantity),
        "lots": lots,
        "price": str(fill_price),
        "charges_inr": str(total_charges),
        "slippage_inr": "0.05",
        "charges_breakdown": charges_info,
        "execution_context": "EXPERIMENTAL",
        "data_provenance": "EXPERIMENTAL_UNVERIFIED_DATA",
        "live_broker_routed": False,
        "live_order_calls": 0,
        "occurred_at": occurred_at.isoformat(),
    }

    capital = Decimal(str(getattr(risk_config, "risk_capital_inr", None) or "1000000"))
    existing_event = session.get(PaperAccountEvent, f"sim-fill-{intent_id}")
    if existing_event is None:
        cost = (fill_price * quantity) + total_charges if side == "BUY" else -(fill_price * quantity) + total_charges
        session.add(
            PaperAccountEvent(
                event_id=f"sim-fill-{intent_id}",
                event_type="FILL",
                occurred_at=occurred_at,
                intent_id=intent_id,
                source="SIMULATION",
                body_hash=snapshot.get("body_hash", "0" * 64),
                opening_cash_inr=capital,
                quantity=quantity,
                price=fill_price,
                charges_inr=total_charges,
                payload=sim_fill,
                effect={
                    "applied_fill_ids": [f"sim-fill-{intent_id}"],
                    "cash_inr": str(capital - cost),
                    "position_qty": str(quantity),
                },
                ledger_applied=False,
                broker_confirmed=False,
            )
        )

    return _finish(
        session,
        actor,
        intent_id,
        "SIMULATED_FILL_APPLIED",
        [],
        state=state,
        risk=risk,
        decision_attempt=True,
        duplicate_request=recovery,
        recovery=recovery,
        evaluator_inputs=evaluator_inputs,
        simulated_fill=sim_fill,
    )


def _evaluate_stored(session: Session, actor: str, intent_id: str, snapshot: dict, *, recovery: bool) -> dict:
    """Re-run the risk gates from the stored request, then veto or apply simulated fill."""
    lock_intent(session, intent_id)
    occurred_at = _clock_from_snapshot(snapshot)
    if occurred_at is None or not isinstance(snapshot.get("risk_intent"), dict):
        state = current_state(session, intent_id)
        if state == "PROPOSED":
            try:
                vetoed = transition(session, intent_id, "VETOED", occurred_at=datetime.now(timezone.utc), reason="INPUTS_NOT_STORED")
                state = vetoed["state"]
            except Exception:
                session.rollback()
                return _finish(session, actor, intent_id, "VETO_INTERRUPTED", ["VETO_INTERRUPTED"], state="PROPOSED", risk=None)
        return _finish(session, actor, intent_id, "INPUTS_NOT_STORED", ["INPUTS_NOT_STORED"], state=state, risk=None)
    try:
        ensure_seed(session, get_settings())
    except Exception:
        session.rollback()
        return _veto(session, actor, intent_id, occurred_at, ["KILL_SWITCH_NOT_READ"], risk=None, recovery=recovery, evaluator_inputs=None)
    lock_ops_row(session)
    _lock_decision_session(session, snapshot)
    risk_config = load_defaults(REPO_ROOT / "config" / "defaults.yaml").risk
    if risk_config.risk_capital_inr is None:
        try:
            from app.config.store import current_config
            db_risk = current_config(session).risk
            if db_risk.risk_capital_inr is not None:
                risk_config = db_risk
        except Exception:
            pass
    consumed = _consumed_risk(risk_config)
    try:
        risk = evaluate(snapshot["risk_intent"], session=session, config=risk_config, calendar=None, as_of=occurred_at)
    except Exception:
        session.rollback()
        return _finish(
            session,
            actor,
            intent_id,
            "EVALUATION_INTERRUPTED",
            ["EVALUATION_INTERRUPTED"],
            state="PROPOSED",
            risk=None,
            duplicate_request=recovery,
            recovery=recovery,
        )
    if risk["passed"]:
        if snapshot.get("risk_intent", {}).get("experimental_granted") is True:
            return _execute_simulated_paper_trade(
                session,
                actor,
                intent_id,
                snapshot,
                risk,
                occurred_at,
                recovery=recovery,
                evaluator_inputs=consumed,
                risk_config=risk_config,
            )
        return _finish(
            session,
            actor,
            intent_id,
            "RISK_PASSED_FILL_UNAVAILABLE",
            ["PAPER_FILL_UNAVAILABLE"],
            state=current_state(session, intent_id),
            risk=risk,
            decision_attempt=True,
            duplicate_request=recovery,
            recovery=recovery,
            evaluator_inputs=consumed,
        )
    if current_state(session, intent_id) == "VETOED":
        return _finish(
            session,
            actor,
            intent_id,
            "VETOED",
            list(risk["reasons"]),
            state="VETOED",
            risk=risk,
            decision_attempt=True,
            duplicate_request=True,
            recovery=False,
            evaluator_inputs=consumed,
        )
    return _veto(session, actor, intent_id, occurred_at, list(risk["reasons"]), risk=risk, recovery=recovery, evaluator_inputs=consumed)


def _veto(session: Session, actor: str, intent_id: str, occurred_at: datetime, reasons: list[str], *, risk: dict | None, recovery: bool, evaluator_inputs: dict | None) -> dict:
    if current_state(session, intent_id) == "VETOED":
        return _finish(
            session,
            actor,
            intent_id,
            "VETOED",
            reasons,
            state="VETOED",
            risk=risk,
            decision_attempt=risk is not None,
            duplicate_request=True,
            recovery=False,
            evaluator_inputs=evaluator_inputs,
        )
    try:
        vetoed = transition(session, intent_id, "VETOED", occurred_at=occurred_at, reason="RISK_VETO")
    except Exception:
        session.rollback()
        if current_state(session, intent_id) == "VETOED":
            return _finish(
                session,
                actor,
                intent_id,
                "VETOED",
                reasons,
                state="VETOED",
                risk=risk,
                decision_attempt=risk is not None,
                duplicate_request=True,
                recovery=False,
                evaluator_inputs=evaluator_inputs,
            )
        return _finish(
            session,
            actor,
            intent_id,
            "VETO_INTERRUPTED",
            ["VETO_INTERRUPTED"],
            state="PROPOSED",
            risk=None,
            duplicate_request=recovery,
            recovery=recovery,
        )
    if vetoed["state"] == "VETOED" and vetoed["applied"] is False:
        return _finish(
            session,
            actor,
            intent_id,
            "VETOED",
            reasons,
            state="VETOED",
            risk=risk,
            decision_attempt=risk is not None,
            duplicate_request=True,
            recovery=False,
            evaluator_inputs=evaluator_inputs,
        )
    return _finish(
        session,
        actor,
        intent_id,
        "VETOED",
        reasons,
        state=vetoed["state"],
        risk=risk,
        decision_attempt=True,
        duplicate_request=recovery,
        recovery=recovery,
        evaluator_inputs=evaluator_inputs,
    )


def _lock_decision_session(session: Session, snapshot: dict) -> None:
    """Lock the ledger row for this decision when that date already exists."""
    intent = snapshot.get("risk_intent") if isinstance(snapshot, dict) else None
    raw = intent.get("session_date") if isinstance(intent, dict) else None
    if not isinstance(raw, str):
        return
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        return
    lock_session_row(session, day)


def _snapshot(body: dict, occurred_at: datetime) -> dict | None:
    clock = _evaluation_clock(occurred_at)
    if clock is None:
        return None
    payload = {"occurred_at": clock.isoformat(), "dataset": body.get("dataset"), "risk_intent": _risk_intent(body)}
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default)
    except TypeError:
        return None
    return {
        "body_hash": hashlib.sha256(encoded.encode()).hexdigest(),
        "occurred_at": clock.isoformat(),
        "request_occurred_at": clock.isoformat(),
        "quote_timestamp": _quote_timestamp(body),
        "lineage": _lineage_record(body.get("dataset"), body.get("forecast")),
        "risk_intent": payload["risk_intent"],
    }


def _request_rows(session: Session, intent_id: str) -> list[AuditEvent]:
    return list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity == f"paper_intent:{intent_id}", AuditEvent.action == "paper.simulation_request")
            .order_by(AuditEvent.id.asc())
        ).all()
    )


def _stored_request(session: Session, intent_id: str) -> dict | None:
    """Return the first snapshot. A later row cannot replace it."""
    rows = _request_rows(session, intent_id)
    if not rows or not isinstance(rows[0].after, dict) or not isinstance(rows[0].after.get("body_hash"), str):
        return None
    return rows[0].after


def replay_simulation_decision(session: Session, intent_id: str) -> dict:
    """Read the stored simulation. Missing fields stay missing."""
    requests = _request_rows(session, intent_id)
    snapshots = [row.after for row in requests if isinstance(row.after, dict)]
    stored = _stored_request(session, intent_id)
    hashes = [item.get("body_hash") for item in snapshots if isinstance(item.get("body_hash"), str)]
    conflict = len(requests) > 1 or len(set(hashes)) > 1
    missing: list[str] = []
    lineage = stored.get("lineage") if isinstance(stored, dict) else None
    if stored is None:
        missing.extend(["snapshot", "body_hash", "request_occurred_at", "quote_timestamp", "lineage"])
    else:
        if not isinstance(stored.get("request_occurred_at"), str) and not isinstance(stored.get("occurred_at"), str):
            missing.append("request_occurred_at")
        if not isinstance(stored.get("quote_timestamp"), str):
            missing.append("quote_timestamp")
        if not isinstance(lineage, dict):
            missing.append("lineage")
            lineage = None
        else:
            for key in ("dataset_id", "schema", "origin", "source_row_sha256", "forecast_promotion_state", "forecast_model_id"):
                if lineage.get(key) in (None, ""):
                    missing.append(f"lineage.{key}")
    attempts = []
    for row in session.scalars(
        select(AuditEvent)
        .where(AuditEvent.entity == f"paper_intent:{intent_id}", AuditEvent.action == "paper.simulation")
        .order_by(AuditEvent.id.asc())
    ).all():
        after = row.after if isinstance(row.after, dict) else {}
        if "reasons" not in after or not isinstance(after.get("reasons"), list):
            missing.append(f"attempt_reasons:{row.id}")
        if after.get("decision_attempt") is True and not isinstance(after.get("config_revision"), int):
            missing.append(f"config_revision:{row.id}")
        if after.get("decision_attempt") is True and not isinstance(after.get("gates"), list):
            missing.append(f"gates:{row.id}")
        if after.get("decision_attempt") is True and not isinstance(after.get("evaluator_inputs"), dict):
            missing.append(f"evaluator_inputs:{row.id}")
        if after.get("decision_attempt") is True and not isinstance(after.get("operational_state"), dict):
            missing.append(f"operational_state:{row.id}")
        attempts.append(
            {
                "audit_id": row.id,
                "attempt": after.get("attempt"),
                "code": after.get("code"),
                "reasons": after.get("reasons") if isinstance(after.get("reasons"), list) else None,
                "state": after.get("state"),
                "decision_attempt": after.get("decision_attempt"),
                "duplicate_request": after.get("duplicate_request"),
                "input_conflict": after.get("input_conflict"),
                "recovery": after.get("recovery"),
                "body_hash": after.get("body_hash"),
                "presented_body_hash": after.get("presented_body_hash"),
                "request_occurred_at": after.get("request_occurred_at"),
                "quote_timestamp": after.get("quote_timestamp"),
                "config_revision": after.get("config_revision") if isinstance(after.get("config_revision"), int) else None,
                "gates": after.get("gates") if isinstance(after.get("gates"), list) else None,
                "evaluator_inputs": after.get("evaluator_inputs") if isinstance(after.get("evaluator_inputs"), dict) else None,
                "operational_state": after.get("operational_state") if isinstance(after.get("operational_state"), dict) else None,
                "created_at": row.created_at.isoformat() if isinstance(row.created_at, datetime) else None,
            }
        )
    transitions = []
    for row in session.scalars(
        select(PaperTransition).where(PaperTransition.intent_id == intent_id).order_by(PaperTransition.id.asc())
    ).all():
        transitions.append(
            {
                "from_state": row.from_state,
                "to_state": row.to_state,
                "reason": row.reason,
                "applied": row.applied,
                "occurred_at": row.occurred_at.isoformat() if isinstance(row.occurred_at, datetime) else None,
                "created_at": row.created_at.isoformat() if isinstance(row.created_at, datetime) else None,
            }
        )
    request_occurred_at = None
    quote_timestamp = None
    body_hash = None
    if isinstance(stored, dict):
        request_occurred_at = stored.get("request_occurred_at") if isinstance(stored.get("request_occurred_at"), str) else stored.get("occurred_at")
        quote_timestamp = stored.get("quote_timestamp") if isinstance(stored.get("quote_timestamp"), str) else None
        body_hash = stored.get("body_hash") if isinstance(stored.get("body_hash"), str) else None
    request_inputs = stored.get("risk_intent") if isinstance(stored, dict) and isinstance(stored.get("risk_intent"), dict) else None
    if request_inputs is None:
        missing.extend(["quote", "forecast", "master", "lot_size", "tick_size", "charges_per_lot", "expected_net", "entry_plan"])
    else:
        for key in ("quote", "forecast", "master", "lot_size", "tick_size", "charges_per_lot", "expected_net", "entry_plan"):
            if request_inputs.get(key) in (None, "", {}):
                missing.append(key)
    return {
        "intent_id": intent_id,
        "state": current_state(session, intent_id),
        "body_hash": body_hash,
        "request_occurred_at": request_occurred_at if isinstance(request_occurred_at, str) else None,
        "quote_timestamp": quote_timestamp,
        "quote": request_inputs.get("quote") if isinstance(request_inputs, dict) and isinstance(request_inputs.get("quote"), dict) else None,
        "forecast": request_inputs.get("forecast") if isinstance(request_inputs, dict) and isinstance(request_inputs.get("forecast"), dict) else None,
        "master": request_inputs.get("master") if isinstance(request_inputs, dict) and isinstance(request_inputs.get("master"), dict) else None,
        "lot_size": request_inputs.get("lot_size") if isinstance(request_inputs, dict) else None,
        "tick_size": request_inputs.get("tick_size") if isinstance(request_inputs, dict) else None,
        "charges_per_lot": request_inputs.get("charges_per_lot") if isinstance(request_inputs, dict) else None,
        "expected_net": request_inputs.get("expected_net") if isinstance(request_inputs, dict) else None,
        "entry_plan": request_inputs.get("entry_plan") if isinstance(request_inputs, dict) and isinstance(request_inputs.get("entry_plan"), dict) else None,
        "lineage": lineage if isinstance(lineage, dict) else None,
        "snapshot_conflict": conflict,
        "snapshot_count": len(requests),
        "transitions": transitions,
        "attempts": attempts,
        "missing": missing,
        "fill": None,
        "simulated_fill": None,
        "reconstructed": stored is not None and not conflict and any(item.get("decision_attempt") is True and isinstance(item.get("reasons"), list) for item in attempts),
        **_FLAGS,
    }


def _attempt_audit(
    session: Session,
    intent_id: str,
    *,
    decision_attempt: bool,
    duplicate_request: bool,
    input_conflict: bool,
    recovery: bool,
    presented_body_hash: str | None,
    risk: dict | None,
    evaluator_inputs: dict | None = None,
) -> dict:
    stored = _stored_request(session, intent_id)
    prior = session.scalar(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.entity == f"paper_intent:{intent_id}", AuditEvent.action == "paper.simulation")
    )
    # A config revision id is not the file evaluate() read. Consumed fields are stored separately.
    quote_timestamp = stored.get("quote_timestamp") if isinstance(stored, dict) and isinstance(stored.get("quote_timestamp"), str) else None
    request_occurred_at = None
    if isinstance(stored, dict):
        raw_clock = stored.get("request_occurred_at") if isinstance(stored.get("request_occurred_at"), str) else stored.get("occurred_at")
        request_occurred_at = raw_clock if isinstance(raw_clock, str) else None
    return {
        "attempt": int(prior or 0) + 1,
        "decision_attempt": decision_attempt,
        "duplicate_request": duplicate_request,
        "input_conflict": input_conflict,
        "recovery": recovery,
        "body_hash": stored.get("body_hash") if isinstance(stored, dict) else None,
        "presented_body_hash": presented_body_hash,
        "request_occurred_at": request_occurred_at,
        "quote_timestamp": quote_timestamp,
        "quote_timestamp_missing": quote_timestamp is None,
        "config_revision": None,
        "config_revision_missing": decision_attempt,
        "lineage": stored.get("lineage") if isinstance(stored, dict) and isinstance(stored.get("lineage"), dict) else None,
        "gates": _gate_audit(risk) if decision_attempt else None,
        "evaluator_inputs": evaluator_inputs if decision_attempt and isinstance(evaluator_inputs, dict) else None,
        "operational_state": risk.get("operational_state") if decision_attempt and isinstance(risk, dict) and isinstance(risk.get("operational_state"), dict) else None,
    }


def _consumed_risk(config: RiskConfig) -> dict:
    """Copy only the risk fields evaluate() reads. Unused file settings are not decision inputs."""
    dumped = config.model_dump(mode="json")
    consumed = {key: dumped[key] for key in _CONSUMED_RISK_FIELDS}
    consumed["calendar"] = None
    return consumed


def _gate_audit(risk: dict | None) -> list[dict] | None:
    if not isinstance(risk, dict) or not isinstance(risk.get("gates"), list):
        return None
    rows = []
    for gate in risk["gates"]:
        if not isinstance(gate, dict):
            return None
        rows.append(
            {
                "name": gate.get("name") if isinstance(gate.get("name"), str) else None,
                "state": gate.get("state") if isinstance(gate.get("state"), str) else None,
                "detail": gate.get("detail") if isinstance(gate.get("detail"), str) else None,
            }
        )
    return rows


def _quote_timestamp(body: dict) -> str | None:
    """Copy the quote's own timestamp. A missing value stays missing."""
    quote = body.get("quote")
    if not isinstance(quote, dict):
        return None
    raw = quote.get("quote_timestamp")
    if isinstance(raw, datetime):
        clock = _evaluation_clock(raw)
        return None if clock is None else clock.isoformat()
    if isinstance(raw, str) and raw.strip():
        return raw
    return None


def _lineage_record(dataset: object, forecast: object) -> dict:
    record: dict = {}
    if isinstance(dataset, dict):
        for key in ("dataset_id", "checksum", "origin", "source_row_sha256"):
            if key in dataset:
                record[key] = dataset.get(key)
        lineage = dataset.get("lineage")
        if isinstance(lineage, dict):
            for key in ("schema", "origin", "source_id", "source_row_sha256", "parent_dataset_id", "parent_checksum", "market_data_verified", "research_declaration"):
                if key in lineage and key not in record:
                    record[key] = lineage.get(key)
    if isinstance(forecast, dict):
        for key in ("promotion_state", "model_id", "version_id"):
            if key in forecast:
                record[f"forecast_{key}"] = forecast.get(key)
    return record


def _clock_from_snapshot(snapshot: dict) -> datetime | None:
    raw = snapshot.get("occurred_at")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return _evaluation_clock(parsed)


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        clock = _evaluation_clock(value)
        if clock is None:
            raise TypeError("naive datetime")
        return clock.isoformat()
    raise TypeError(type(value).__name__)


def _entry_plan(plan: object) -> dict | None:
    """Pass the four operator texts through. Missing texts stay missing."""
    if not isinstance(plan, dict):
        return None
    return {field: plan.get(field) for field in _ENTRY_FIELDS}


def _evaluation_clock(occurred_at: datetime) -> datetime | None:
    """Use the request timestamp. A missing quote time is not replaced with now."""
    if occurred_at.tzinfo is None or occurred_at.tzinfo.utcoffset(occurred_at) is None:
        return None
    return occurred_at.astimezone(timezone.utc)


def _price(value: Decimal | None, reason: str) -> dict:
    return {"price": None if value is None else str(value), "reason": reason, "fill_recorded": False, "market_fill": False, **_FLAGS}


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
    except Exception:
        return None
    if not number.is_finite():
        return None
    return number


def close_paper_position(
    session: Session,
    intent_id: str,
    *,
    exit_price: Decimal | float | str | None = None,
    exit_quote: dict | None = None,
    reason: str = "OPERATOR_EXIT",
    occurred_at: datetime | None = None,
    actor: str = "paper",
) -> dict:
    """Close an open paper position, compute statutory friction and net realized P&L,
    and persist the exit transitions and account event.

    Idempotent: Repeating with the same intent_id returns the existing closed event
    without double-counting P&L or duplicating database rows.
    """
    from app.domain.tables import PaperAccountEvent, PaperTransition
    from app.execution.paper import current_state, transition

    # 1. Check idempotency: if already closed, return existing exit record
    existing_exit = session.get(PaperAccountEvent, f"sim-exit-{intent_id}")
    if existing_exit is not None:
        payload = existing_exit.payload or {}
        return {
            "ok": True,
            "status": "ALREADY_CLOSED",
            "intent_id": intent_id,
            "exit_fill": payload,
            "realized_pnl_inr": float(payload.get("realized_pnl_inr", 0.0)),
            "net_realized_pnl_inr": float(payload.get("net_realized_pnl_inr", 0.0)),
            "exit_charges_inr": float(payload.get("charges_inr", 0.0)),
            "duplicate": True,
        }

    # 2. Retrieve entry event
    entry_event = session.get(PaperAccountEvent, f"sim-fill-{intent_id}")
    if entry_event is None:
        return {
            "ok": False,
            "status": "POSITION_NOT_FOUND",
            "message": f"No open paper position found for intent {intent_id}.",
        }

    entry_payload = entry_event.payload or {}
    recorded_entry = entry_payload.get("price") or entry_event.price
    if recorded_entry is None:
        return {"ok": False, "status": "ENTRY_PRICE_MISSING", "message": f"Entry price for {intent_id} is not recorded; P&L cannot be computed."}
    entry_price = Decimal(str(recorded_entry))
    entry_charges = Decimal(str(entry_payload.get("charges_inr") or entry_event.charges_inr or "0.0"))
    entry_side = entry_payload.get("side", "BUY")
    underlying = entry_payload.get("underlying")
    lot_size = _resolve_lot_size(entry_payload.get("charges_breakdown", {}).get("lot_size"), underlying)
    recorded_qty = entry_payload.get("quantity") or entry_event.quantity
    quantity = Decimal(str(recorded_qty)) if recorded_qty else lot_size

    # Determine exit side: if bought, exit is SELL; if sold, exit is BUY
    exit_side = "SELL" if entry_side == "BUY" else "BUY"

    # 3. Determine exit price
    exit_dt = occurred_at or datetime.now(timezone.utc)
    if exit_price is not None:
        final_exit_price = Decimal(str(exit_price))
    elif exit_quote and (exit_quote.get("bid") is not None or exit_quote.get("ask") is not None):
        bid = exit_quote.get("bid")
        ask = exit_quote.get("ask")
        haircut = "half_spread"
        priced = simulated_execution_price(side=exit_side, bid=bid, ask=ask, haircut=haircut, extra_tick_penalty=False)
        touch = bid if exit_side == "SELL" else ask
        if priced.get("price") is not None:
            final_exit_price = Decimal(str(priced["price"]))
        elif touch is not None:
            final_exit_price = Decimal(str(touch))
        else:
            return {"ok": False, "status": "EXIT_PRICE_REQUIRED",
                    "message": f"The exit quote has no {'bid' if exit_side == 'SELL' else 'ask'} to {exit_side.lower()} into."}
    else:
        # Never book an exit at the entry price: that would fabricate a flat result
        return {"ok": False, "status": "EXIT_PRICE_REQUIRED",
                "message": "An exit price or a live exit quote is required to close a paper position."}

    # 4. Calculate Indian regulatory exit charges
    entry_breakdown = entry_payload.get("charges_breakdown") or {}
    entry_cpl = entry_breakdown.get("charges_per_lot")
    exit_instrument = entry_breakdown.get("instrument_type") or ("OPTION" if entry_payload.get("option_type") else "FUTURE")
    exit_schedule = charge_schedule_for(underlying, exit_instrument)
    if exit_schedule is None:
        return {"ok": False, "status": "CHARGE_SCHEDULE_UNAVAILABLE", "message": f"No charge schedule for {underlying}."}
    exit_charges_info = calculate_indian_regulatory_charges(
        side=exit_side,
        price=final_exit_price,
        quantity=quantity,
        charges_per_lot=Decimal(str(entry_cpl)) if entry_cpl else None,
        lot_size=lot_size,
        exchange=exit_schedule[0],
        instrument_type=exit_instrument,
    )
    exit_charges_total = Decimal(exit_charges_info["total_charges_inr"])

    # 5. Compute P&L
    if entry_side == "BUY":
        gross_pnl = (final_exit_price - entry_price) * quantity
    else:
        gross_pnl = (entry_price - final_exit_price) * quantity

    total_charges = entry_charges + exit_charges_total
    net_realized_pnl = gross_pnl - total_charges

    # 6. Apply state transitions: FILLED -> EXIT_PENDING -> CLOSED
    curr = current_state(session, intent_id)
    if curr == "FILLED":
        transition(session, intent_id, "EXIT_PENDING", occurred_at=exit_dt, reason=reason, experimental=True)
        transition(session, intent_id, "CLOSED", occurred_at=exit_dt, reason=f"EXIT_FILLED_{reason}", experimental=True)
    elif curr == "EXIT_PENDING":
        transition(session, intent_id, "CLOSED", occurred_at=exit_dt, reason=f"EXIT_FILLED_{reason}", experimental=True)

    # 7. Persist exit PaperAccountEvent
    capital = entry_event.opening_cash_inr or Decimal("1000000.00")
    exit_payload = {
        "event_id": f"sim-exit-{intent_id}",
        "intent_id": intent_id,
        "side": exit_side,
        "entry_side": entry_side,
        "underlying": underlying,
        "expiry": entry_payload.get("expiry"),
        "strike": entry_payload.get("strike"),
        "option_type": entry_payload.get("option_type"),
        "contract": entry_payload.get("contract") or f"{underlying} {entry_payload.get('strike')} {entry_payload.get('option_type')}",
        "quantity": str(quantity),
        "entry_price": str(entry_price),
        "exit_price": str(final_exit_price),
        "entry_charges_inr": str(entry_charges),
        "charges_inr": str(exit_charges_total),
        "total_charges_inr": str(total_charges),
        "gross_pnl_inr": float(gross_pnl),
        "realized_pnl_inr": float(net_realized_pnl),
        "net_realized_pnl_inr": float(net_realized_pnl),
        "charges_breakdown": exit_charges_info,
        "exit_reason": reason,
        "execution_context": "EXPERIMENTAL",
        "data_provenance": "EXPERIMENTAL_UNVERIFIED_DATA",
        "live_broker_routed": False,
        "live_order_calls": 0,
        "occurred_at": exit_dt.isoformat(),
    }

    exit_event = PaperAccountEvent(
        event_id=f"sim-exit-{intent_id}",
        event_type="FILL",
        occurred_at=exit_dt,
        intent_id=intent_id,
        source="SIMULATION",
        body_hash=entry_event.body_hash,
        opening_cash_inr=capital,
        quantity=quantity,
        price=final_exit_price,
        charges_inr=exit_charges_total,
        payload=exit_payload,
        effect={
            "applied_fill_ids": [f"sim-exit-{intent_id}"],
            "cash_inr": str(capital + net_realized_pnl),
            "position_qty": "0",
            "realized_pnl_inr": str(net_realized_pnl),
        },
        ledger_applied=False,
        broker_confirmed=False,
    )
    session.add(exit_event)
    session.commit()

    return {
        "ok": True,
        "status": "POSITION_CLOSED",
        "intent_id": intent_id,
        "entry_price": float(entry_price),
        "exit_price": float(final_exit_price),
        "entry_charges_inr": float(entry_charges),
        "exit_charges_inr": float(exit_charges_total),
        "total_charges_inr": float(total_charges),
        "gross_pnl_inr": float(gross_pnl),
        "realized_pnl_inr": float(net_realized_pnl),
        "net_realized_pnl_inr": float(net_realized_pnl),
        "exit_fill": exit_payload,
        "duplicate": False,
    }
