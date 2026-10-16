"""Review an M8 research proposal. The review does not create an order."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.risk.gates import evaluate

_FLAGS = {
    "forecast_ready": False,
    "paper_approved": False,
    "live_approved": False,
    "real_market_data_verified": False,
}


def review_proposal(proposal: dict | None, *, session: Session | None) -> dict:
    if not isinstance(proposal, dict) or proposal.get("schema_version") != "m8-proposal-1":
        return _blocked(["INVALID_PROPOSAL"])
    risk = evaluate(
        {
            "mode": "PAPER",
            "intent_purpose": "ENTRY",
            "underlying": proposal.get("identity", {}).get("underlying") if isinstance(proposal.get("identity"), dict) else None,
            "quote": proposal.get("quote"),
            "forecast": proposal.get("forecast"),
            "expected_net": proposal.get("expected_net"),
            "ask": proposal.get("quote", {}).get("ask") if isinstance(proposal.get("quote"), dict) else None,
            "lot_size": proposal.get("identity", {}).get("lot_size") if isinstance(proposal.get("identity"), dict) else None,
        },
        session=session,
    )
    reasons = ["RESEARCH_PROPOSAL_NOT_AN_ORDER", *risk["reasons"]]
    if proposal.get("paper_approved") is True or proposal.get("live_approved") is True or proposal.get("executable") is True:
        reasons.append("APPROVAL_FLAG_IGNORED")
    return {
        "executable": False,
        "order_created": False,
        "simulated_fill": None,
        "market_fill": False,
        "decision": "NO_TRADE",
        "status": proposal.get("status"),
        "reasons": reasons,
        "risk_result": risk["result"],
        **_FLAGS,
    }


def _blocked(reasons: list[str]) -> dict:
    return {
        "executable": False,
        "order_created": False,
        "simulated_fill": None,
        "market_fill": False,
        "decision": "NO_TRADE",
        "status": None,
        "reasons": reasons,
        "risk_result": "VETO",
        **_FLAGS,
    }
