"""Tests for V6 Multi-Instrument Forecasting Dashboard and Hub.

Verifies:
1. Instrument catalog completeness and session configuration
2. Independent forecast isolation per instrument (zero leakage)
3. Honest NO TRADE reasons and data gap disclosures
4. Independent walk-forward backtest reporting (NIFTY verified, SENSEX/CRUDE unevaluated)
5. Data health and session calendar classification
6. Safety invariants preservation (all financial flags locked False)
7. FastAPI endpoint responses for multi-instrument suite
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.forecasting.instrument_hub import (
    INSTRUMENT_CATALOG,
    get_instrument_backtest,
    get_instrument_data_health,
    get_instrument_forecast,
    get_supported_instruments,
)
from app.main import app


def test_instrument_catalog_completeness():
    catalog = get_supported_instruments()
    ids = {item["id"] for item in catalog}
    assert "NIFTY" in ids
    assert "SENSEX" in ids
    assert "CRUDEOILMINI" in ids

    nifty = next(c for c in catalog if c["id"] == "NIFTY")
    assert nifty["exchange"] == "NSE"
    assert nifty["contract_lot_size"] == 25
    assert nifty["options_supported"] is True
    assert "15m" in nifty["forecast_horizons"][0]

    sensex = next(c for c in catalog if c["id"] == "SENSEX")
    assert sensex["exchange"] == "BSE"
    assert sensex["contract_lot_size"] == 20
    assert sensex["options_supported"] is True
    assert sensex["validation_status"] == "INDEPENDENT_PROVENANCE_REQUIRED"

    crude = next(c for c in catalog if c["id"] == "CRUDEOILMINI")
    assert crude["exchange"] == "MCX"
    assert crude["contract_lot_size"] == 10
    assert crude["options_supported"] is False  # MCX crude options feed unavailable
    assert crude["validation_status"] == "DATA_FEED_GAP_REPORTED"


def test_independent_forecast_isolation():
    fc_nifty = get_instrument_forecast("NIFTY")
    fc_sensex = get_instrument_forecast("SENSEX")
    fc_crude = get_instrument_forecast("CRUDEOILMINI")

    assert fc_nifty["instrument"] == "NIFTY"
    assert fc_sensex["instrument"] == "SENSEX"
    assert fc_crude["instrument"] == "CRUDEOILMINI"

    # Isolation Check: SENSEX does not copy NIFTY probability or direction
    assert fc_sensex["decision"] == "NO TRADE"
    assert fc_sensex["predicted_direction"] == "UNKNOWN"
    assert fc_sensex["calibrated_probability"] is None
    assert any("NO_FITTED_MODEL" in r for r in fc_sensex["reasons_for_no_trade"])

    # Crude Oil Mini: reports data feed gap and does not fabricate prediction
    assert fc_crude["decision"] == "NO TRADE"
    assert fc_crude["predicted_direction"] == "UNKNOWN"
    assert fc_crude["calibrated_probability"] is None
    assert any("DATA_FEED_GAP" in r for r in fc_crude["reasons_for_no_trade"])
    assert any("OPTIONS_DATA_UNAVAILABLE" in r for r in fc_crude["reasons_for_no_trade"])

    # All forecasts preserve safety locks
    assert fc_nifty["safety_controls_locked"] is True
    assert fc_sensex["safety_controls_locked"] is True
    assert fc_crude["safety_controls_locked"] is True


def test_independent_backtest_reporting():
    bt_nifty = get_instrument_backtest("NIFTY")
    bt_sensex = get_instrument_backtest("SENSEX")
    bt_crude = get_instrument_backtest("CRUDEOILMINI")

    # NIFTY has verified walk-forward
    assert bt_nifty["evaluation_status"] == "VERIFIED_WALK_FORWARD"
    assert bt_nifty["folds_summary"]["total_folds"] == 19
    assert bt_nifty["performance_after_costs"]["full_period_max_drawdown"] == 9.62
    assert bt_nifty["performance_after_costs"]["local_holdout_window_drawdown"] == 0.04
    assert bt_nifty["performance_after_costs"]["statutory_friction_bps"] == 2.0

    # SENSEX: Unevaluated, requires independent dataset
    assert bt_sensex["evaluation_status"] == "UNEVALUATED"
    assert "independent BSE SENSEX historical dataset" in bt_sensex["reason"]

    # CRUDEOILMINI: Unevaluated, reports data feed gap
    assert bt_crude["evaluation_status"] == "UNEVALUATED"
    assert "MCX historical commodity tick and candle data is not supplied" in bt_crude["reason"]


def test_data_health_and_session_calendars():
    health = get_instrument_data_health()
    assert health["total_instruments_configured"] == 3
    items = {item["instrument"]: item for item in health["primary_instruments"]}

    assert items["NIFTY"]["health_status"] == "HEALTHY_VERIFIED"
    assert items["SENSEX"]["health_status"] == "PARTIAL_LTP_ONLY"
    assert items["CRUDEOILMINI"]["health_status"] == "DATA_FEED_GAP"

    invariants = health["safety_invariants"]
    assert invariants["live_trading_enabled"] is False
    assert invariants["order_placement_allowed"] is False
    assert invariants["capital_commitment_allowed"] is False
    assert invariants["synthetic_orders_only"] is True
    assert invariants["real_money_loss_risk"] is False


def test_api_endpoints_integration(client: TestClient):
    from tests.conftest import login
    login(client)

    res_inst = client.get("/api/forecasting/instruments")
    assert res_inst.status_code == 200
    inst_data = res_inst.json()
    assert "instruments" in inst_data
    assert len(inst_data["instruments"]) == 3

    for sym in ["NIFTY", "SENSEX", "CRUDEOILMINI"]:
        res_fc = client.get(f"/api/forecasting/instrument-forecast?instrument={sym}")
        assert res_fc.status_code == 200
        fc = res_fc.json()
        assert fc["instrument"] == sym
        assert "decision" in fc
        assert "reasons_for_no_trade" in fc
        assert "transaction_cost_assumptions" in fc

        res_bt = client.get(f"/api/forecasting/instrument-backtest?instrument={sym}")
        assert res_bt.status_code == 200
        bt = res_bt.json()
        assert bt["instrument"] == sym
        assert "evaluation_status" in bt

    res_health = client.get("/api/market/data-health")
    assert res_health.status_code == 200
    h_data = res_health.json()
    assert "primary_instruments" in h_data
    assert len(h_data["primary_instruments"]) == 3


def test_train_benchmark_endpoint_requires_auth(client: TestClient):
    res = client.post(
        "/api/forecasting/train-benchmark",
        json={"instrument": "NIFTY", "model_type": "lightgbm", "strategy_mode": "regime_gated"},
    )
    assert res.status_code in {401, 403}


def test_train_benchmark_endpoint_missing_dataset(client: TestClient):
    from tests.conftest import login
    login(client)

    res = client.post(
        "/api/forecasting/train-benchmark",
        json={"instrument": "GOLDMINI", "model_type": "lightgbm", "strategy_mode": "regime_gated"},
    )
    assert res.status_code == 400
    body = res.json()
    assert body["code"] == "DATASET_NOT_FOUND"


def test_train_benchmark_endpoint_crudeoilmini(client: TestClient):
    from tests.conftest import login
    login(client)

    res = client.post(
        "/api/forecasting/train-benchmark",
        json={"instrument": "CRUDEOILMINI", "model_type": "lightgbm", "strategy_mode": "deadband"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["instrument"] == "CRUDEOILMINI"
    assert body["num_folds"] == 19



def test_train_benchmark_endpoint_sensex(client: TestClient):
    from tests.conftest import login
    login(client)

    res = client.post(
        "/api/forecasting/train-benchmark",
        json={"instrument": "SENSEX", "model_type": "lightgbm", "strategy_mode": "deadband"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["instrument"] == "SENSEX"
    assert body["num_folds"] == 19



def test_train_benchmark_endpoint_nifty(client: TestClient):
    from tests.conftest import login
    login(client)

    res = client.post(
        "/api/forecasting/train-benchmark",
        json={"instrument": "NIFTY", "model_type": "lightgbm", "strategy_mode": "regime_gated", "folds": 2},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["instrument"] == "NIFTY"
    assert "all_strategies" in body
    assert body["num_folds"] > 0
    assert "holdout_accuracy" in body
    assert "holdout_brier_skill_score" in body

