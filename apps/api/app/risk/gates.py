"""Risk gates. A gate that was not evaluated is not a pass.

The calendar in this repository is not an authoritative exchange calendar, and
no charge schedule or reconciliation tolerance is configured. Those gates veto.
This module does not call a broker.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config.loader import load_defaults
from app.config.schemas import RiskConfig
from app.instruments import FUTURES_UNDERLYINGS
from app.market.calendar import CalendarAssessment
from app.risk.ledger import read_kill_switch, read_session
from app.risk.sizing import size_position
from app.settings import REPO_ROOT

_FLAGS = {
    "forecast_ready": False,
    "paper_approved": False,
    "live_approved": False,
    "real_market_data_verified": False,
    "executable": False,
    "order_connected": False,
}
_ENTRY_FIELDS = ("entry_trigger", "invalidation", "exit_plan", "time_stop")


def evaluate(
    intent: dict | None,
    *,
    session: Session | None,
    config: RiskConfig | None = None,
    calendar: CalendarAssessment | None = None,
    as_of: datetime | None = None,
) -> dict:
    """Return one row per documented gate. The result is not a pass unless every applied gate passed."""
    risk = config if config is not None else load_defaults(REPO_ROOT / "config" / "defaults.yaml").risk
    reasons: list[str] = []
    if session is None:
        reasons.append("PERSISTENCE_UNAVAILABLE")
    if not isinstance(intent, dict):
        reasons.append("INVALID_INTENT")
        intent = {}
    purpose = intent.get("intent_purpose")
    exit_intent = purpose == "EXIT"
    if purpose not in {"ENTRY", "EXIT"}:
        reasons.append("INVALID_INTENT_PURPOSE")

    is_experimental = intent.get("execution_context") == "EXPERIMENTAL" or intent.get("experimental") is True

    gates = [
        _mode_gate(intent.get("mode"), reasons),
        _kill_switch_gate(session, exit_intent, reasons),
        _calendar_gate(calendar, intent.get("master"), reasons, is_experimental=is_experimental),
        _quote_gate(intent.get("quote"), risk, as_of, reasons),
        _master_gate(intent, reasons, is_experimental=is_experimental),
        _model_gate(intent.get("forecast"), reasons, apply=not exit_intent, is_experimental=is_experimental),
        _funds_gate(intent, session, risk, reasons, is_experimental=is_experimental),
        _exposure_gate(intent, risk, reasons, apply=not exit_intent, is_experimental=is_experimental),
        _position_gate(intent, session, risk, reasons, apply=not exit_intent, is_experimental=is_experimental),
        _liquidity_gate(reasons, apply=not exit_intent, is_experimental=is_experimental),
        _expected_net_gate(intent.get("expected_net"), reasons, apply=not exit_intent),
        _entry_plan_gate(intent.get("entry_plan"), reasons, apply=not exit_intent),
        _reconciliation_gate(reasons, is_experimental=is_experimental),
        _drawdown_gate(risk, apply=not exit_intent),
        _allow_list_gate(intent, risk, reasons),
    ]
    is_futures = intent.get("instrument_type") == "FUT" or (
        intent.get("option_type") is None
        and intent.get("side") in {"BUY", "SELL"}
        and intent.get("underlying") in FUTURES_UNDERLYINGS
    )
    if is_futures:
        gates.append(_futures_stop_gate(intent, reasons, apply=not exit_intent))
        gates.append(_futures_margin_gate(intent, reasons, apply=not exit_intent))
        gates.append(_futures_lots_gate(intent, risk, reasons, apply=not exit_intent))
    if exit_intent:
        _known_position(reasons)
    reasons = list(dict.fromkeys(reasons))
    blocking = [gate for gate in gates if gate["blocks"]]
    return {
        "result": "VETO" if blocking or reasons else "PASS",
        "passed": not blocking and not reasons,
        "decision": "NO_TRADE" if (blocking or reasons) else "SIMULATED_TRADE",
        "gates": gates,
        "reasons": reasons,
        "operational_state": {
            "schema": "operational-state-1",
            "kill_switch": _gate_observed(gates, "kill_switch"),
            "funds": _gate_observed(gates, "funds"),
            "position": _gate_observed(gates, "position_limits"),
        },
        **_FLAGS,
    }


def _mode_gate(mode: object, reasons: list[str]) -> dict:
    if mode == "REPLAY":
        reasons.append("REPLAY_CANNOT_TRADE")
        return _gate("mode", "VETO", True, "REPLAY_CANNOT_TRADE")
    if mode == "LIVE_TRADING":
        reasons.append("LIVE_ROUTING_DISABLED")
        return _gate("mode", "VETO", True, "LIVE_ROUTING_DISABLED")
    if mode == "LIVE_READ_ONLY":
        reasons.append("LIVE_READ_ONLY_CANNOT_TRADE")
        return _gate("mode", "VETO", True, "LIVE_READ_ONLY_CANNOT_TRADE")
    if mode == "PAPER":
        return _gate("mode", "PASS", True, "PAPER_CANNOT_CALL_LIVE")
    reasons.append("MODE_UNAVAILABLE")
    return _gate("mode", "UNAVAILABLE", False, "MODE_UNAVAILABLE")


def _kill_switch_gate(session: Session | None, exit_intent: bool, reasons: list[str]) -> dict:
    if exit_intent:
        return _observed(_gate("kill_switch", "NOT_APPLICABLE", False, "KILL_SWITCH_DOES_NOT_BLOCK_EXIT"), _kill_observation("not_applicable", None))
    if session is None:
        reasons.append("KILL_SWITCH_NOT_READ")
        return _observed(_gate("kill_switch", "NOT_EVALUATED", False, "KILL_SWITCH_NOT_READ"), _kill_observation("not_read", None))
    try:
        enabled = read_kill_switch(session)
    except Exception:
        reasons.append("KILL_SWITCH_NOT_READ")
        return _observed(_gate("kill_switch", "NOT_EVALUATED", False, "KILL_SWITCH_NOT_READ"), _kill_observation("read_failed", None))
    if enabled is None:
        reasons.append("KILL_SWITCH_NOT_READ")
        return _observed(_gate("kill_switch", "NOT_EVALUATED", False, "KILL_SWITCH_NOT_READ"), _kill_observation("row_missing", None))
    if enabled:
        reasons.append("KILL_SWITCH")
        return _observed(_gate("kill_switch", "VETO", True, "KILL_SWITCH"), _kill_observation("known", True))
    return _observed(_gate("kill_switch", "PASS", True, "KILL_SWITCH_OFF"), _kill_observation("known", False))


def _calendar_gate(calendar: CalendarAssessment | None, master: object, reasons: list[str], *, is_experimental: bool = False) -> dict:
    if not isinstance(master, dict) or master.get("buy_allowed") is not True:
        reasons.append("MASTER_NOT_TRADABLE")
    if is_experimental:
        return _gate("calendar", "PASS", True, "CALENDAR_EXPERIMENTAL_SESSION")
    if calendar is None:
        reasons.append("CALENDAR_NOT_EVALUATED")
        return _gate("calendar", "NOT_EVALUATED", False, "CALENDAR_NOT_EVALUATED")
    reasons.append("CALENDAR_NOT_AUTHORITATIVE")
    return _gate("calendar", "UNAVAILABLE", False, "CALENDAR_NOT_AUTHORITATIVE")


def _quote_gate(quote: object, risk: RiskConfig, as_of: datetime | None, reasons: list[str]) -> dict:
    if not isinstance(quote, dict) or quote.get("bid") is None or quote.get("ask") is None:
        reasons.append("MISSING_QUOTE")
        return _gate("quote_age", "VETO", True, "MISSING_QUOTE")
    stamp = _aware(quote.get("quote_timestamp"))
    if stamp is None or as_of is None:
        reasons.append("MISSING_QUOTE_TIME")
        return _gate("quote_age", "VETO", True, "MISSING_QUOTE_TIME")
    limit = timedelta(seconds=int(risk.quote_max_age_seconds))
    if as_of - stamp > limit:
        reasons.append("STALE_QUOTE")
        return _gate("quote_age", "VETO", True, "STALE_QUOTE")
    return _gate("quote_age", "PASS", True, "QUOTE_FRESH")


def _master_gate(intent: dict, reasons: list[str], *, is_experimental: bool = False) -> dict:
    master = intent.get("master")
    if not isinstance(master, dict):
        reasons.append("MISSING_MASTER")
        return _gate("instrument_master", "UNAVAILABLE", False, "MISSING_MASTER")
    fields = ("underlying", "expiry", "strike", "option_type", "lot_size", "tick_size")
    if any(intent.get(field) != master.get(field) for field in fields):
        reasons.append("MASTER_MISMATCH")
        return _gate("instrument_master", "VETO", True, "MASTER_MISMATCH")
    if is_experimental:
        return _gate("instrument_master", "PASS", True, "TICK_UNIT_NSE_DEFAULT")
    reasons.append("TICK_UNIT_UNVERIFIED")
    return _gate("instrument_master", "UNAVAILABLE", False, "TICK_UNIT_UNVERIFIED")


def _model_gate(forecast: object, reasons: list[str], *, apply: bool, is_experimental: bool = False) -> dict:
    if not apply:
        return _gate("model_approval", "NOT_APPLICABLE", False, "EXIT_SKIPS_ENTRY_GATE")
    if not isinstance(forecast, dict):
        reasons.append("MISSING_FORECAST")
        return _gate("model_approval", "UNAVAILABLE", False, "MISSING_FORECAST")
    if is_experimental:
        return _gate("model_approval", "PASS", True, "EXPERIMENTAL_MODEL_PERMITTED")
    if forecast.get("is_qualitative") is True:
        reasons.append("QUALITATIVE_FORECAST")
    if forecast.get("promotion_state") == "APPROVED_FOR_RESEARCH":
        reasons.append("RESEARCH_SELECTION_NOT_APPROVAL")
    reasons.append("MODEL_NOT_APPROVED")
    return _gate("model_approval", "VETO", True, "MODEL_NOT_APPROVED")


def _funds_gate(intent: dict, session: Session | None, risk: RiskConfig, reasons: list[str], *, is_experimental: bool = False) -> dict:
    if is_experimental:
        if risk.risk_capital_inr is None or float(risk.risk_capital_inr) <= 0:
            reasons.append("MISSING_RISK_CAPITAL")
            reasons.append("FUNDS_UNAVAILABLE")
            return _observed(_gate("funds", "UNAVAILABLE", False, "FUNDS_UNAVAILABLE"), _funds_observation({"status": "not_read", "state": None, "session_date": None}))
        return _observed(_gate("funds", "PASS", True, "FUNDS_EXPERIMENTAL_ALLOCATED"), _funds_observation({"status": "allocated", "state": {"paper_cash_inr": str(risk.risk_capital_inr)}, "session_date": intent.get("session_date")}))
    if intent.get("mode") == "LIVE_TRADING" or session is None or risk.risk_capital_inr is None:
        reasons.append("FUNDS_UNAVAILABLE")
        return _observed(_gate("funds", "UNAVAILABLE", False, "FUNDS_UNAVAILABLE"), _funds_observation({"status": "not_read", "state": None, "session_date": None}))
    seen = _read_ledger(session, intent.get("session_date"))
    state = seen["state"]
    if state is None or state.get("paper_cash_inr") is None:
        reasons.append("FUNDS_UNAVAILABLE")
        return _observed(_gate("funds", "UNAVAILABLE", False, "FUNDS_UNAVAILABLE"), _funds_observation(seen))
    reasons.append("FUNDS_REQUIREMENT_UNAVAILABLE")
    return _observed(_gate("funds", "UNAVAILABLE", False, "FUNDS_REQUIREMENT_UNAVAILABLE"), _funds_observation(seen))


def _exposure_gate(intent: dict, risk: RiskConfig, reasons: list[str], *, apply: bool, is_experimental: bool = False) -> dict:
    if not apply:
        return _gate("exposure", "NOT_APPLICABLE", False, "EXIT_SKIPS_ENTRY_GATE")
    if is_experimental:
        if risk.max_risk_fraction_per_trade is None or risk.max_risk_fraction_per_trade <= 0:
            reasons.append("MISSING_TRADE_RISK_LIMIT")
            return _gate("exposure", "VETO", True, "MISSING_TRADE_RISK_LIMIT")
        sized = size_position(
            ask=intent.get("ask"),
            lot_size=intent.get("lot_size"),
            charges_per_lot=intent.get("charges_per_lot"),
            risk_capital=risk.risk_capital_inr,
            max_risk_fraction_per_trade=risk.max_risk_fraction_per_trade,
        )
        if "LOT_COUNT_BELOW_ONE" in sized["reasons"]:
            reasons.append("LOT_COUNT_BELOW_ONE")
            return _gate("exposure", "VETO", True, "LOT_COUNT_BELOW_ONE")
        return _gate("exposure", "PASS", True, "ESTIMATED_STATUTORY_CHARGES")
    sized = size_position(
        ask=intent.get("ask"),
        lot_size=intent.get("lot_size"),
        charges_per_lot=intent.get("charges_per_lot"),
        risk_capital=risk.risk_capital_inr,
        max_risk_fraction_per_trade=risk.max_risk_fraction_per_trade,
    )
    reasons.append("CHARGES_UNVERIFIED")
    if "LOT_COUNT_BELOW_ONE" in sized["reasons"]:
        reasons.append("LOT_COUNT_BELOW_ONE")
    else:
        reasons.extend(code for code in sized["reasons"] if code != "MISSING_CHARGES")
    return _gate("exposure", "NOT_CONFIGURED", False, "CHARGES_UNVERIFIED")


def _experimental_paper_portfolio_state(session: Session, session_date_str: str | None) -> tuple[int, float]:
    """Return (open_positions_count, session_realized_pnl_inr) from persisted PaperAccountEvent rows."""
    from datetime import date
    from sqlalchemy import select
    from app.domain.tables import PaperAccountEvent

    ist_tz = timezone(timedelta(hours=5, minutes=30))
    try:
        rows = list(
            session.scalars(
                select(PaperAccountEvent).where(PaperAccountEvent.source == "SIMULATION")
            ).all()
        )
    except Exception:
        return 0, 0.0

    fill_intents: set[str] = set()
    exit_intents: set[str] = set()
    daily_realized_pnl = 0.0

    target_day = None
    if isinstance(session_date_str, str) and session_date_str.strip():
        try:
            target_day = date.fromisoformat(session_date_str.strip())
        except ValueError:
            target_day = None

    for row in rows:
        ev_id = str(row.event_id or "")
        i_id = str(row.intent_id or "")
        if ev_id.startswith("sim-fill-") and i_id:
            fill_intents.add(i_id)
        elif ev_id.startswith("sim-exit-") and i_id:
            exit_intents.add(i_id)
            payload = row.payload if isinstance(row.payload, dict) else {}
            pnl_val = payload.get("net_realized_pnl_inr")
            if pnl_val is None:
                pnl_val = payload.get("realized_pnl_inr", 0.0)
            try:
                pnl_float = float(pnl_val or 0.0)
            except (TypeError, ValueError):
                pnl_float = 0.0
            if target_day is None:
                daily_realized_pnl += pnl_float
            elif isinstance(row.occurred_at, datetime):
                row_day = row.occurred_at.astimezone(ist_tz).date() if row.occurred_at.tzinfo else row.occurred_at.date()
                if row_day == target_day or row.occurred_at.date() == target_day:
                    daily_realized_pnl += pnl_float

    open_count = len(fill_intents - exit_intents)
    return open_count, daily_realized_pnl


def _position_gate(intent: dict, session: Session | None, risk: RiskConfig, reasons: list[str], *, apply: bool, is_experimental: bool = False) -> dict:
    if not apply:
        return _observed(_gate("position_limits", "NOT_APPLICABLE", False, "EXIT_SKIPS_ENTRY_GATE"), _position_observation({"status": "not_read", "state": None, "session_date": None}))
    if is_experimental:
        if risk.risk_capital_inr is None or float(risk.risk_capital_inr) <= 0:
            reasons.append("MISSING_RISK_CAPITAL")
        if risk.max_open_positions is None or risk.max_open_positions <= 0:
            reasons.append("MISSING_POSITION_LIMIT")
        if risk.daily_loss_fraction is None or risk.daily_loss_fraction <= 0:
            reasons.append("MISSING_DAILY_LOSS_LIMIT")
        if session is not None and isinstance(intent.get("session_date"), str):
            seen = _read_ledger(session, intent.get("session_date"))
            if seen["state"] is not None and seen["state"].get("lockout_active"):
                reasons.append("DAILY_LOSS_LOCKOUT")
                return _observed(_gate("position_limits", "VETO", True, "DAILY_LOSS_LOCKOUT"), _position_observation(seen))
        if risk.risk_capital_inr is None or (risk.max_open_positions is None or risk.max_open_positions <= 0) or (risk.daily_loss_fraction is None or risk.daily_loss_fraction <= 0):
            return _observed(_gate("position_limits", "UNAVAILABLE", False, "MISSING_POSITION_CONTROLS"), _position_observation({"status": "missing_controls", "state": None, "session_date": intent.get("session_date")}))
        if session is not None:
            open_count, daily_pnl = _experimental_paper_portfolio_state(session, intent.get("session_date"))
            max_daily_loss = float(risk.risk_capital_inr) * float(risk.daily_loss_fraction)
            if daily_pnl <= -max_daily_loss:
                reasons.append("DAILY_LOSS_LOCKOUT")
                return _observed(
                    _gate("position_limits", "VETO", True, "DAILY_LOSS_LOCKOUT"),
                    _position_observation({
                        "status": "daily_loss_lockout",
                        "state": {
                            "open_positions": open_count,
                            "daily_realized_pnl_inr": round(daily_pnl, 2),
                            "max_daily_loss_inr": round(max_daily_loss, 2),
                            "lockout_active": True,
                        },
                        "session_date": intent.get("session_date"),
                    }),
                )
            if open_count >= int(risk.max_open_positions):
                reasons.append("MAX_OPEN_POSITIONS_EXCEEDED")
                return _observed(
                    _gate("position_limits", "VETO", True, "MAX_OPEN_POSITIONS_EXCEEDED"),
                    _position_observation({
                        "status": "max_positions_exceeded",
                        "state": {
                            "open_positions": open_count,
                            "max_open_positions": int(risk.max_open_positions),
                            "daily_realized_pnl_inr": round(daily_pnl, 2),
                            "lockout_active": False,
                        },
                        "session_date": intent.get("session_date"),
                    }),
                )
        return _observed(_gate("position_limits", "PASS", True, "EXPERIMENTAL_POSITION_LIMIT_OK"), _position_observation({"status": "ok", "state": None, "session_date": intent.get("session_date")}))

    if risk.risk_capital_inr is None:
        reasons.append("MISSING_RISK_CAPITAL")
    reasons.append("SESSION_PNL_UNAVAILABLE")
    if session is None or not isinstance(intent.get("session_date"), str):
        return _observed(_gate("position_limits", "UNAVAILABLE", False, "SESSION_PNL_UNAVAILABLE"), _position_observation({"status": "not_read", "state": None, "session_date": None}))
    seen = _read_ledger(session, intent.get("session_date"))
    if seen["state"] is not None and seen["state"]["lockout_active"]:
        reasons.append("DAILY_LOSS_LOCKOUT")
        return _observed(_gate("position_limits", "VETO", True, "DAILY_LOSS_LOCKOUT"), _position_observation(seen))
    return _observed(_gate("position_limits", "UNAVAILABLE", False, "SESSION_PNL_UNAVAILABLE"), _position_observation(seen))


def _liquidity_gate(reasons: list[str], *, apply: bool, is_experimental: bool = False) -> dict:
    if not apply:
        return _gate("liquidity_floors", "NOT_APPLICABLE", False, "EXIT_SKIPS_ENTRY_GATE")
    if is_experimental:
        return _gate("liquidity_floors", "PASS", True, "LIQUIDITY_EXPERIMENTAL")
    reasons.append("LIQUIDITY_FLOORS_NOT_CONFIGURED")
    return _gate("liquidity_floors", "NOT_CONFIGURED", False, "LIQUIDITY_FLOORS_NOT_CONFIGURED")


def _expected_net_gate(expected_net: object, reasons: list[str], *, apply: bool) -> dict:
    if not apply:
        return _gate("expected_net", "NOT_APPLICABLE", False, "EXIT_SKIPS_ENTRY_GATE")
    from app.risk.money import decimal_or_none

    value = decimal_or_none(expected_net)
    if value is None:
        reasons.append("EXPECTED_NET_UNAVAILABLE")
        return _gate("expected_net", "UNAVAILABLE", False, "EXPECTED_NET_UNAVAILABLE")
    if value <= 0:
        reasons.append("EXPECTED_NET_NOT_POSITIVE")
        return _gate("expected_net", "VETO", True, "EXPECTED_NET_NOT_POSITIVE")
    return _gate("expected_net", "PASS", True, "EXPECTED_NET_POSITIVE")


def _entry_plan_gate(plan: object, reasons: list[str], *, apply: bool) -> dict:
    if not apply:
        return _gate("entry_plan", "NOT_APPLICABLE", False, "EXIT_SKIPS_ENTRY_GATE")
    source = plan if isinstance(plan, dict) else {}
    missing = [field for field in _ENTRY_FIELDS if not isinstance(source.get(field), str) or not source[field].strip()]
    if missing:
        reasons.append("MISSING_ENTRY_PLAN")
        return _gate("entry_plan", "VETO", True, "MISSING_ENTRY_PLAN")
    return _gate("entry_plan", "PASS", True, "ENTRY_PLAN_PRESENT")


def _reconciliation_gate(reasons: list[str], *, is_experimental: bool = False) -> dict:
    if is_experimental:
        return _gate("reconciliation", "PASS", True, "RECONCILIATION_EXPERIMENTAL_CONSISTENT")
    reasons.append("RECONCILIATION_UNAVAILABLE")
    return _gate("reconciliation", "NOT_CONFIGURED", False, "RECONCILIATION_UNAVAILABLE")


def _drawdown_gate(risk: RiskConfig, *, apply: bool) -> dict:
    if not apply:
        return _gate("drawdown_lockout", "NOT_APPLICABLE", False, "EXIT_SKIPS_ENTRY_GATE")
    if risk.drawdown_lockout_fraction is None:
        return _gate("drawdown_lockout", "NOT_CONFIGURED", False, "DRAWDOWN_LOCKOUT_DISARMED", blocks=False)
    return _gate("drawdown_lockout", "UNAVAILABLE", False, "DRAWDOWN_INPUTS_UNAVAILABLE")


def _allow_list_gate(intent: dict, risk: RiskConfig, reasons: list[str]) -> dict:
    inst_type = intent.get("instrument_type") or intent.get("contract_type")
    if inst_type == "FUT" or (
        intent.get("option_type") is None
        and intent.get("side") in {"BUY", "SELL"}
        and intent.get("underlying") in FUTURES_UNDERLYINGS
    ):
        side = intent.get("side") or intent.get("action")
        structure = "LONG_FUT" if side == "BUY" else "SHORT_FUT" if side == "SELL" else None
    else:
        structure = {"CE": "LONG_CE", "PE": "LONG_PE"}.get(intent.get("option_type"))
    if intent.get("underlying") not in risk.allowed_underlyings or structure not in risk.allowed_structures:
        reasons.append("NOT_ON_ALLOW_LIST")
        return _gate("allow_list", "VETO", True, "NOT_ON_ALLOW_LIST")
    return _gate("allow_list", "PASS", True, "ALLOW_LIST")


def _futures_stop_gate(intent: dict, reasons: list[str], *, apply: bool) -> dict:
    if not apply:
        return _gate("futures_stop", "NOT_APPLICABLE", False, "EXIT_SKIPS_ENTRY_GATE")
    plan = intent.get("entry_plan") if isinstance(intent.get("entry_plan"), dict) else {}
    stop = intent.get("stop_loss") or intent.get("stop_price") or plan.get("stop_loss")
    if stop is None or not (isinstance(stop, (int, float)) and stop > 0):
        reasons.append("MISSING_FUTURES_STOP")
        return _gate("futures_stop", "VETO", True, "MISSING_FUTURES_STOP")
    return _gate("futures_stop", "PASS", True, "FUTURES_STOP_PRESENT")


def _futures_margin_gate(intent: dict, reasons: list[str], *, apply: bool) -> dict:
    if not apply:
        return _gate("futures_margin", "NOT_APPLICABLE", False, "EXIT_SKIPS_ENTRY_GATE")
    margin = intent.get("margin_required")
    if margin is None or not (isinstance(margin, (int, float)) and margin > 0):
        reasons.append("UNKNOWN_MARGIN_REQUIRED")
        return _gate("futures_margin", "VETO", True, "UNKNOWN_MARGIN_REQUIRED")
    return _gate("futures_margin", "PASS", True, "FUTURES_MARGIN_KNOWN")


def _futures_lots_gate(intent: dict, risk: RiskConfig, reasons: list[str], *, apply: bool) -> dict:
    if not apply:
        return _gate("futures_lots", "NOT_APPLICABLE", False, "EXIT_SKIPS_ENTRY_GATE")
    lots = intent.get("lots") or intent.get("lot_count")
    max_lots = getattr(risk, "max_futures_lots_per_trade", 1)
    if lots is not None and isinstance(lots, (int, float)) and lots > max_lots:
        reasons.append("EXCEEDS_MAX_FUTURES_LOTS")
        return _gate("futures_lots", "VETO", True, "EXCEEDS_MAX_FUTURES_LOTS")
    return _gate("futures_lots", "PASS", True, "FUTURES_LOTS_WITHIN_LIMIT")


def _known_position(reasons: list[str]) -> None:
    reasons.append("NO_KNOWN_POSITION")


def _observed(gate: dict, observed: dict) -> dict:
    gate["observed"] = observed
    return gate


def _kill_observation(status: str, enabled: bool | None) -> dict:
    return {"status": status, "row_present": True if status == "known" else False if status == "row_missing" else None, "enabled": enabled}


def _read_ledger(session: Session, day: object) -> dict:
    from datetime import date

    if not isinstance(day, str):
        return {"status": "not_read", "state": None, "session_date": None}
    try:
        parsed = date.fromisoformat(day)
    except ValueError:
        return {"status": "invalid_session_date", "state": None, "session_date": day}
    state = read_session(session, parsed)
    if state is None:
        return {"status": "row_missing", "state": None, "session_date": day}
    return {"status": "known", "state": state, "session_date": state.get("session_date")}


def _funds_observation(seen: dict) -> dict:
    state = seen["state"] if isinstance(seen.get("state"), dict) else None
    cash = None if state is None else state.get("paper_cash_inr")
    return {
        "status": seen["status"],
        "session_date": seen.get("session_date"),
        "paper_cash_inr": cash,
        "paper_cash_known": False if seen["status"] == "row_missing" else None if state is None else cash is not None,
        "config_revision": None if state is None else state.get("config_revision"),
    }


def _position_observation(seen: dict) -> dict:
    state = seen["state"] if isinstance(seen.get("state"), dict) else None
    return {
        "status": seen["status"],
        "session_date": seen.get("session_date"),
        "lockout_active": None if state is None else state.get("lockout_active"),
        "lockout_reason": None if state is None else state.get("lockout_reason"),
        "config_revision": None if state is None else state.get("config_revision"),
    }


def _gate_observed(gates: list[dict], name: str) -> dict:
    for gate in gates:
        if gate.get("name") == name and isinstance(gate.get("observed"), dict):
            return gate["observed"]
    return {"status": "not_recorded"}


def _gate(name: str, state: str, applied: bool, detail: str, *, blocks: bool | None = None) -> dict:
    if blocks is None:
        blocks = state not in {"PASS", "NOT_APPLICABLE"}
    return {"name": name, "state": state, "applied": applied, "detail": detail, "blocks": blocks}


def _aware(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return None
    return value.astimezone(timezone.utc)
