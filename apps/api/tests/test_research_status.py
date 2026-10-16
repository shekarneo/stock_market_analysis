"""The research desk status is read-only and fail-closed."""

from sqlalchemy import text

from app.db import get_engine
from tests.conftest import login


def _financial_counts():
    with get_engine().connect() as connection:
        row = connection.execute(
            text(
                """
                select
                  (select count(*) from risk_events),
                  (select count(*) from risk_events where event_type = 'FILL'),
                  (select count(*) from paper_transitions),
                  (select count(*) from risk_sessions)
                """
            )
        ).one()
    return tuple(row)


def test_research_status_requires_sign_in_and_stays_disabled(client, db):
    denied = client.get("/api/research/status")
    assert denied.status_code == 401
    assert client.get("/api/accounting/projection").status_code == 401
    login(client)
    body = client.get("/api/research/status").json()
    assert body["paper_trading_active"] is False
    assert body["forecast_ready"] is False
    assert body["paper_approved"] is False
    assert body["live_approved"] is False
    assert body["real_market_data_verified"] is False
    assert body["live_trading_enabled"] is False
    assert body["fills_persisted"] is False
    assert body["broker_called"] is False
    assert body["market_data"] == "unverified"
    assert body["risk_capital_inr"] is None
    codes = [item["code"] for item in body["blockers"]]
    assert "MISSING_RISK_CAPITAL" in codes
    assert "PAPER_TRADING_DISABLED" in codes
    assert "MODEL_NOT_APPROVED" in codes
    options = client.get("/api/options/research")
    assert options.status_code == 200
    proposal = options.json()
    assert proposal["decision"] == "NO_TRADE"
    assert proposal["executable"] is False
    assert proposal["expected_net"] is None
    assert proposal["approvals"]["paper_approved"] is False
    assert proposal["live_trading_enabled"] is False
    accounting = client.get("/api/accounting/status").json()
    assert accounting["fill_accepted"] is False
    assert accounting["fills_persisted"] is False
    assert "FILL" not in accounting["event_types"]
    assert accounting["reconciliation_tolerance"] is None
    assert accounting["reservation_release_status"] == "RULE_UNDEFINED"
    projection = client.get("/api/accounting/projection")
    assert projection.status_code == 200
    projected = projection.json()
    assert projected["role"] == "research_projection"
    assert projected["active_paper_account"] is False
    assert projected["paper_trading_active"] is False
    assert projected["forecast_ready"] is False
    assert projected["paper_approved"] is False
    assert projected["live_approved"] is False
    assert projected["real_market_data_verified"] is False
    assert projected["live_trading_enabled"] is False
    assert projected["ledger_applied"] is False
    assert projected["broker_called"] is False
    assert projected["cash"] == {"status": "unavailable", "value": None}
    assert projected["charges"] == {"status": "unavailable", "value": None}
    assert projected["open_premium"] == {"status": "unavailable", "value": None}
    assert projected["positions"] == {"status": "unavailable", "value": None}
    assert projected["pnl"] == {"status": "unavailable", "value": None}
    assert projected["reservation_release_status"] == "RULE_UNDEFINED"
    assert projected["reservation_release_inr"] is None
    assert projected["first_invalid_event"] is None
    missing = client.get("/api/paper/simulations/does-not-exist")
    assert missing.status_code == 200
    assert missing.json()["fill"] is None
    assert missing.json()["state"] is None


def test_research_reads_do_not_change_financial_rows(client, db):
    login(client)
    before = _financial_counts()
    assert before == (0, 0, 0, 0)
    for path in (
        "/api/research/status",
        "/api/research/decision?underlying=NIFTY",
        "/api/options/research",
        "/api/accounting/status",
        "/api/accounting/projection",
        "/api/paper/simulations/unknown-intent",
        "/api/paper/simulations/bad id",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
    malformed = client.get("/api/paper/simulations/bad id").json()
    assert malformed["fill"] is None
    assert malformed["expected_net"] is None
    assert malformed["state"] is None
    refused = client.post(
        "/api/paper/executions",
        json={
            "event_type": "FILL",
            "event_id": "evt-read-only",
            "intent_id": "intent-read-only",
            "decision_audit_id": 1,
            "body_hash": "abc",
            "side": "BUY",
            "occurred_at": "2026-10-15T09:15:00+05:30",
        },
    )
    assert refused.status_code == 403
    token = client.cookies.get("imm_csrf")
    candidate = client.post(
        "/api/options/candidates",
        json={"provenance": "EXPLICIT_LOCAL_FIXTURE", "underlying": "NIFTY", "expiry": "2026-10-20", "strike": 25000, "option_type": "CE"},
        headers={"x-csrf-token": token},
    )
    assert candidate.status_code == 200
    assert candidate.json()["decision"] == "NO_TRADE"
    assert candidate.json()["expected_net"] is None
    assert _financial_counts() == before
