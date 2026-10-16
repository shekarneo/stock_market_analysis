"""A research decision cites local inputs and does not invent a trade."""

from app.execution.orders import live_order_calls
from app.execution.paper import PAPER_TRADING_ACTIVE
from app.research.decision import build_research_decision
from tests.conftest import login


def _snapshot():
    return {
        "provider": "synthetic",
        "origin": "SYNTHETIC",
        "quotes": [
            {
                "underlying": "NIFTY",
                "last_price": 11111.5,
                "origin": "SYNTHETIC",
                "quality": "WARN",
                "event_timestamp": "2026-10-15T09:15:00+05:30",
                "issues": [{"code": "STALE_QUOTE"}],
            }
        ],
    }


def _models():
    return {
        "models": [
            {
                "model_id": "last_return_sign",
                "version": "v1",
                "origin": "SYNTHETIC",
                "training_dataset_id": "dataset-1",
                "forecast_ready": True,
                "paper_approved": True,
                "live_approved": True,
            }
        ]
    }


def _experiments():
    return {"holdout": [{"experiment_id": "hold-1"}], "walk_forward": [{"experiment_id": "walk-1"}]}


def test_decision_cites_inputs_and_does_not_price_the_option():
    decision = build_research_decision(
        underlying="NIFTY",
        snapshot=_snapshot(),
        models=_models(),
        experiments=_experiments(),
        blockers=[{"code": "MISSING_RISK_CAPITAL", "class": "operator"}, {"code": "CHARGES_UNVERIFIED", "class": "external"}],
    )
    assert decision["decision"] == "NO_TRADE"
    assert decision["executable"] is False
    assert decision["expected_net"] is None
    assert decision["expected_return"] is None
    assert decision["market"]["last_price"] == 11111.5
    assert decision["market"]["data_class"] == "synthetic"
    assert decision["market"]["stale"] is True
    assert decision["market"]["verified"] is False
    assert decision["market"]["quarantined"] is False
    assert decision["market"]["used_as_option_premium"] is False
    assert decision["proposal"]["quote"]["premium"] is None
    assert decision["proposal"]["expected_net"] is None
    assert decision["forecast_research"]["models"][0]["model_id"] == "last_return_sign"
    assert decision["forecast_research"]["models"][0]["forecast_ready"] is False
    assert decision["forecast_research"]["models"][0]["paper_approved"] is False
    assert decision["forecast_research"]["holdout_ids"] == ["hold-1"]
    assert decision["forecast_research"]["walk_forward_ids"] == ["walk-1"]
    assert decision["forecast_research"]["used_as_expected_return"] is False
    assert decision["forecast_research"]["expected_return"] is None
    missing = decision["missing_inputs"]
    assert {item["field"] for item in missing["contract"]} >= {"expiry", "strike", "option_type", "lot_size", "tick_size", "quantity"}
    assert {item["field"] for item in missing["quote"]} == {"bid", "ask", "premium"}
    assert missing["cost"][0]["value"] is None
    assert missing["forecast"][0]["reason"] == "NO_APPROVED_FORECAST"
    assert "MISSING_RISK_CAPITAL" in {item["code"] for item in missing["risk"]}
    assert decision["quarantine_promoted"] is False
    assert decision["paper_trading_active"] is False
    assert decision["forecast_ready"] is False
    assert decision["paper_approved"] is False
    assert decision["live_approved"] is False
    assert decision["real_market_data_verified"] is False
    assert decision["live_trading_enabled"] is False
    assert decision["broker_called"] is False
    assert {item["source"] for item in decision["trace"]} == {
        "synthetic_market_snapshot",
        "model_registry",
        "saved_experiments",
        "options_research_proposal",
        "research_status",
    }
    assert live_order_calls == []
    assert PAPER_TRADING_ACTIVE is False


def test_a_missing_snapshot_stays_missing():
    decision = build_research_decision(underlying="SENSEX", snapshot=_snapshot(), models={"models": []}, experiments={}, blockers=[])
    assert decision["decision"] == "NO_TRADE"
    assert decision["market"]["status"] == "missing"
    assert decision["market"]["data_class"] == "missing"
    assert decision["market"]["last_price"] is None
    assert decision["missing_inputs"]["market_observation"][0]["field"] == "underlying_snapshot"
    assert decision["proposal"]["quote"]["premium"] is None


def test_an_unverified_origin_is_not_called_synthetic():
    snapshot = _snapshot()
    snapshot["quotes"][0]["origin"] = "PROVIDER"
    decision = build_research_decision(underlying="NIFTY", snapshot=snapshot, models=None, experiments=None, blockers=None)
    assert decision["market"]["data_class"] == "unverified"
    assert decision["market"]["verified"] is False
    assert decision["real_market_data_verified"] is False


def test_decision_route_uses_the_synthetic_snapshot_and_refuses_another_underlying(client, db):
    assert client.get("/api/research/decision").status_code == 401
    login(client)
    body = client.get("/api/research/decision", params={"underlying": "NIFTY"}).json()
    assert body["decision"] == "NO_TRADE"
    assert body["expected_net"] is None
    assert body["market"]["data_class"] == "synthetic"
    assert body["market"]["used_as_option_premium"] is False
    assert body["proposal"]["quote"]["premium"] is None
    assert body["proposal"]["expected_net"] is None
    assert body["broker_called"] is False
    assert body["paper_trading_active"] is False
    assert body["forecast_ready"] is False
    assert body["real_market_data_verified"] is False
    assert body["quarantine_promoted"] is False
    if body["market"]["last_price"] is not None:
        assert body["market"]["last_price"] != body["proposal"]["quote"]["premium"]
    refused = client.get("/api/research/decision", params={"underlying": "RELIANCE"})
    assert refused.status_code == 400
    assert refused.json()["code"] == "INVALID_UNDERLYING"
    absent = client.get("/api/research/decision").json()
    assert absent["underlying"] is None
    assert absent["market"]["status"] == "missing"
    assert absent["decision"] == "NO_TRADE"
    assert live_order_calls == []
