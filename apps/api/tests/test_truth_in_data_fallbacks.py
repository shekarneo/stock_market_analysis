"""Truth-in-Data regression tests for forecasts, backtests, option picks and watchlist premiums.

Verifies that missing inputs surface as None / UNAVAILABLE / STALE instead of
placeholder numbers, and that the synthetic BANK NIFTY dataset is never served.
Offline; no provider is called.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.analysis.intelligence import _generate_option_picks, _market
from app.forecasting.instrument_hub import _nifty_backtest_from_artifact
from app.forecasting.live_forecast import MAX_FEATURE_AGE_MINUTES, _stale_feature_reason
from app.market.dataset_resolver import resolve_dataset_file
from app.market.groww_options import get_live_option_quote
from app.settings import REPO_ROOT

NOW = datetime(2026, 10, 16, 5, 0, tzinfo=timezone.utc)  # 10:30 IST


# --- Live forecast freshness -------------------------------------------------

def test_historical_dataset_features_are_stale():
    reason = _stale_feature_reason({"bar_end": NOW.isoformat()}, "HISTORICAL_CANDLE_DATASET", False, NOW)
    assert reason and "historical" in reason.lower()


def test_live_features_older_than_limit_are_stale():
    old_end = NOW - timedelta(minutes=MAX_FEATURE_AGE_MINUTES + 1)
    reason = _stale_feature_reason({"bar_end": old_end.isoformat()}, "LIVE_DB_MARKET_CANDLES", True, NOW)
    assert reason and "minutes ago" in reason


def test_recent_live_features_are_accepted():
    recent_end = NOW - timedelta(minutes=10)
    assert _stale_feature_reason({"bar_end": recent_end.isoformat()}, "LIVE_DB_MARKET_CANDLES", True, NOW) is None


def test_live_features_without_bar_end_are_stale():
    assert _stale_feature_reason({}, "LIVE_GROWW_15M_CANDLES", True, NOW)


def test_caller_supplied_features_are_not_rechecked():
    assert _stale_feature_reason({}, "LIVE_QUOTE_FEATURES", True, NOW) is None


def test_reused_quote_keeps_historical_feature_source():
    from app.forecasting.live_forecast import compute_live_forecast_for_instrument
    from app.forecasting.targets import MODEL_FEATURES

    quote = {
        "last_price": 25000.0,
        "features": {f: 0.01 for f in MODEL_FEATURES},
        "feature_source": "HISTORICAL_CANDLE_DATASET",
        "is_live_feature_vector": False,
        "bar_end": (NOW - timedelta(days=2)).isoformat(),
    }
    res = compute_live_forecast_for_instrument("NIFTY", quote, current_time=NOW)
    assert res["status"] == "STALE_FEATURES"
    assert res["probability_up"] is None


# --- Backtest report -----------------------------------------------------------

def test_backtest_without_artifact_is_unevaluated():
    missing = REPO_ROOT / "var" / "datasets" / "does_not_exist_m40.json"
    report = _nifty_backtest_from_artifact(missing)
    assert report["evaluation_status"] == "UNEVALUATED"
    assert "performance_after_costs" not in report


def test_backtest_serves_artifact_values_and_caveats(tmp_path):
    artifact = tmp_path / "m40.json"
    artifact.write_text(json.dumps({
        "created_at": "2026-10-16T00:00:00+00:00",
        "nifty_dataset_id": "nifty-ds",
        "num_folds": 19,
        "dev_fold_count": 14,
        "holdout_fold_count": 5,
        "nifty_summary": {"strategies": {
            "empirical_prior_regime_gated": {
                "model_name": "empirical_prior", "strategy_mode": "regime_gated",
                "dev_net_return_2bps": -1.77, "holdout_net_return_2bps": 3.93,
                "full_net_return_2bps": 2.16, "full_gross_return_0bps": 2.54,
                "full_max_drawdown_2bps": 1.1, "holdout_accuracy": 0.52,
                "holdout_brier_skill_score": 0.01, "dev_accuracy": 0.49,
                "holdout_turnover_units": 3.5, "full_turnover_units": 11.0,
            },
        }},
    }), encoding="utf-8")
    report = _nifty_backtest_from_artifact(artifact)
    assert report["evaluation_status"] == "RESEARCH_WALK_FORWARD"
    perf = report["performance_after_costs"]
    assert perf["holdout_net_return"] == 3.93
    assert perf["dev_net_return"] == -1.77
    assert perf["mean_fold_max_drawdown"] == 1.1
    assert report["statistical_metrics"]["holdout_accuracy"] == 0.52
    assert any("negative" in c for c in report["caveats"])
    assert all("status" not in row for row in report["baseline_comparisons"])


# --- Synthetic BANK NIFTY quarantine -----------------------------------------

@pytest.mark.parametrize("symbol", ["BANKNIFTY", "NSE-BANKNIFTY", "BANK NIFTY"])
def test_synthetic_banknifty_dataset_is_never_resolved(symbol):
    assert resolve_dataset_file(symbol) is None


# --- Live option quotes --------------------------------------------------------

def _chain(tmp_path, *, underlying="NIFTY", retrieved_at=NOW, expiry="2026-10-20"):
    path = tmp_path / "chain.json"
    path.write_text(json.dumps({
        "status": "SUCCESS",
        "underlying": underlying,
        "expiry_date": expiry,
        "retrieved_at": retrieved_at.isoformat(),
        "strikes": {"25000.0": {"CE": {"ltp": 112.5, "greeks": {"delta": 0.52}, "trading_symbol": "NIFTY25000CE"}}},
    }), encoding="utf-8")
    return path


def test_fresh_matching_option_quote_is_returned(tmp_path):
    q = get_live_option_quote("NIFTY 25000 CE", _chain(tmp_path), current_time=NOW + timedelta(minutes=2))
    assert q is not None and q["ltp"] == 112.5 and q["delta"] == 0.52


def test_option_quote_for_other_underlying_is_rejected(tmp_path):
    path = _chain(tmp_path, underlying="SENSEX")
    assert get_live_option_quote("NIFTY 25000 CE", path, current_time=NOW) is None


def test_stale_option_quote_is_rejected(tmp_path):
    path = _chain(tmp_path, retrieved_at=NOW - timedelta(hours=2))
    assert get_live_option_quote("NIFTY 25000 CE", path, current_time=NOW) is None


def test_expired_contract_quote_is_rejected(tmp_path):
    path = _chain(tmp_path, expiry="2026-10-13")
    assert get_live_option_quote("NIFTY 25000 CE", path, current_time=NOW) is None


# --- Option picks --------------------------------------------------------------

def test_picks_without_live_quote_have_no_premiums(monkeypatch):
    import app.market.groww_options as go

    monkeypatch.setattr(go, "get_live_option_quote", lambda *a, **k: None)
    picks = _generate_option_picks("NIFTY", 25012.0, "CE", 80.0, 40.0)
    assert len(picks) == 5
    for p in picks:
        assert p["quote_source"] == "UNAVAILABLE"
        assert p["is_live_quote"] is False
        assert p["entry_premium"] is None
        assert p["target_premium"] is None
        assert p["stop_loss_premium"] is None
        assert p["delta"] is None
        assert p["capital_per_lot"] is None


def test_market_without_vix_has_no_sized_levels(monkeypatch):
    import app.market.groww_options as go

    monkeypatch.setattr(go, "get_live_option_quote", lambda *a, **k: None)
    rows = [{
        "instrument": "NIFTY", "last_price": 25012.0, "directional_implication": "BULLISH",
        "category": "INDIAN_EQUITY", "ohlc": {"open": 24800.0, "close": 24750.0},
    }]
    rec = _market(rows, "NIFTY")["manual_trade_recommendation"]
    assert rec["target_spot"] is None
    assert rec["stop_loss_spot"] is None
    assert rec["expected_move_points"] is None
    assert all(p["entry_premium"] is None for p in rec["top_5_options"])
    assert "₹None" not in rec["execution_guide"]


# --- Watchlist premiums --------------------------------------------------------

def test_watchlist_drops_client_estimated_premiums(db):
    from app.db import get_session_factory
    from app.watchlist.service import create_suggestion

    session = get_session_factory()()
    try:
        row = create_suggestion(
            session, instrument="NIFTY", contract="NIFTY 25000 CE", option_type="CE", call="BUY",
            entry_spot=25000.0, target_points=80.0, stop_loss_points=40.0,
            model_premiums={"entry": 120, "target": 180, "stop_loss": 80, "delta": 0.5, "strike": 25000, "estimated": True},
            data_class="UNVERIFIED_PROVIDER_DATA", created_by="t", now=NOW,
        )
        prem = row.model_premiums
        assert "estimated" not in prem
        assert prem.get("data_source") in {"UNAVAILABLE", "GROWW_OPTION_CHAIN"}
        if prem.get("data_source") == "UNAVAILABLE":
            for key in ("entry", "target", "stop_loss", "delta"):
                assert key not in prem
        assert prem["strike"] == 25000
    finally:
        session.rollback()
        session.close()
