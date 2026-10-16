"""Offline paper-accounting replay. It does not persist a fill or move a ledger row.

The persisted ledger accepts only RESERVE, RELEASE, LOCKOUT_SET, and LOCKOUT_CLEAR.
Its session invariant keeps open premium at zero and paper cash equal to configured
capital, so a fill cannot be posted there. This module replays explicit events in
memory and leaves unknown charges unknown.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.risk.money import decimal_or_none

_FLAGS = {
    "forecast_ready": False,
    "paper_approved": False,
    "live_approved": False,
    "real_market_data_verified": False,
    "live_trading_enabled": False,
    "persisted": False,
    "activated": False,
}
_KINDS = frozenset({"FILL", "PARTIAL_FILL", "CANCEL", "REJECT", "CHARGE_ASSESSMENT", "CHARGE_CORRECTION", "RECONCILIATION_DISCREPANCY"})
_FILL_KINDS = frozenset({"FILL", "PARTIAL_FILL"})
_SIDES = frozenset({"BUY", "SELL"})


def replay_paper_accounts(events: object, *, opening_cash: object = None) -> dict:
    """Replay explicit paper events. Identical ids are not applied twice."""
    cash = _money(opening_cash)
    if opening_cash is not None and cash is None:
        return _stopped("INVALID_OPENING_CASH", cash=None, charges=None, charges_known=False)
    if not isinstance(events, list):
        return _stopped("INVALID_EVENTS", cash=cash, charges=Decimal("0") if cash is not None else None, charges_known=cash is not None)
    ordered = sorted(events, key=_sort_key)
    state = _Book(cash=cash, charges=Decimal("0"), charges_known=True)
    seen_events: dict[str, str] = {}
    seen_fills: dict[str, str] = {}
    for event in ordered:
        refusal = _invalid(event)
        if refusal is not None:
            return state.finish(refusal, event)
        digest = _digest(event)
        event_id = event["event_id"]
        if event_id in seen_events:
            if seen_events[event_id] != digest:
                return state.finish("DUPLICATE_EVENT_CONFLICT", event)
            continue
        fill_id = event.get("fill_id")
        if event["event_type"] in _FILL_KINDS:
            if fill_id in seen_fills:
                if seen_fills[fill_id] != digest:
                    return state.finish("DUPLICATE_FILL_CONFLICT", event)
                seen_events[event_id] = digest
                continue
            problem = state.apply_fill(event)
            if problem is not None:
                return state.finish(problem, event)
            seen_fills[fill_id] = digest
        elif event["event_type"] in {"CHARGE_ASSESSMENT", "CHARGE_CORRECTION"}:
            problem = state.apply_charge(event)
            if problem is not None:
                return state.finish(problem, event)
        elif event["event_type"] == "RECONCILIATION_DISCREPANCY":
            problem = state.apply_discrepancy(event)
            if problem is not None:
                return state.finish(problem, event)
        else:
            state.apply_terminal(event)
        seen_events[event_id] = digest
        state.applied.append(event_id)
    return state.finish(None, None)


def reconcile_paper_accounts(
    *,
    replay: dict,
    statement: dict | None,
    tolerance: object = None,
    max_age_seconds: object = None,
    as_of: object = None,
) -> dict:
    """Compare a replay with an independent statement. An absent value is not zero."""
    reasons = []
    if tolerance is None:
        reasons.append("TOLERANCE_MISSING")
    elif _money(tolerance) is None or _money(tolerance) < 0:
        reasons.append("TOLERANCE_INVALID")
    if not isinstance(replay, dict) or not isinstance(statement, dict):
        reasons.append("STATEMENT_ABSENT")
        return _reconciliation(False, list(dict.fromkeys(reasons)))
    reasons.extend(_statement_identity(statement))
    reasons.extend(_statement_evidence(statement, max_age_seconds=max_age_seconds, as_of=as_of))
    replay_positions = replay.get("positions", _MISSING)
    if replay_positions is _MISSING or not isinstance(replay_positions, list):
        reasons.append("POSITION_REPLAY_ABSENT")
    elif "positions" not in statement:
        reasons.append("POSITION_STATEMENT_ABSENT")
    else:
        reported = statement.get("positions")
        if not isinstance(reported, list):
            reasons.append("POSITION_STATEMENT_ABSENT")
        else:
            reasons.extend(_position_differences(replay_positions, reported))
    reasons.extend(_money_difference("cash", replay.get("cash_inr"), statement.get("cash_inr") if "cash_inr" in statement else _MISSING, tolerance))
    reasons.extend(
        _money_difference("charges", replay.get("charges_booked_inr"), statement.get("charges_booked_inr") if "charges_booked_inr" in statement else _MISSING, tolerance)
    )
    if "fill_ids" not in statement or statement.get("fill_ids") is None or not isinstance(statement.get("fill_ids"), list):
        reasons.append("FILL_STATEMENT_ABSENT")
    elif set(statement.get("fill_ids") or []) != set(replay.get("applied_fill_ids") or []):
        reasons.append("FILL_ID_MISMATCH")
    if replay.get("cash_inr") is None:
        reasons.append("CASH_UNKNOWN")
    if replay.get("charges_booked_inr") is None:
        reasons.append("CHARGES_UNKNOWN")
    unique = list(dict.fromkeys(reasons))
    return _reconciliation(not unique, unique)


class _Missing:
    pass


_MISSING = _Missing()


class _Book:
    def __init__(self, *, cash: Decimal | None, charges: Decimal | None, charges_known: bool) -> None:
        self.cash = cash
        self.charges = charges
        self.charges_known = charges_known
        self.positions: dict[tuple, dict] = {}
        self.intents: dict[str, dict] = {}
        self.applied: list[str] = []
        self.fills: list[str] = []
        self.charge_posts: dict[str, Decimal] = {}
        self.discrepancies: list[dict] = []

    def apply_fill(self, event: dict) -> str | None:
        price = _money(event.get("price"))
        quantity = _money(event.get("quantity"))
        if price is None or price <= 0 or quantity is None or quantity <= 0:
            return "INCOMPLETE_FILL"
        if event["event_type"] == "PARTIAL_FILL":
            order = _money(event.get("order_quantity"))
            if event.get("order_quantity") is None or order is None:
                return "UNFILLED_QUANTITY_UNKNOWN"
            if order <= quantity:
                return "NOT_PARTIAL"
        charges = event.get("charges_inr")
        charge = None if charges is None else _money(charges)
        if charges is not None and charge is None:
            return "INVALID_CHARGES"
        key = _contract(event)
        current = self.positions.get(key)
        side = event["side"]
        if side == "SELL":
            if current is None or current["quantity"] < quantity:
                return "OVERSELL"
            current["quantity"] -= quantity
            if current["quantity"] == 0:
                self.positions.pop(key)
        else:
            if current is None:
                self.positions[key] = {"quantity": quantity, "average": price, **_contract_fields(event)}
            else:
                total = current["quantity"] + quantity
                current["average"] = (current["quantity"] * current["average"] + quantity * price) / total
                current["quantity"] = total
        if charge is None:
            self.charges_known = False
            self.charges = None
            self.cash = None
        elif self.charges_known:
            self.charges = (Decimal("0") if self.charges is None else self.charges) + charge
            if self.cash is not None:
                premium = price * quantity
                self.cash = self.cash - premium - charge if side == "BUY" else self.cash + premium - charge
            self.charge_posts[event["event_id"]] = charge
        self._intent_fill(event, quantity)
        self.fills.append(event["fill_id"])
        return None

    def apply_charge(self, event: dict) -> str | None:
        """Book an explicit charge. A missing amount does not become zero."""
        amount = event.get("charges_inr")
        charge = None if amount is None else _money(amount)
        if amount is None:
            return "CHARGES_UNKNOWN"
        if charge is None or charge < 0:
            return "INVALID_CHARGES"
        if not self.charges_known or self.charges is None:
            return "CHARGES_ALREADY_UNKNOWN"
        if event["event_type"] == "CHARGE_CORRECTION":
            prior = event.get("prior_event_id")
            if not isinstance(prior, str) or prior not in self.charge_posts:
                return "PRIOR_CHARGE_UNKNOWN"
            delta = charge - self.charge_posts[prior]
        else:
            delta = charge
        self.charges = self.charges + delta
        if self.cash is not None:
            self.cash = self.cash - delta
        self.charge_posts[event["event_id"]] = charge
        return None

    def apply_discrepancy(self, event: dict) -> str | None:
        """Record a discrepancy. It does not change cash, quantity, or charges."""
        if not isinstance(event.get("statement_id"), str) or not event["statement_id"].strip():
            return "STATEMENT_ID_MISSING"
        if _aware(event.get("statement_as_of")) is None:
            return "STATEMENT_TIME_MISSING"
        if event.get("completeness") not in {"COMPLETE", "INCOMPLETE"}:
            return "COMPLETENESS_MISSING"
        if not isinstance(event.get("source"), str) or not event["source"].strip():
            return "SOURCE_MISSING"
        self.discrepancies.append(
            {
                "event_id": event["event_id"],
                "statement_id": event["statement_id"],
                "completeness": event["completeness"],
                "source": event["source"],
            }
        )
        return None

    def apply_terminal(self, event: dict) -> None:
        intent = self.intents.setdefault(event["intent_id"], {"filled": Decimal("0"), "order": None, "status": "OPEN"})
        order = event.get("order_quantity")
        if order is not None and _money(order) is not None:
            intent["order"] = _money(order)
        intent["status"] = "CANCELLED" if event["event_type"] == "CANCEL" else "REJECTED"

    def finish(self, reason: str | None, event: object) -> dict:
        rejected = []
        if reason is not None and isinstance(event, dict):
            rejected.append({"event_id": event.get("event_id"), "reason": reason})
        positions = []
        for row in self.positions.values():
            premium = row["average"] * row["quantity"]
            positions.append(
                {
                    "underlying": row["underlying"],
                    "expiry": row["expiry"],
                    "strike": row["strike"],
                    "option_type": row["option_type"],
                    "quantity": _text(row["quantity"]),
                    "average_entry_ask": _text(row["average"]),
                    "open_premium_inr": _text(premium),
                }
            )
        intents = {}
        for intent_id, row in self.intents.items():
            unfilled = None if row["order"] is None else row["order"] - row["filled"]
            status = row["status"]
            if status == "OPEN" and row["order"] is not None and unfilled == 0:
                status = "FILLED"
            elif status == "OPEN" and row["order"] is not None and row["filled"] > 0:
                status = "PARTIAL"
            intents[intent_id] = {
                "status": status,
                "filled_quantity": _text(row["filled"]),
                "unfilled_quantity": None if unfilled is None else _text(unfilled),
            }
        return {
            "stopped": reason is not None,
            "stop_reason": reason,
            "rejected": rejected,
            "applied_event_ids": list(self.applied),
            "applied_fill_ids": list(self.fills),
            "cash_inr": None if self.cash is None else _text(self.cash),
            "charges_booked_inr": None if not self.charges_known or self.charges is None else _text(self.charges),
            "charges_known": self.charges_known and self.charges is not None,
            "positions": positions,
            "intents": intents,
            "session_pnl_inr": None,
            "discrepancies": list(self.discrepancies),
            **_FLAGS,
        }

    def _intent_fill(self, event: dict, quantity: Decimal) -> None:
        intent = self.intents.setdefault(event["intent_id"], {"filled": Decimal("0"), "order": None, "status": "OPEN"})
        intent["filled"] += quantity
        order = event.get("order_quantity")
        if order is not None and _money(order) is not None:
            intent["order"] = _money(order)


def _invalid(event: object) -> str | None:
    if not isinstance(event, dict):
        return "INVALID_EVENT"
    if not isinstance(event.get("event_id"), str) or not event["event_id"].strip():
        return "INVALID_EVENT_ID"
    if event.get("event_type") not in _KINDS:
        return "INVALID_EVENT_TYPE"
    if not isinstance(event.get("intent_id"), str) or not event["intent_id"].strip():
        return "INVALID_INTENT_ID"
    if _aware(event.get("occurred_at")) is None:
        return "INVALID_TIMESTAMP"
    if event["event_type"] == "CHARGE_CORRECTION" and (not isinstance(event.get("prior_event_id"), str) or not event["prior_event_id"].strip()):
        return "PRIOR_CHARGE_UNKNOWN"
    if event["event_type"] in _FILL_KINDS:
        if not isinstance(event.get("fill_id"), str) or not event["fill_id"].strip():
            return "INVALID_FILL_ID"
        if event.get("side") not in _SIDES:
            return "INVALID_SIDE"
        if _contract(event) is None:
            return "INCOMPLETE_CONTRACT"
    return None


def _position_differences(replay_rows: list, reported_rows: list) -> list[str]:
    reasons = []
    replay = {_row_key(row): row for row in replay_rows if _row_key(row) is not None}
    reported = {}
    for row in reported_rows:
        key = _row_key(row)
        if key is None:
            reasons.append("POSITION_INCOMPLETE")
            continue
        reported[key] = row
    for key, row in replay.items():
        other = reported.get(key)
        if other is None:
            reasons.append("POSITION_ABSENT")
            continue
        if _money(other.get("quantity")) != _money(row.get("quantity")) or _money(other.get("average_entry_ask")) != _money(row.get("average_entry_ask")):
            reasons.append("POSITION_MISMATCH")
    for key in reported:
        if key not in replay:
            reasons.append("STATEMENT_POSITION_EXTRA")
    return reasons


def _statement_evidence(statement: dict, *, max_age_seconds: object, as_of: object) -> list[str]:
    reasons = []
    if statement.get("source") == "BROKER" and statement.get("verified") is not True:
        reasons.append("BROKER_EVIDENCE_UNVERIFIED")
    stamp = statement.get("as_of") if "as_of" in statement else _MISSING
    if stamp is _MISSING or stamp is None:
        reasons.append("STATEMENT_TIME_MISSING")
        return reasons
    parsed = _aware(stamp)
    clock = _aware(as_of)
    limit = None if isinstance(max_age_seconds, bool) else max_age_seconds
    if parsed is None:
        reasons.append("STATEMENT_TIME_INVALID")
    elif clock is None or limit is None:
        reasons.append("STATEMENT_FRESHNESS_UNVERIFIED")
    else:
        try:
            seconds = int(limit)
        except (TypeError, ValueError):
            reasons.append("STATEMENT_FRESHNESS_UNVERIFIED")
        else:
            if seconds < 0 or clock - parsed > timedelta(seconds=seconds):
                reasons.append("STATEMENT_STALE")
    return reasons


def _statement_identity(statement: dict) -> list[str]:
    reasons = []
    source = statement.get("source") if "source" in statement else _MISSING
    if source is _MISSING or not isinstance(source, str) or not source.strip():
        reasons.append("SOURCE_MISSING")
    completeness = statement.get("completeness") if "completeness" in statement else _MISSING
    if completeness is _MISSING or completeness is None:
        reasons.append("COMPLETENESS_MISSING")
    elif completeness != "COMPLETE":
        reasons.append("COMPLETENESS_INCOMPLETE")
    return reasons


def _money_difference(name: str, replay_value: object, statement_value: object, tolerance: object = None) -> list[str]:
    label = name.upper()
    if statement_value is _MISSING:
        return [f"{label}_ABSENT"]
    if statement_value is None:
        return [f"{label}_STATEMENT_UNKNOWN"]
    statement_money = _money(statement_value)
    if statement_money is None:
        return [f"{label}_STATEMENT_INVALID"]
    if replay_value is None:
        return []
    replay_money = _money(replay_value)
    if replay_money is None:
        return [f"{label}_MISMATCH"]
    band = _money(tolerance) if tolerance is not None else Decimal("0")
    if band is None or abs(replay_money - statement_money) > band:
        return [f"{label}_MISMATCH"]
    return []


def _reconciliation(consistent: bool, reasons: list[str]) -> dict:
    return {"consistent": consistent, "reasons": reasons, "broker_orders": 0, **_FLAGS}


def _stopped(reason: str, *, cash: Decimal | None, charges: Decimal | None, charges_known: bool) -> dict:
    book = _Book(cash=cash, charges=charges, charges_known=charges_known)
    return book.finish(reason, {"event_id": None})


def _contract(event: dict) -> tuple | None:
    underlying = event.get("underlying")
    expiry = event.get("expiry")
    strike = event.get("strike")
    option_type = event.get("option_type")
    if not isinstance(underlying, str) or not underlying.strip():
        return None
    if not isinstance(expiry, str) or not expiry.strip():
        return None
    if strike is None or str(strike).strip() == "":
        return None
    if option_type not in {"CE", "PE"}:
        return None
    return (underlying, expiry, str(strike), option_type)


def _contract_fields(event: dict) -> dict:
    return {
        "underlying": event["underlying"],
        "expiry": event["expiry"],
        "strike": str(event["strike"]),
        "option_type": event["option_type"],
    }


def _row_key(row: object) -> tuple | None:
    if not isinstance(row, dict):
        return None
    return _contract(row)


def _money(value: object) -> Decimal | None:
    return decimal_or_none(value)


def _text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _aware(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return None
    return value.astimezone(timezone.utc)


def _sort_key(event: object) -> tuple:
    """Order by absolute time, then event id. Text form is not the order."""
    if not isinstance(event, dict):
        return (datetime.min.replace(tzinfo=timezone.utc), "")
    stamp = _aware(event.get("occurred_at"))
    if stamp is None:
        return (datetime.min.replace(tzinfo=timezone.utc), str(event.get("event_id") or ""))
    return (stamp, str(event.get("event_id") or ""))


def _digest(event: dict) -> str:
    body = {
        "event_id": event.get("event_id"),
        "fill_id": event.get("fill_id"),
        "event_type": event.get("event_type"),
        "intent_id": event.get("intent_id"),
        "side": event.get("side"),
        "quantity": None if _money(event.get("quantity")) is None else _text(_money(event.get("quantity"))),
        "price": None if _money(event.get("price")) is None else _text(_money(event.get("price"))),
        "charges_inr": None if event.get("charges_inr") is None or _money(event.get("charges_inr")) is None else _text(_money(event.get("charges_inr"))),
        "order_quantity": None if _money(event.get("order_quantity")) is None else _text(_money(event.get("order_quantity"))),
        "source": event.get("source"),
        "prior_event_id": event.get("prior_event_id"),
        "statement_id": event.get("statement_id"),
        "completeness": event.get("completeness"),
        "statement_as_of": None if _aware(event.get("statement_as_of")) is None else _aware(event.get("statement_as_of")).isoformat(),
        "underlying": event.get("underlying"),
        "expiry": event.get("expiry"),
        "strike": None if event.get("strike") is None else str(event.get("strike")),
        "option_type": event.get("option_type"),
        "occurred_at": None if _aware(event.get("occurred_at")) is None else _aware(event.get("occurred_at")).isoformat(),
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()
