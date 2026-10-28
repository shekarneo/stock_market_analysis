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

import json

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
    from app.instrument_specs import lot_size_for
    assert nifty["contract_lot_size"] == lot_size_for("NIFTY")
    assert nifty["options_supported"] is True
    assert "15-minute" in nifty["forecast_horizons"][0]
    assert nifty["validation_status"] == "RANGE_VALIDATED"
    assert "6,227" not in (nifty["available_history"] or "")  # never a hard-coded count

    sensex = next(c for c in catalog if c["id"] == "SENSEX")
    assert sensex["exchange"] == "BSE"
    assert sensex["contract_lot_size"] == 20
    assert sensex["options_supported"] is True
    assert sensex["validation_status"] == "RANGE_VALIDATED"

    crude = next(c for c in catalog if c["id"] == "CRUDEOILMINI")
    assert crude["exchange"] == "MCX"
    assert crude["contract_lot_size"] == 10
    assert crude["options_supported"] is False  # MCX crude options feed unavailable
    assert crude["validation_status"] == "DATA_FEED_GAP_REPORTED"


def test_history_depth_reports_the_saved_series(tmp_path, monkeypatch):
    from app.forecasting import instrument_hub
    from app.market import history_loader as hl

    monkeypatch.setattr(hl, "HISTORY_DIR", tmp_path)
    monkeypatch.setattr(instrument_hub, "_depth_cache", {})
    assert instrument_hub.history_depth("NSE-NIFTY") == "No saved history yet (fetch it on the Backtest page)"
    for interval, count, first in (("15minute", 45907, "2020-01-01T09:15:00+05:30"), ("1day", 1694, "2020-01-01T00:00:00+05:30")):
        hl.series_path("NSE-NIFTY", interval, tmp_path).write_text(
            json.dumps({"candle_count": count, "first": first, "last": "2026-10-28T00:00:00+05:30", "candles": []}))
    assert instrument_hub.history_depth("NSE-NIFTY") == "45,907 15-minute + 1,694 daily candles (2020-01-01 to 2026-10-28)"
    assert instrument_hub.history_depth(None) is None


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

    # NIFTY reports only computed artifact values, or UNEVALUATED when the artifact is missing
    assert bt_nifty["evaluation_status"] in {"RESEARCH_WALK_FORWARD", "UNEVALUATED"}
    if bt_nifty["evaluation_status"] == "RESEARCH_WALK_FORWARD":
        assert bt_nifty["performance_after_costs"]["statutory_friction_bps"] == 2.0
        assert "full_period_max_drawdown" not in bt_nifty["performance_after_costs"]
        assert bt_nifty["caveats"]
        assert not any("Zero overnight gap" in a for a in bt_nifty["execution_assumptions"])
    else:
        assert "performance_after_costs" not in bt_nifty

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

    for inst in ("NIFTY", "SENSEX"):
        h = items[inst]
        if h["stored_candles"] > 0:
            assert h["health_status"] == ("HEALTHY" if h["last_price"] is not None else "NO_LIVE_QUOTE")
            assert "saved Groww 15-minute candles" in h["gap_disclosure"]
        else:
            assert h["health_status"] == "DATA_GAP"
    assert items["CRUDEOILMINI"]["health_status"] == "DATA_FEED_GAP"

    invariants = health["safety_invariants"]
    assert invariants["live_trading_enabled"] is False
    assert invariants["order_placement_allowed"] is False
    assert invariants["capital_commitment_allowed"] is False
    assert invariants["synthetic_orders_only"] is True
    assert invariants["real_money_loss_risk"] is False


def test_data_health_counts_the_saved_groww_history(tmp_path, monkeypatch):
    from app.forecasting import instrument_hub
    from app.market import history_loader as hl

    monkeypatch.setattr(hl, "HISTORY_DIR", tmp_path)
    monkeypatch.setattr(instrument_hub, "_depth_cache", {})
    monkeypatch.setattr(instrument_hub, "load_read", lambda: {"quotes": [{"instrument": "NIFTY", "last_price": 22700.0}]})
    hl.series_path("NSE-NIFTY", "15minute", tmp_path).write_text(json.dumps(
        {"candle_count": 45907, "first": "2020-01-01T09:15:00+05:30", "last": "2026-10-28T13:00:00+05:30", "candles": []}))
    items = {i["instrument"]: i for i in instrument_hub.get_instrument_data_health()["primary_instruments"]}
    assert items["NIFTY"]["stored_candles"] == 45907 and items["NIFTY"]["health_status"] == "HEALTHY"
    assert items["NIFTY"]["gap_disclosure"] == "45,907 saved Groww 15-minute candles, 2020-01-01 to 2026-10-28."
    assert items["SENSEX"]["stored_candles"] == 0 and items["SENSEX"]["health_status"] == "DATA_GAP"


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
    """MCX crude has no Groww history; the old derived_crude file is not MCX data, so no training."""
    from tests.conftest import login
    login(client)

    res = client.post(
        "/api/forecasting/train-benchmark",
        json={"instrument": "CRUDEOILMINI", "model_type": "lightgbm", "strategy_mode": "deadband"},
    )
    assert res.status_code == 400
    assert res.json()["code"] == "DATASET_NOT_FOUND"



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


def test_train_benchmark_sota_models(client: TestClient):
    from tests.conftest import login
    login(client)

    # Test XGBoost on NIFTY
    res_xgb = client.post(
        "/api/forecasting/train-benchmark",
        json={"instrument": "NIFTY", "model": "xgboost", "strategy_mode": "deadband"},
    )
    assert res_xgb.status_code == 200
    b_xgb = res_xgb.json()
    assert b_xgb["ok"] is True
    assert b_xgb["model_name"] == "xgboost"

    # Test CatBoost on SENSEX (MCX crude has no history to train on)
    res_cb = client.post(
        "/api/forecasting/train-benchmark",
        json={"instrument": "SENSEX", "model": "catboost", "strategy_mode": "regime_gated"},
    )
    assert res_cb.status_code == 200
    b_cb = res_cb.json()
    assert b_cb["ok"] is True
    assert b_cb["model_name"] == "catboost"

    # Test DLinear on NIFTY
    res_dl = client.post(
        "/api/forecasting/train-benchmark",
        json={"instrument": "NIFTY", "model": "dlinear", "strategy_mode": "deadband"},
    )
    assert res_dl.status_code == 200
    b_dl = res_dl.json()
    assert b_dl["ok"] is True
    assert b_dl["model_name"] == "dlinear"

    # Test Chronos Foundation Model on NIFTY
    res_chr = client.post(
        "/api/forecasting/train-benchmark",
        json={"instrument": "NIFTY", "model": "chronos", "strategy_mode": "regime_gated"},
    )
    assert res_chr.status_code == 200
    b_chr = res_chr.json()
    assert b_chr["ok"] is True
    assert b_chr["model_name"] == "chronos"


def test_multi_benchmark_endpoint(client: TestClient):
    from tests.conftest import login
    # Unauthenticated should fail
    unauth = client.post("/api/forecasting/multi-benchmark", json={})
    assert unauth.status_code in {401, 403}

    login(client)
    res = client.post(
        "/api/forecasting/multi-benchmark",
        json={
            "instruments": ["NIFTY", "CRUDEOILMINI"],
            "models": ["lightgbm", "xgboost"],
            "strategy_modes": ["deadband", "regime_gated"],
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert "leaderboard" in body
    assert len(body["leaderboard"]) > 0
    # First item must have rank 1
    assert body["leaderboard"][0]["rank"] == 1
    assert "champion" in body
    assert "top_by_instrument" in body
    assert "NIFTY" in body["top_by_instrument"]
    assert "CRUDEOILMINI" not in body["top_by_instrument"]  # no MCX history: never ranked

    # Test full 9-model multi-dataset benchmark execution
    res_full = client.post(
        "/api/forecasting/multi-benchmark",
        json={
            "instruments": ["NIFTY", "SENSEX"],
            "models": ["lightgbm", "xgboost", "catboost", "dlinear", "chronos", "random_forest", "mlp", "logistic_regression", "empirical_prior"],
            "strategy_modes": ["regime_gated", "deadband", "raw"],
        },
    )
    assert res_full.status_code == 200
    body_full = res_full.json()
    assert body_full["ok"] is True
    # 2 instruments * 3 modes * each model that could run (54 with every library installed).
    # A model whose library is missing is listed as unavailable, never filled with a stand-in.
    runnable = 9 - len(body_full["unavailable_models"])
    assert len(body_full["leaderboard"]) == 2 * 3 * runnable
    assert body_full["instruments_evaluated"] == ["NIFTY", "SENSEX"] or set(body_full["instruments_evaluated"]) == {"NIFTY", "SENSEX"}

    # Second call should be a cache hit and return immediately
    res_cached = client.post(
        "/api/forecasting/multi-benchmark",
        json={
            "instruments": ["NIFTY", "SENSEX"],
            "models": ["lightgbm", "xgboost", "catboost", "dlinear", "chronos", "random_forest", "mlp", "logistic_regression", "empirical_prior"],
            "strategy_modes": ["regime_gated", "deadband", "raw"],
        },
    )
    assert res_cached.status_code == 200
    assert res_cached.json()["total_combinations"] == 54


def test_live_trend_chart_endpoint(client: TestClient):
    from tests.conftest import login
    # Unauthenticated should fail
    unauth = client.get("/api/forecasting/live-trend-chart?instrument=NIFTY")
    assert unauth.status_code in {401, 403}

    login(client)
    res = client.get("/api/forecasting/live-trend-chart?instrument=NIFTY&bars=25")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["instrument"] == "NIFTY"
    assert "candles" in body
    assert len(body["candles"]) > 0
    assert "current_spot" in body
    assert "projected_path" in body
    assert "target_spot" in body
    assert "stop_loss_spot" in body
    if body["forecast_status"] == "ACTIVE" and body["target_spot"] is not None:
        assert len(body["projected_path"]) == 4
        assert "upper_bound" in body["projected_path"][0]
        assert "lower_bound" in body["projected_path"][0]
    else:
        # No live forecast: no invented direction, probability or projection
        assert body["projected_path"] == []
        assert body["predicted_direction"] == "UNKNOWN"
        assert body["calibrated_probability"] is None

    # Test explicit model selection on live trend chart
    res_model = client.get("/api/forecasting/live-trend-chart?instrument=NIFTY&bars=25&model=xgboost&strategy_mode=regime_gated")
    assert res_model.status_code == 200
    body_model = res_model.json()
    assert body_model["ok"] is True
    assert body_model["model_name"] == "xgboost"
    assert body_model["strategy_mode"] == "regime_gated"
    # Research models have no deployed live artifact, so no projection is fabricated for them
    assert body_model["forecast_status"] == "MODEL_NOT_DEPLOYED"
    assert body_model["projected_path"] == []
    assert body_model["calibrated_probability"] is None
    assert body_model["predicted_direction"] == "UNKNOWN"



