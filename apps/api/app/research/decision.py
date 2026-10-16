"""Traceable research decision from local inputs.

The index snapshot, registered models, and saved experiments are cited.
None of them becomes an option premium or an expected return. A missing
contract, quote, charge, or risk input keeps the decision at NO_TRADE.
"""

from __future__ import annotations

from app.execution.paper import PAPER_TRADING_ACTIVE
from app.options.proposal import build_research_proposal

SCHEMA = "research-decision-1"
_CONTRACT_FIELDS = ("underlying", "expiry", "strike", "option_type", "lot_size", "tick_size", "quantity")
_QUOTE_FIELDS = ("bid", "ask", "premium")


def build_research_decision(
    *,
    underlying: str | None,
    snapshot: dict | None,
    models: dict | None,
    experiments: dict | None,
    blockers: list | None,
) -> dict:
    """Compose one decision. This does not read a network service or a ledger."""
    proposal = build_research_proposal(None, None)
    market = _market(underlying, snapshot)
    research = _research(models, experiments)
    missing = _missing(proposal, market, blockers)
    return {
        "schema_version": SCHEMA,
        "decision": "NO_TRADE",
        "status": "INCOMPLETE",
        "executable": False,
        "order_connected": False,
        "expected_net": None,
        "expected_return": None,
        "paper_trading_active": PAPER_TRADING_ACTIVE,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
        "live_trading_enabled": False,
        "broker_called": False,
        "quarantine_promoted": False,
        "underlying": underlying,
        "market": market,
        "forecast_research": research,
        "proposal": proposal,
        "missing_inputs": missing,
        "trace": _trace(market, research, proposal, blockers),
    }


def _market(underlying: str | None, snapshot: dict | None) -> dict:
    quotes = snapshot.get("quotes") if isinstance(snapshot, dict) else None
    if not isinstance(quotes, list):
        quotes = []
    quote = next((row for row in quotes if isinstance(row, dict) and row.get("underlying") == underlying), None)
    if underlying is None:
        status = "missing"
        data_class = "missing"
    elif quote is None:
        status = "missing"
        data_class = "missing"
    else:
        status = "observed"
        data_class = _data_class(quote.get("origin"))
    issues = quote.get("issues") if isinstance(quote, dict) else None
    codes = [item.get("code") for item in issues if isinstance(item, dict)] if isinstance(issues, list) else []
    return {
        "status": status,
        "provider": None if not isinstance(snapshot, dict) else snapshot.get("provider"),
        "origin": None if quote is None else quote.get("origin"),
        "data_class": data_class,
        "stale": "STALE_QUOTE" in codes,
        "verified": False,
        "quarantined": False,
        "live_market_data": False,
        "last_price": None if quote is None else quote.get("last_price"),
        "quality": None if quote is None else quote.get("quality"),
        "event_timestamp": None if quote is None else quote.get("event_timestamp"),
        "issue_codes": codes,
        "used_as_option_premium": False,
        "used_as_expected_return": False,
    }


def _data_class(origin: object) -> str:
    if origin == "SYNTHETIC":
        return "synthetic"
    if origin == "DOCUMENTED_SAMPLE":
        return "documented_sample"
    if origin in (None, ""):
        return "unavailable"
    return "unverified"


def _research(models: dict | None, experiments: dict | None) -> dict:
    rows = models.get("models") if isinstance(models, dict) else None
    if not isinstance(rows, list):
        rows = []
    holdout = experiments.get("holdout") if isinstance(experiments, dict) else None
    walk = experiments.get("walk_forward") if isinstance(experiments, dict) else None
    if not isinstance(holdout, list):
        holdout = []
    if not isinstance(walk, list):
        walk = []
    return {
        "forecast_ready": False,
        "approved_forecast_count": 0,
        "expected_return": None,
        "used_as_expected_return": False,
        "models": [
            {
                "model_id": row.get("model_id"),
                "version": row.get("version"),
                "origin": row.get("origin"),
                "training_dataset_id": row.get("training_dataset_id"),
                "forecast_ready": False,
                "paper_approved": False,
                "live_approved": False,
            }
            for row in rows
            if isinstance(row, dict)
        ],
        "holdout_ids": [row.get("experiment_id") for row in holdout if isinstance(row, dict)],
        "walk_forward_ids": [row.get("experiment_id") for row in walk if isinstance(row, dict)],
    }


def _missing(proposal: dict, market: dict, blockers: list | None) -> dict:
    identity = proposal.get("identity") if isinstance(proposal.get("identity"), dict) else {}
    quote = proposal.get("quote") if isinstance(proposal.get("quote"), dict) else {}
    rows = blockers if isinstance(blockers, list) else []
    return {
        "contract": [{"field": field, "status": "missing", "value": None} for field in _CONTRACT_FIELDS if identity.get(field) is None],
        "quote": [{"field": field, "status": "missing", "value": None} for field in _QUOTE_FIELDS if quote.get(field) is None],
        "cost": [{"field": "charges", "status": "unavailable", "value": None, "reason": "CHARGES_UNVERIFIED"}],
        "risk": [{"code": item.get("code"), "class": item.get("class")} for item in rows if isinstance(item, dict)],
        "forecast": [{"field": "expected_return", "status": "unavailable", "value": None, "reason": "NO_APPROVED_FORECAST"}],
        "market_observation": [] if market["status"] == "observed" else [{"field": "underlying_snapshot", "status": "missing", "value": None}],
    }


def _trace(market: dict, research: dict, proposal: dict, blockers: list | None) -> list[dict]:
    rows = blockers if isinstance(blockers, list) else []
    return [
        {
            "source": "synthetic_market_snapshot",
            "provider": market["provider"],
            "underlying_status": market["status"],
            "data_class": market["data_class"],
            "used_as_option_premium": False,
        },
        {
            "source": "model_registry",
            "model_ids": [row["model_id"] for row in research["models"]],
            "used_as_expected_return": False,
        },
        {
            "source": "saved_experiments",
            "holdout_ids": research["holdout_ids"],
            "walk_forward_ids": research["walk_forward_ids"],
            "used_as_expected_return": False,
        },
        {
            "source": "options_research_proposal",
            "schema_version": proposal.get("schema_version"),
            "decision": proposal.get("decision"),
            "expected_net": None,
        },
        {
            "source": "research_status",
            "blocker_codes": [item.get("code") for item in rows if isinstance(item, dict)],
        },
    ]
