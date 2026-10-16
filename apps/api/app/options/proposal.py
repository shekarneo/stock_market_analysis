"""Research proposal contract. A proposal is not an order.

The options spec separates a quoted ask, a modelled value, a forecast, scenario
inputs, charges, and expected net. This module records those fields and the
risk gates that can be checked without a ledger. It does not size a position,
replace missing charges with zero, or call the order function.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from app.instruments import OPTION_UNDERLYINGS
from app.options.expected_value import evaluate_expected_value
from app.options.pricing import price_contract
from app.options.validation import validate_option_inputs

SCHEMA = "m8-proposal-1"
_ENTRY_FIELDS = (
    ("entry_trigger", "MISSING_ENTRY_TRIGGER"),
    ("order_type", "MISSING_ORDER_TYPE"),
    ("invalidation", "MISSING_INVALIDATION"),
    ("exit_plan", "MISSING_EXIT_PLAN"),
    ("time_stop", "MISSING_TIME_STOP"),
    ("counterargument", "MISSING_COUNTERARGUMENT"),
)
_UNEVALUATED_GATES = (
    ("mode", "The operating mode is not evaluated by the research proposal."),
    ("kill_switch", "No kill-switch row is read by the research proposal."),
    ("exchange_calendar", "No exchange calendar is read by the research proposal."),
    ("broker_funds", "No funds read is made by the research proposal."),
    ("exposure", "No risk ledger is read by the research proposal."),
    ("position_limits", "Open-position and session counts are not read here."),
    ("reconciliation", "Broker positions are not compared here."),
)
_UNCONFIGURED_GATES = (
    ("spread_volume_open_interest", "No spread, volume, or open-interest floor is configured."),
    ("expiry_allow_list", "No expiry allow-list is configured."),
    ("iv_stress", "No IV stress is configured."),
    ("extrapolation_bound", "No extrapolation bound is configured."),
)
_FLAGS = {
    "forecast_ready": False,
    "paper_approved": False,
    "live_approved": False,
    "real_market_data_verified": False,
}


def build_research_proposal(
    forecast: dict | None,
    contract: dict | None,
    costs: dict | None = None,
    *,
    task_horizon: str | None = None,
    as_of: datetime | None = None,
    max_age: timedelta | None = None,
    risk: dict | None = None,
    siblings: list[dict] | None = None,
    ranked: bool = False,
    entry_plan: dict | None = None,
) -> dict:
    """Record one research candidate. The decision stays NO_TRADE."""
    valuation = evaluate_expected_value(
        forecast,
        contract if isinstance(contract, dict) else None,
        costs,
        task_horizon=task_horizon,
        as_of=as_of,
        max_age=max_age,
    )
    quote_report = validate_option_inputs(contract, as_of=as_of, max_age=max_age) if isinstance(contract, dict) else None
    reasons = list(valuation["reasons"])
    if not isinstance(contract, dict):
        reasons.append("INVALID_CONTRACT")
    reasons.extend(_identity_reasons(contract, siblings))
    reasons.extend(_plan_reasons(entry_plan))
    reasons.extend(_risk_reasons(risk))
    reasons.extend(_scenarios(forecast)["reasons"])
    if _tick_missing(contract):
        reasons.append("MISSING_TICK_SIZE")
    reasons.append("MISSING_QUANTITY")
    if _risk_capital_missing():
        reasons.append("MISSING_RISK_CAPITAL")
    reasons.append("MISSING_ADVERSE_SLICE")
    if ranked:
        reasons.append("RANK_IS_NOT_AN_ORDER")
    reasons = list(dict.fromkeys(reasons))
    qualitative = isinstance(forecast, dict) and forecast.get("is_qualitative") is True
    priced = {method: price_contract(contract if isinstance(contract, dict) else {}, method) for method in ("MODELLED_VENDOR_GREEKS", "MODELLED_BLACK76")}
    proposal = {
        "schema_version": SCHEMA,
        "status": "COMPLETE" if qualitative else "INCOMPLETE",
        "decision": "NO_TRADE",
        "decision_reason": reasons[0] if reasons else "NO_APPROVED_FORECAST",
        "decision_reasons": reasons,
        "executable": False,
        "order_connected": False,
        "quote": _quote(contract, quote_report),
        "modelled_value": _modelled(contract, priced),
        "forecast": _forecast(forecast, task_horizon),
        "scenarios": _scenarios(forecast),
        "gross_expected": None,
        "charges": _charges(costs, reasons),
        "expected_net": None,
        "identity": _identity(contract, reasons),
        "risk": _risk(risk, reasons),
        "research_candidate": {
            "status": "REJECTED",
            "ranked": bool(ranked),
            "executable": False,
            "reasons": reasons,
        },
        "approvals": _approvals(forecast),
    }
    return proposal


def _quote(contract: dict | None, report: dict | None) -> dict:
    accepted = report["accepted"] if report and report["ok"] else None
    origin = contract.get("origin") if isinstance(contract, dict) else None
    return {
        "accepted": accepted is not None,
        "origin": origin,
        "market_observation": False,
        "bid": None if accepted is None else accepted.get("bid"),
        "ask": None if accepted is None else accepted.get("ask"),
        "premium": None if accepted is None else accepted.get("ask"),
        "premium_role": None if accepted is None else "QUOTED_ASK",
        "ltp": None if accepted is None else accepted.get("ltp"),
        "quote_timestamp": None if accepted is None else accepted.get("quote_timestamp"),
        "usable_as_quote": accepted is not None and origin == "UNVERIFIED_MARKET_INPUT",
    }


def _modelled(contract: dict | None, priced: dict) -> dict:
    supplied = None
    if isinstance(contract, dict) and contract.get("origin") == "CALCULATED":
        supplied = contract.get("premium")
    return {
        "value": None,
        "supplied_calculated_premium": supplied,
        "accepted_as_quote": False,
        "usable_as_quote": False,
        "status": "UNAVAILABLE",
        "methods": {name: {"enabled": item["enabled"], "premium": item["premium"]} for name, item in priced.items()},
    }


def _forecast(forecast: dict | None, task_horizon: str | None) -> dict:
    state = forecast.get("promotion_state") if isinstance(forecast, dict) else None
    return {
        "present": isinstance(forecast, dict),
        "horizon": forecast.get("horizon") if isinstance(forecast, dict) else None,
        "task_horizon": task_horizon,
        "promotion_state": state,
        "is_qualitative": forecast.get("is_qualitative") if isinstance(forecast, dict) else None,
        "model_version": forecast.get("model_version") if isinstance(forecast, dict) else None,
        "research_selected": state == "APPROVED_FOR_RESEARCH",
        "claims_paper_approval": state == "APPROVED_FOR_PAPER",
        "claims_live_approval": state == "APPROVED_FOR_LIVE",
    }


def _scenarios(forecast: dict | None) -> dict:
    source = forecast if isinstance(forecast, dict) else {}
    probabilities = {name: source.get(f"p_{name}") for name in ("up", "range", "down")}
    assumptions = {name: source.get(f"r_{name}") for name in ("up", "range", "down")}
    missing = [name for name in ("up", "range", "down") if source.get(f"p_{name}") is None or source.get(f"r_{name}") is None]
    return {
        "probabilities": probabilities,
        "assumptions": assumptions,
        "status": "UNAVAILABLE" if missing or not isinstance(forecast, dict) else "SUPPLIED",
        "reasons": ["MISSING_SCENARIO_INPUTS"] if missing or not isinstance(forecast, dict) else [],
    }


def _charges(costs: dict | None, reasons: list[str]) -> dict:
    return {
        "amount": None,
        "source": None,
        "verified": False,
        "supplied_amount_used": False,
        "reasons": [code for code in ("MISSING_CHARGES", "CHARGES_UNVERIFIED") if code in reasons],
    }


def _identity(contract: dict | None, reasons: list[str]) -> dict:
    source = contract if isinstance(contract, dict) else {}
    return {
        "underlying": source.get("underlying"),
        "expiry": source.get("expiry"),
        "strike": source.get("strike"),
        "option_type": source.get("option_type"),
        "trading_symbol": source.get("trading_symbol"),
        "groww_symbol": source.get("groww_symbol"),
        "broker_symbol": source.get("broker_symbol"),
        "lot_size": source.get("lot_size"),
        "tick_size": source.get("tick_size"),
        "lot_count": None,
        "quantity": None,
        "duplicate": "DUPLICATE_CONTRACT" in reasons,
    }


def _risk(risk: dict | None, reasons: list[str]) -> dict:
    gates = [
        {"name": "expected_net", "state": "VETO", "applied": True, "detail": "EXPECTED_NET_UNAVAILABLE"},
        {"name": "forecast_approval", "state": "VETO", "applied": True, "detail": "PAPER_AND_LIVE_APPROVAL_NOT_GRANTED"},
        {"name": "charges", "state": "VETO", "applied": True, "detail": "CHARGES_UNAVAILABLE"},
        _allow_list_gate(reasons),
    ]
    for name, detail in _UNEVALUATED_GATES:
        gates.append({"name": name, "state": "NOT_EVALUATED", "applied": False, "detail": detail})
    for name, detail in _UNCONFIGURED_GATES:
        gates.append({"name": name, "state": "NOT_CONFIGURED", "applied": False, "detail": detail})
    if isinstance(risk, dict) and isinstance(risk.get("gates"), list):
        for gate in risk["gates"]:
            if isinstance(gate, dict):
                gates.append({"name": gate.get("name"), "state": "SUPPLIED", "applied": False, "detail": gate.get("detail")})
    return {
        "result": "VETO",
        "passed": False,
        "gates": gates,
        "reasons": [code for code in reasons if code.startswith("RISK_") or code.startswith("MISSING_RISK") or code == "INVALID_RISK_RESULT"],
    }


def _allow_list_gate(reasons: list[str]) -> dict:
    failed = any(code in reasons for code in ("INVALID_UNDERLYING", "INVALID_OPTION_TYPE", "INVALID_CONTRACT"))
    return {
        "name": "allow_list",
        "state": "VETO" if failed else "PASS",
        "applied": True,
        "detail": f"Configured long {' and '.join(OPTION_UNDERLYINGS)} structures only. Unconfigured floors are not applied.",
    }


def _approvals(forecast: dict | None) -> dict:
    state = forecast.get("promotion_state") if isinstance(forecast, dict) else None
    return {
        "forecast_promotion_state": state,
        "research_selected": state == "APPROVED_FOR_RESEARCH",
        "paper_approved": False,
        "live_approved": False,
        **{key: value for key, value in _FLAGS.items() if key not in {"paper_approved", "live_approved"}},
    }


def _identity_reasons(contract: dict | None, siblings: list[dict] | None) -> list[str]:
    if not isinstance(contract, dict) or not isinstance(siblings, list):
        return []
    identity = (contract.get("underlying"), contract.get("expiry"), contract.get("strike"), contract.get("option_type"))
    if any(part is None for part in identity):
        return ["INVALID_CONTRACT_IDENTITY"]
    for sibling in siblings:
        if not isinstance(sibling, dict):
            continue
        other = (sibling.get("underlying"), sibling.get("expiry"), sibling.get("strike"), sibling.get("option_type"))
        if other == identity:
            return ["DUPLICATE_CONTRACT"]
    return []


def _plan_reasons(entry_plan: dict | None) -> list[str]:
    source = entry_plan if isinstance(entry_plan, dict) else {}
    reasons = []
    for field, code in _ENTRY_FIELDS:
        value = source.get(field)
        if not isinstance(value, str) or not value.strip():
            reasons.append(code)
    return reasons


def _risk_reasons(risk: dict | None) -> list[str]:
    if risk is None:
        return ["MISSING_RISK_RESULT", "RISK_NOT_EVALUATED"]
    if not isinstance(risk, dict) or risk.get("result") not in {"PASS", "VETO"}:
        return ["INVALID_RISK_RESULT", "RISK_NOT_EVALUATED"]
    reasons = ["RISK_NOT_EVALUATED"]
    if risk.get("result") == "VETO":
        reasons.append("RISK_VETO")
    if risk.get("result") == "PASS":
        reasons.append("RISK_PASS_REFUSED")
    return reasons


def _tick_missing(contract: dict | None) -> bool:
    return not isinstance(contract, dict) or contract.get("tick_size") is None


def _risk_capital_missing() -> bool:
    from app.config.loader import load_defaults
    from app.settings import REPO_ROOT

    config = load_defaults(Path(REPO_ROOT / "config" / "defaults.yaml"))
    return config.risk.risk_capital_inr is None
