"""Phase 6 regressions: scale-free model inputs, server-side EV, instrument-master expiries, charges."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.execution.simulation import CHARGE_SCHEDULES, calculate_indian_regulatory_charges
from app.features.definitions import FEATURE_SET_VERSION, FEATURE_SPECS
from app.forecasting.live_forecast import _compute_features_from_candle_dicts, load_registered_model
from app.forecasting.targets import MODEL_FEATURES
from app.integrations.groww import expiries_url, read_expiries
from app.market import groww_options, instrument_master
from app.market.instrument_master import (
    contract_spec_mismatches,
    expiries_from_api_payload,
    front_month_future_symbol,
    option_expiries_from_rows,
    parse_instruments_csv,
    save_listed_expiries,
)

IST = timezone(timedelta(hours=5, minutes=30))
PRICE_LEVEL_FEATURES = {"sma_3", "sma_5", "sma_3_minus_sma_5", "atr_3"}


# --- Scale-free model inputs ----------------------------------------------------

def test_model_inputs_are_scale_free():
    assert FEATURE_SET_VERSION == "ohlc-2"
    assert not PRICE_LEVEL_FEATURES & set(MODEL_FEATURES)
    assert set(MODEL_FEATURES) <= set(FEATURE_SPECS)


def _candles(scale: float) -> list[dict]:
    out, px, t = [], 100.0, datetime(2026, 10, 16, 9, 15, tzinfo=IST)
    for i in range(12):
        o = px
        px = px * (1 + 0.002 * math.sin(i))
        out.append({
            "bar_start": (t + timedelta(minutes=15 * i)).isoformat(),
            "bar_end": (t + timedelta(minutes=15 * (i + 1))).isoformat(),
            "open": o * scale, "high": max(o, px) * 1.001 * scale, "low": min(o, px) * 0.999 * scale,
            "close": px * scale, "volume": 1.0,
        })
    return out


def test_features_do_not_depend_on_price_level():
    low, _, _ = _compute_features_from_candle_dicts("NIFTY", _candles(250.0))
    high, _, _ = _compute_features_from_candle_dicts("NIFTY", _candles(820.0))
    assert low is not None and set(low) == set(MODEL_FEATURES)
    for name in MODEL_FEATURES:
        assert low[name] == pytest.approx(high[name], abs=1e-12)


def _registry_entry(names: list[str], tag: str = "v1") -> dict:
    n = len(names)
    return {
        "status": "TRAINED", "family": "logistic_regression", "model_version": tag,
        "fitted_state": {"ok": True, "family": "logistic_regression", "feature_names": names,
                         "scaler": {"means": [0.0] * n, "scales": [1.0] * n}, "weights": [0.0] * n, "intercept": 0.0},
    }


def test_models_fitted_on_old_inputs_are_refused(tmp_path):
    old_names = ["ret_1", "ret_3", "sma_3", "sma_5", "close_vs_sma_5", "sma_3_minus_sma_5",
                 "ret_std_5", "atr_3", "hl_range_vs_prev_close", "oc_return", "close_position"]
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"models": {"logistic_regression:NIFTY:M15": {"versions": {"v1": _registry_entry(old_names)}}}}),
                    encoding="utf-8")
    assert load_registered_model("NIFTY", registry_path=path) is None


def test_registry_versions_sort_numerically(tmp_path):
    names = list(MODEL_FEATURES)
    versions = {"v9": _registry_entry(names, "v9"), "v10": _registry_entry(names, "v10")}
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"models": {"logistic_regression:NIFTY:M15": {"versions": versions}}}), encoding="utf-8")
    assert load_registered_model("NIFTY", registry_path=path)["model_version"] == "v10"


# --- Instrument master and expiries ---------------------------------------------

CSV = (
    "exchange,exchange_token,trading_symbol,groww_symbol,name,instrument_type,segment,series,isin,underlying_symbol,"
    "underlying_exchange_token,expiry_date,strike_price,lot_size,tick_size,freeze_quantity,is_reserved,buy_allowed,sell_allowed\n"
    "BSE,1,S1,x,SENSEX,CE,FNO,,,SENSEX,1,2026-10-29,82000,20,0.05,,0,1,1\n"
    "BSE,2,S2,x,SENSEX,PE,FNO,,,SENSEX,1,2026-11-05,82000,20,0.05,,0,1,1\n"
    "MCX,3,CRUDEOILM18NOV26FUT,x,CRUDEOILM,FUT,COMMODITY,,,CRUDEOILM,1,2026-11-18,,10,1,,0,1,1\n"
    "MCX,4,CRUDEOILM17DEC26FUT,x,CRUDEOILM,FUT,COMMODITY,,,CRUDEOILM,1,2026-12-17,,10,1,,0,1,1\n"
    "MCX,5,CRUDEOILM17NOV265800CE,x,CRUDEOILM,CE,COMMODITY,,,CRUDEOILM,1,2026-11-17,5800,10,0.1,,0,1,1\n"
)


def test_expiries_and_front_month_from_master():
    rows = parse_instruments_csv(CSV)
    assert option_expiries_from_rows(rows, "SENSEX") == ["2026-10-29", "2026-11-05"]
    assert option_expiries_from_rows(rows, "CRUDEOILMINI") == ["2026-11-17"]
    assert front_month_future_symbol(rows, "CRUDEOILMINI", date(2026, 10, 23)) == "CRUDEOILM18NOV26FUT"
    assert front_month_future_symbol(rows, "CRUDEOILMINI", date(2026, 11, 19)) == "CRUDEOILM17DEC26FUT"
    assert contract_spec_mismatches(rows) == []  # SENSEX 20 and crude mini 10 match the instrument master


def test_refreshed_expiries_enable_sensex_validation(tmp_path, monkeypatch):
    path = tmp_path / "listed_expiries.json"
    save_listed_expiries({"SENSEX": ["2026-10-29", "2026-11-05"]}, source="test", path=path)
    monkeypatch.setattr(instrument_master, "LISTED_EXPIRIES_PATH", path)
    assert groww_options.resolve_upcoming_expiry("SENSEX", as_of=date(2026, 10, 30)) == "2026-11-05"
    assert groww_options.validate_contract_expiry("2026-10-29", as_of=date(2026, 10, 23), underlying="SENSEX") == (True, "VALID")


def test_expiries_api_shape_and_scope():
    assert "underlying_symbol=SENSEX" in expiries_url("BSE", "SENSEX", 2026)
    assert expiries_from_api_payload({"payload": {"expiries": ["2026-11-05", "2026-10-29"]}}) == ["2026-10-29", "2026-11-05"]
    with pytest.raises(ValueError):
        read_expiries(None, "token", exchange="MCX", underlying_symbol="CRUDEOILM")


# --- Charges ---------------------------------------------------------------------

def test_all_charge_schedules_are_verified():
    assert all(schedule["verified"] for schedule in CHARGE_SCHEDULES.values())
    futures = calculate_indian_regulatory_charges(side="SELL", price=Decimal("6000"), quantity=Decimal("10"),
                                                  exchange="MCX", instrument_type="FUTURE")
    assert Decimal(futures["stt"]) == Decimal("6.00")  # 0.01% CTT on Rs60,000 notional
    assert futures["transaction_tax_label"] == "CTT"


# --- Server-side expected net (Postgres fixture) ---------------------------------------

def test_client_expected_net_is_not_trusted_by_default(db):
    from app.config.store import current_config, ensure_seed, replace_section
    from app.db import get_session_factory
    from app.execution.simulation import run_paper_simulation
    from app.settings import get_settings
    from tests.test_experimental_paper_execution import _body

    session = get_session_factory()()
    try:
        settings = get_settings()
        ensure_seed(session, settings)
        risk = current_config(session).risk.model_dump()
        risk.update(risk_capital_inr=1000000.0, max_open_positions=3, max_risk_fraction_per_trade=0.02, daily_loss_fraction=0.03)
        replace_section(session, settings, "risk", risk, actor="t")
        session.commit()
        result = run_paper_simulation(session, _body("ev-default", expected_net="99999"), actor="t")
        assert result["code"] == "VETOED"
        assert "EXPECTED_NET_UNAVAILABLE" in result["reasons"]
    finally:
        session.rollback()
        session.close()
