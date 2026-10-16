"""An explicit option fixture stays a research input."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db import get_engine
from app.execution.orders import live_order_calls
from app.execution.paper import PAPER_TRADING_ACTIVE
from app.options.candidate import assess_option_candidate
from tests.conftest import login

AT = datetime(2026, 10, 15, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def _decision():
    return {
        "schema_version": "research-decision-1",
        "decision": "NO_TRADE",
        "underlying": "NIFTY",
        "market": {"status": "observed", "data_class": "synthetic", "last_price": 11111.5, "stale": True},
        "forecast_research": {
            "approved_forecast_count": 0,
            "expected_return": None,
            "models": [{"model_id": "last_return_sign"}],
            "holdout_ids": ["hold-1"],
            "walk_forward_ids": ["walk-1"],
        },
        "missing_inputs": {"risk": [{"code": "MISSING_RISK_CAPITAL", "class": "operator"}]},
    }


def _fixture(**extra):
    payload = {
        "provenance": "EXPLICIT_LOCAL_FIXTURE",
        "underlying": "NIFTY",
        "exchange": "NSE",
        "segment": "FNO",
        "expiry": "2026-10-20",
        "strike": 25000,
        "option_type": "CE",
        "trading_symbol": "NIFTY26OCT25000CE",
        "instrument_id": "NIFTY26OCT25000CE",
        "lot_size": 25,
        "tick_size": 0.05,
    }
    payload.update(extra)
    return payload


def _codes(result):
    return {item["code"] for item in result["errors"]}


def _blocker_codes(result):
    return {item["code"] for item in result["blockers"]}


def _evidence(result, name):
    return next(item for item in result["evidence"] if item["name"] == name)


def _identity(result, field):
    return next(item for item in result["identity"] if item["field"] == field)


def test_a_complete_looking_fixture_stays_unverified_and_unpriced():
    result = assess_option_candidate(
        _fixture(bid=180, ask=182, quote_timestamp="2026-10-15T09:59:50+05:30"),
        decision=_decision(),
        as_of=AT,
    )
    assert result["ok"] is True
    assert result["decision"] == "NO_TRADE"
    assert result["tradable"] is False
    assert result["listed"] is None
    assert result["expected_net"] is None
    assert result["expected_return"] is None
    assert result["forecast_ready"] is False
    assert result["paper_approved"] is False
    assert result["live_approved"] is False
    assert result["real_market_data_verified"] is False
    quote = _evidence(result, "option_quote")
    assert quote["premium"] is None
    assert quote["ask"] == 182
    assert quote["verified"] is False
    index = _evidence(result, "index_observation")
    assert index["last_price"] == 11111.5
    assert index["used_as_option_premium"] is False
    assert index["last_price"] != quote["premium"]
    assert _identity(result, "exchange")["verified"] is False
    assert _identity(result, "lot_size")["reason"] == "LOT_TICK_UNVERIFIED"
    assert _evidence(result, "charges")["value"] is None
    assert _evidence(result, "forecast")["expected_return"] is None
    assert _evidence(result, "contract_master")["value"] is None
    assert result["proposal"]["quote_premium"] is None
    assert result["decision_record"]["model_ids"] == ["last_return_sign"]
    assert "TRADABILITY_NOT_ESTABLISHED" in _blocker_codes(result)
    assert live_order_calls == []
    assert PAPER_TRADING_ACTIVE is False


def test_omitted_identity_stays_missing_and_invalid_values_are_refused():
    missing = assess_option_candidate(_fixture(expiry=None, strike=None, option_type=None), decision=_decision(), as_of=AT)
    assert missing["decision"] == "NO_TRADE"
    assert _identity(missing, "expiry") == {"field": "expiry", "status": "missing", "value": None, "verified": False, "reason": None}
    assert _identity(missing, "strike")["status"] == "missing"
    assert _identity(missing, "option_type")["status"] == "missing"
    assert _identity(missing, "underlying")["value"] == "NIFTY"
    assert {"MISSING_EXPIRY", "MISSING_STRIKE", "MISSING_OPTION_TYPE"} <= _blocker_codes(missing)
    invalid = assess_option_candidate(_fixture(strike=-1, option_type="CALL", expiry="tomorrow"), decision=_decision(), as_of=AT)
    assert invalid["ok"] is False
    assert invalid["decision"] == "NO_TRADE"
    assert invalid["expected_net"] is None
    assert {"INVALID_STRIKE", "INVALID_OPTION_TYPE", "INVALID_EXPIRY"} <= _codes(invalid)
    conflict = assess_option_candidate(_fixture(option_type="CE", trading_symbol="NIFTY26OCT25000PE", instrument_id="BANKNIFTY26OCT25000CE"), decision=_decision(), as_of=AT)
    assert conflict["ok"] is False
    assert "CONFLICTING_IDENTITY" in _codes(conflict)
    assert conflict["tradable"] is False


def test_quote_charge_forecast_and_capital_gaps_do_not_create_a_premium():
    bare = assess_option_candidate(_fixture(), decision=_decision(), as_of=AT)
    assert _evidence(bare, "option_quote")["status"] == "missing"
    assert _evidence(bare, "option_quote")["premium"] is None
    stale = assess_option_candidate(
        _fixture(bid=10, ask=11, quote_timestamp="2020-01-01T00:00:00+05:30"),
        decision=_decision(),
        as_of=AT,
    )
    assert _evidence(stale, "option_quote")["freshness"] == "stale"
    assert _evidence(stale, "option_quote")["premium"] is None
    assert stale["expected_net"] is None
    undated = assess_option_candidate(_fixture(bid=10, ask=11), decision=_decision(), as_of=AT)
    assert _evidence(undated, "option_quote")["reason"] == "MISSING_QUOTE_TIMESTAMP"
    assert _evidence(bare, "charges")["reason"] == "CHARGES_UNVERIFIED"
    assert _evidence(bare, "forecast")["reason"] == "NO_APPROVED_FORECAST"
    assert _evidence(bare, "risk_capital")["reason"] == "MISSING_RISK_CAPITAL"
    assert _identity(bare, "lot_size")["verified"] is False
    no_size = assess_option_candidate(_fixture(lot_size=None, tick_size=None), decision=_decision(), as_of=AT)
    assert _identity(no_size, "lot_size")["status"] == "missing"
    assert _identity(no_size, "tick_size")["value"] is None


def _counts():
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


def test_candidate_route_refuses_a_bad_fixture_and_does_not_change_financial_rows(client, db):
    assert client.post("/api/options/candidates", json=_fixture()).status_code == 401
    token = login(client)
    assert client.post("/api/options/candidates", json=_fixture()).status_code == 403
    before = _counts()
    assert before == (0, 0, 0, 0)
    accepted = client.post("/api/options/candidates", json=_fixture(bid=180, ask=182), headers={"x-csrf-token": token})
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["decision"] == "NO_TRADE"
    assert body["expected_net"] is None
    assert body["tradable"] is False
    assert body["paper_approved"] is False
    assert body["live_approved"] is False
    assert body["forecast_ready"] is False
    assert body["real_market_data_verified"] is False
    assert body["live_trading_enabled"] is False
    quote = _evidence(body, "option_quote")
    assert quote["premium"] is None
    assert _evidence(body, "index_observation")["used_as_option_premium"] is False
    malformed = client.post("/api/options/candidates", json={"provenance": "EXPLICIT_LOCAL_FIXTURE", "paper_approved": True}, headers={"x-csrf-token": token})
    assert malformed.status_code == 422
    invalid = client.post("/api/options/candidates", json=_fixture(strike=-5), headers={"x-csrf-token": token})
    assert invalid.status_code == 422
    assert "INVALID_STRIKE" in _codes(invalid.json())
    assert _counts() == before
    assert live_order_calls == []
