"""GET /api/research/paper-readiness serializes the dataclass report (it used to 500)."""

from __future__ import annotations

import json

from app.research import paper_readiness_audit as audit_module
from app.research.paper_readiness_audit import PaperReadinessReport, ReadinessGateResult


def _report() -> PaperReadinessReport:
    gate = ReadinessGateResult("G1", "Safety", "PASSED", "Kill switch wired", "test", {"checks": 3})
    return PaperReadinessReport(
        evaluated_at="2026-10-23T08:00:00+00:00", overall_readiness="BLOCKED", live_trading_verdict="STRICT_NO_GO_LOCKED",
        total_gates_evaluated=1, passed_gates=1, warning_gates=0, failed_gates=0, gates={"G1": gate},
        safety_invariants={"live_trading_disabled": True}, active_blockers=["RISK_CONFIG_MISSING"], audit_notes=[],
    )


def test_route_returns_a_json_serializable_dict(monkeypatch):
    """No Postgres needed: the route is called directly with the audit stubbed."""
    import app.main as main

    monkeypatch.setattr(main, "read_session", lambda request, settings: {"username": "op"})
    monkeypatch.setattr(audit_module, "audit_paper_trading_readiness", lambda session: _report())
    body = main.read_paper_readiness(request=None, session=None, settings=None)
    assert isinstance(body, dict)
    assert body["gates"]["G1"]["status"] == "PASSED"
    assert body["live_trading_verdict"] == "STRICT_NO_GO_LOCKED" and body["live_approved"] is False
    json.dumps(body)


def test_endpoint_over_http(client):
    from tests.conftest import login

    assert client.get("/api/research/paper-readiness").status_code in {401, 403}
    login(client)
    response = client.get("/api/research/paper-readiness")
    assert response.status_code == 200
    body = response.json()
    assert body["total_gates_evaluated"] == len(body["gates"])
    assert body["live_trading_verdict"] == "STRICT_NO_GO_LOCKED"
