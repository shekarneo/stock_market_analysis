"""Tests validating the 16 October 2026 audit corrective milestone.

Covers:
Task 1: Removal of misleading forecast outputs, safe artifact loading, incomplete candle rejection.
Task 2: Removal of fabricated market prices and fallback elimination.
Task 3: Instrument identity standardization and MCX vs NSE session separation.
Task 4: Groww quarantined trusted-data path validation.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest

from app.forecasting.live_forecast import (
    compute_live_forecast_for_instrument,
    generate_all_live_forecasts,
    is_candle_complete,
    load_registered_model,
)
from app.forecasting.targets import MODEL_FEATURES
from app.instruments import canonical_underlying
from app.market.calendar import ExchangeCalendar, MCXExchangeCalendar, get_exchange_calendar
from app.market.groww_market_snapshot import (
    _fallback_commodities,
    _fallback_global_indices,
    _fallback_sectoral_indices,
    build_groww_market_observations,
    parse_global_indices,
    parse_mcx_commodities,
    parse_sectoral_indices,
)
from app.market.live_quotes import stored_observations
from app.market.timestamp_contract import map_provider_timestamp
from app.market.verified_history import (
    build_trusted_dataset,
    validate_quarantine_nifty_dataset,
)
from app.settings import REPO_ROOT

IST = ZoneInfo("Asia/Kolkata")


# ============================================================================
# TASK 1: FORECAST OUTPUTS & ARTIFACT INFERENCE
# ============================================================================

def test_missing_or_unregistered_model_returns_explicit_no_fitted_model():
    quote = {
        "last_price": 24500.0,
        "features": {f: 0.001 for f in MODEL_FEATURES},
        "partial_candle": False,
    }
    # Instrument without registered model
    res = compute_live_forecast_for_instrument("UNKNOWN_INST", quote)
    assert res["status"] == "NO_FITTED_MODEL"
    assert res["model_name"] is None
    assert res["model_version"] is None
    assert res["direction"] == "UNKNOWN"
    assert res["probability_up"] is None
    assert res["probability_down"] is None
    assert "No valid approved fitted model artifact" in res["summary"]


def test_incomplete_candle_is_rejected_for_inference():
    quote_partial = {
        "last_price": 24500.0,
        "partial_candle": True,
        "features": {f: 0.001 for f in MODEL_FEATURES},
    }
    res = compute_live_forecast_for_instrument("NIFTY", quote_partial)
    assert res["status"] == "INCOMPLETE_CANDLE"
    assert res["probability_up"] is None
    assert "not complete" in res["summary"]


def test_incomplete_candle_boundary_time_check():
    now_utc = datetime(2026, 10, 16, 9, 20, tzinfo=timezone.utc)
    bar_end_future = "2026-10-16T09:30:00+00:00"
    quote = {
        "last_price": 24500.0,
        "bar_end": bar_end_future,
        "features": {f: 0.001 for f in MODEL_FEATURES},
    }
    assert is_candle_complete(quote, current_time=now_utc) is False
    res = compute_live_forecast_for_instrument("NIFTY", quote, current_time=now_utc)
    assert res["status"] == "INCOMPLETE_CANDLE"

    # Candle that has finished
    now_after = datetime(2026, 10, 16, 9, 31, tzinfo=timezone.utc)
    assert is_candle_complete(quote, current_time=now_after) is True


def test_mismatched_features_returns_feature_mismatch():
    mock_model = {
        "name": "logistic_regression",
        "model_version": "logistic-l2-newton-1",
        "status": "TRAINED",
        "fitted_state": {
            "ok": True,
            "family": "logistic_regression",
            "feature_names": list(MODEL_FEATURES),
            "scaler": {"means": [0.0] * len(MODEL_FEATURES), "scales": [1.0] * len(MODEL_FEATURES), "zero_variance": []},
            "weights": [0.1] * len(MODEL_FEATURES),
            "intercept": 0.0,
        },
    }
    # Missing required features
    quote = {
        "last_price": 24500.0,
        "features": {"ret_1": 0.01},  # missing ret_3, atr_3, etc.
        "partial_candle": False,
    }
    res = compute_live_forecast_for_instrument("NIFTY", quote, model_artifact=mock_model)
    assert res["status"] == "FEATURE_MISMATCH"
    assert res["probability_up"] is None


def test_valid_artifact_produces_genuine_inference():
    mock_model = {
        "name": "logistic_regression",
        "model_version": "logistic-l2-newton-1",
        "status": "TRAINED",
        "fitted_state": {
            "ok": True,
            "family": "logistic_regression",
            "feature_names": list(MODEL_FEATURES),
            "scaler": {"means": [0.0] * len(MODEL_FEATURES), "scales": [1.0] * len(MODEL_FEATURES), "zero_variance": []},
            "weights": [1.0] * len(MODEL_FEATURES),
            "intercept": 0.0,
        },
    }
    quote = {
        "last_price": 24500.0,
        "features": {f: 0.05 for f in MODEL_FEATURES},
        "partial_candle": False,
    }
    res = compute_live_forecast_for_instrument("NIFTY", quote, model_artifact=mock_model)
    assert res["status"] == "ACTIVE"
    assert res["model_version"] == "logistic-l2-newton-1"
    assert res["direction"] == "BULLISH"
    assert res["probability_up"] is not None
    assert 0.0 < res["probability_up"] < 1.0
    assert round(res["probability_up"] + res["probability_down"], 4) == 1.0


def test_generate_all_live_forecasts_keeps_safety_flag_false():
    all_f = generate_all_live_forecasts()
    # Safety flag must always be False until real market data is verified
    assert all_f["forecast_ready"] is False
    assert "forecasts" in all_f


# ============================================================================
# TASK 2: REMOVAL OF FABRICATED MARKET PRICES
# ============================================================================

def test_fallback_functions_return_empty_lists():
    assert _fallback_commodities() == []
    assert _fallback_global_indices() == []
    assert _fallback_sectoral_indices() == []


def test_failed_scraping_never_produces_fabricated_prices():
    # Empty HTML or failed network should return empty list, not fake prices like 9210.0 or 55810.5
    comms = parse_mcx_commodities(html="")
    assert comms == []
    globs = parse_global_indices(html="")
    assert globs == []
    secs = parse_sectoral_indices(html="")
    assert secs == []

    # Corrupt HTML
    assert parse_mcx_commodities(html="<html><body>Internal Error 500</body></html>") == []
    assert parse_global_indices(html="<html><body>Service Unavailable</body></html>") == []
    assert parse_sectoral_indices(html="<html><body>Gateway Timeout</body></html>") == []


def test_stored_observations_does_not_inject_fake_commodities(tmp_path):
    empty_read = tmp_path / "empty.json"
    empty_read.write_text(json.dumps({"status": "READ", "quotes": [], "observations": []}))
    obs = stored_observations(empty_read)
    assert obs == []


def test_build_groww_market_observations_discards_invalid_prices():
    invalid_rows = [
        {"instrument": "CRUDEOILMINI", "name": "Crude", "last_price": None},
        {"instrument": "GOLDMINI", "name": "Gold", "last_price": 0.0},
        {"instrument": "SILVERMINI", "name": "Silver", "last_price": -100.0},
        {"instrument": "NATURALGASMINI", "name": "NatGas", "last_price": float("nan")},
    ]
    obs = build_groww_market_observations(invalid_rows, [], [])
    assert obs == []


# ============================================================================
# TASK 3: INSTRUMENT IDENTITY & MCX/NSE SESSION SEPARATION
# ============================================================================

def test_crudemini_and_crudeoilmini_canonicalization():
    assert canonical_underlying("CRUDEMINI") == "CRUDEOILMINI"
    assert canonical_underlying("crudeoilm") == "CRUDEOILMINI"
    assert canonical_underlying("MCX_CRUDE_MINI") == "CRUDEOILMINI"
    assert canonical_underlying("CRUDEOILMINI") == "CRUDEOILMINI"


def test_mcx_exchange_calendar_separation():
    nse_cal = get_exchange_calendar("NIFTY")
    assert isinstance(nse_cal, ExchangeCalendar)
    assert nse_cal.open_time.hour == 9 and nse_cal.open_time.minute == 15
    assert nse_cal.close_time.hour == 15 and nse_cal.close_time.minute == 30

    mcx_cal = get_exchange_calendar("CRUDEOILMINI")
    assert isinstance(mcx_cal, MCXExchangeCalendar)
    assert mcx_cal.open_time.hour == 9 and mcx_cal.open_time.minute == 0
    assert mcx_cal.close_time.hour == 23 and mcx_cal.close_time.minute == 30

    # Evening candle at 20:30 IST
    evening_time = datetime(2026, 10, 16, 20, 30, tzinfo=IST)
    assert mcx_cal.in_regular_window(evening_time) is True
    assert nse_cal.in_regular_window(evening_time) is False


def test_timestamp_contract_session_boundary_by_instrument():
    nse_mapped = map_provider_timestamp("2026-10-16 09:15:00", verified=True, instrument="NIFTY")
    assert nse_mapped["ok"] is True
    assert nse_mapped["session_boundary"] == "09:15:00_TO_15:30:00"

    mcx_mapped = map_provider_timestamp("2026-10-16 09:00:00", verified=True, instrument="CRUDEOILMINI")
    assert mcx_mapped["ok"] is True
    assert mcx_mapped["session_boundary"] == "09:00:00_TO_23:30:00"


# ============================================================================
# TASK 4: GROWW TRUSTED-DATA PATH & QUARANTINE VALIDATION
# ============================================================================

def test_validate_quarantined_13_oct_nifty_candles():
    quarantine_id = "0105c2cfde527068e24b576e089b4dabfccda734fd20167ae28419a3e2e98057"
    raw_path = REPO_ROOT / "var" / "history" / "quarantine" / f"{quarantine_id}.json"
    assert raw_path.is_file()

    # Verify raw file bytes stay intact and unmodified
    raw_bytes = raw_path.read_bytes()
    expected_hash = "40ec5199e8a5f1059ce941d04a1a60ef15af6973286354ca1d8ecb7224f79075"
    assert hashlib.sha256(raw_bytes).hexdigest() == expected_hash

    # Validate dataset creation path
    res = validate_quarantine_nifty_dataset(quarantine_id, verified=True)
    assert res["ok"] is True
    assert res["status"] == "QUARANTINED_SEMANTICS_CONFIRMED"
    assert res["total_candles_read"] == 26
    # 25 regular session candles (09:15 to 15:15)
    assert res["completed_regular_candles"] == 25
    # 1 post-session close boundary print (15:30)
    assert res["post_session_boundary_candles"] == 1
    assert res["first_candle_start"].endswith("09:15:00+05:30")
    assert res["last_regular_candle_start"].endswith("15:15:00+05:30")
    assert res["post_session_candle_start"].endswith("15:30:00+05:30")

    # Safety flags must never be marked True automatically
    assert res["real_market_data_verified"] is False
    assert res["forecast_ready"] is False
    assert res["paper_approved"] is False
    assert res["live_approved"] is False

    # Chart reference status
    assert res["chart_comparison"]["status"] == "AWAITING_CHART_REFERENCE"
    assert res["chart_comparison"]["verified"] is False

    # Deterministic features generated for 25 completed regular candles
    assert res["features_generated_count"] == 25
    features = res["dataset"]["features"]
    assert len(features) == 25
    assert features[0]["close"] == 22471.4
    assert "ret_1" in features[0]["features"]
    assert "sma_5" in features[0]["features"]


def test_build_trusted_dataset_defaults_to_blocked_assessment():
    # Calling without verified=True must fail closed and match baseline assessment
    res = build_trusted_dataset(verified=False)
    assert res["trusted_dataset_created"] is False
    assert res["real_market_data_verified"] is False
    assert res["status"] == "BLOCKED"
