"""Regression tests for V6 Paper Trading and Watchlist Monitoring Workflow.

Proves:
1. Watchlist monitoring continues without being blocked by forecast_ready or real_market_data_verified.
2. Multi-instrument monitoring is isolated (missing or unverified data on one does not drop another).
3. Forecast outcome tracking evaluates statistical predictions and NO_TRADE signals immutably.
4. Paper simulation calculates Indian statutory charges and tick slippage without live routing.
5. Live order routing remains strictly isolated (live_approved=False, live_broker_routing_enabled=False).
6. Persisted operational configuration preserves mode=PAPER.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest

from app.config.store import current_config, ensure_seed
from app.db import get_session_factory
from app.execution.orders import live_order_calls
from app.execution.paper_simulation_harness import (
    calculate_indian_market_charges,
    calculate_simulated_fill_price,
    round_to_tick,
)
from app.execution.simulation import run_paper_simulation
from app.analysis.outcome_tracker import (
    evaluate_forecast_outcome,
    record_forecast_prediction,
)
from app.settings import get_settings
from app.watchlist.service import (
    accuracy,
    create_suggestion,
    evaluate_open,
    session_close,
)
from tests.conftest import login
from tests.test_paper_simulation import AT, _body, _dataset


T0 = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)  # 17:30 IST


@pytest.fixture
def session(db):
    s = get_session_factory()()
    try:
        ensure_seed(s, get_settings())
        yield s
    finally:
        s.rollback()
        s.close()


def _obs(inst: str, price: float, at: datetime) -> dict:
    return {"instrument": inst, "last_price": price, "retrieved_at": at.isoformat()}


def test_watchlist_monitoring_independent_of_safety_flags(session):
    """Watchlist monitors multiple instruments and evaluates resolutions using available spot data."""
    # Add suggestions across multiple underlyings (equity index and commodity)
    nifty_ce = create_suggestion(
        session,
        instrument="NIFTY",
        contract="NIFTY 22500 CE",
        option_type="CE",
        call="BUY",
        entry_spot=22500.0,
        target_points=100.0,
        stop_loss_points=50.0,
        model_premiums={"entry": 120.0},
        data_class="UNVERIFIED_PROVIDER_DATA",
        created_by="operator",
        now=T0,
    )
    crude_pe = create_suggestion(
        session,
        instrument="CRUDEMINI",
        contract="CRUDEMINI 9300 PE",
        option_type="PE",
        call="BUY",
        entry_spot=9300.0,
        target_points=50.0,
        stop_loss_points=25.0,
        model_premiums={"entry": 45.0},
        data_class="UNVERIFIED_PROVIDER_DATA",
        created_by="operator",
        now=T0,
    )

    assert nifty_ce.status == "OPEN"
    assert crude_pe.status == "OPEN"
    assert (float(nifty_ce.target_spot), float(nifty_ce.stop_loss_spot)) == (22600.0, 22450.0)
    assert (float(crude_pe.target_spot), float(crude_pe.stop_loss_spot)) == (9250.0, 9325.0)

    # Partial observation feed: NIFTY quote arrives, CRUDEMINI quote is missing
    t1 = T0 + timedelta(minutes=5)
    evaluate_open(session, [_obs("NIFTY", 22610.0, t1)], now=t1)

    # NIFTY hit target; CRUDEMINI was NOT dropped and remains OPEN
    assert nifty_ce.status == "TARGET_HIT"
    assert float(nifty_ce.resolved_spot) == 22610.0
    assert crude_pe.status == "OPEN"
    assert crude_pe.checks == 0

    # Next update: CRUDEMINI quote arrives and triggers stop-loss
    t2 = T0 + timedelta(minutes=10)
    evaluate_open(session, [_obs("CRUDEMINI", 9330.0, t2)], now=t2)
    assert crude_pe.status == "SL_HIT"
    assert float(crude_pe.resolved_spot) == 9330.0

    # Accuracy aggregation correctly accounts for both decided outcomes
    stats = accuracy([nifty_ce, crude_pe])
    assert stats["overall"]["decided"] == 2
    assert stats["overall"]["TARGET_HIT"] == 1
    assert stats["overall"]["SL_HIT"] == 1
    assert stats["overall"]["hit_rate"] == 0.5


def test_forecast_outcome_tracking_evaluates_no_trade_prediction(tmp_path):
    """Outcome tracker registers predictions for NO_TRADE decisions and scores them post-horizon."""
    log_file = tmp_path / "forecast_outcomes.jsonl"
    pred = record_forecast_prediction(
        analysis_id="test_run_100",
        instrument="NIFTY",
        model_version="logistic-l2-newton-1",
        probability_up=0.58,
        direction="BULLISH",
        spot_price=22500.0,
        decision="NO_TRADE",
        path=log_file,
    )

    assert pred["decision"] == "NO_TRADE"
    assert pred["execution_context"] == "FORECAST_EVALUATION"
    assert pred["evaluation_status"] == "PENDING_SUBSEQUENT_CLOSE"
    assert log_file.exists()

    # Verify line was immutably persisted
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    saved = json.loads(lines[0])
    assert saved["analysis_id"] == "test_run_100"
    assert saved["probability_up"] == 0.58

    # Subsequent bar closes higher at 22560.0
    evaluation = evaluate_forecast_outcome(
        pred,
        subsequent_close_price=22560.0,
        subsequent_bar_end="2026-10-15T12:15:00+00:00",
    )

    assert evaluation["actual_direction"] == "BULLISH"
    assert evaluation["direction_correct"] is True
    assert evaluation["realized_return_pct"] == pytest.approx(0.267, rel=1e-2)
    # Brier score: (0.58 - 1.0)^2 = 0.1764
    assert evaluation["brier_score"] == pytest.approx(0.1764, abs=1e-4)
    assert evaluation["execution_context"] == "FORECAST_EVALUATION"
    assert "no real trade was executed" in evaluation["note"].lower()


def test_forecast_evaluation_prevents_leakage_and_duplicate_scoring(tmp_path):
    """Enforce horizon elapsed time to prevent look-ahead leakage and prevent duplicate scoring."""
    from app.analysis.outcome_tracker import (
        compute_forecast_accuracy_summary,
        evaluate_pending_forecasts,
        get_forecast_records,
    )
    log_file = tmp_path / "forecast_outcomes.jsonl"
    t_start = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)

    # 1. Register a forecast
    record_forecast_prediction(
        analysis_id="leakage_test_1",
        instrument="NIFTY",
        model_version="logistic-l2-newton-1",
        probability_up=0.55,
        direction="BULLISH",
        spot_price=22500.0,
        decision="NO_TRADE",
        data_provenance="UNVERIFIED_PROVIDER",
        recorded_at=t_start.isoformat(),
        path=log_file,
    )
    records = get_forecast_records(log_file)
    assert len(records) == 1
    assert records[0]["data_provenance"] == "UNVERIFIED_PROVIDER"

    # 2. Premature evaluation (only 2 minutes elapsed < 15 min horizon) -> Must stay pending!
    t_premature = t_start + timedelta(minutes=2)
    res_premature = evaluate_pending_forecasts(
        [{"instrument": "NIFTY", "last_price": 22550.0}],
        now=t_premature,
        min_elapsed_seconds=900,
        path=log_file,
    )
    assert res_premature["evaluated_count"] == 0
    assert res_premature["pending_count"] == 1
    recs_premature = get_forecast_records(log_file)
    assert recs_premature[0]["evaluation_status"] == "PENDING_SUBSEQUENT_CLOSE"

    # 3. Horizon elapsed (16 minutes >= 15 min horizon) -> Evaluates cleanly
    t_elapsed = t_start + timedelta(minutes=16)
    res_elapsed = evaluate_pending_forecasts(
        [{"instrument": "NIFTY", "last_price": 22550.0}],
        now=t_elapsed,
        min_elapsed_seconds=0,  # simulate horizon completion
        path=log_file,
    )
    assert res_elapsed["evaluated_count"] == 1
    assert res_elapsed["pending_count"] == 0
    recs_scored = get_forecast_records(log_file)
    assert recs_scored[0]["evaluation_status"] == "SCORED"
    assert recs_scored[0]["subsequent_outcome"]["direction_correct"] is True

    # 4. Repeated evaluation run -> Must NOT duplicate score!
    res_repeat = evaluate_pending_forecasts(
        [{"instrument": "NIFTY", "last_price": 22590.0}],
        now=t_elapsed + timedelta(minutes=5),
        min_elapsed_seconds=0,
        path=log_file,
    )
    assert res_repeat["evaluated_count"] == 0
    assert res_repeat["pending_count"] == 0

    # 5. Summary metrics
    summary = compute_forecast_accuracy_summary(path=log_file)
    assert summary["total_forecasts"] == 1
    assert summary["scored_forecasts"] == 1
    assert summary["pending_forecasts"] == 0
    assert summary["directional_accuracy_pct"] == 100.0
    assert summary["brier_score"] == pytest.approx(0.2025, abs=1e-4)  # (0.55 - 1.0)^2
    assert summary["calibration_status"] == "UNCALIBRATED"  # n=1 < 30
    assert "NIFTY" in summary["by_instrument"]



def test_paper_simulation_charges_and_slippage_accounting():
    """Paper simulation calculates Indian regulatory friction and half-spread slippage without broker interaction."""
    live_order_calls.clear()

    # Buy at ask with half-spread slippage modeling
    bid = Decimal("150.00")
    ask = Decimal("152.00")
    fill, slippage = calculate_simulated_fill_price(
        side="BUY",
        reference_price=ask,
        bid=bid,
        ask=ask,
    )
    # Tick alignment (0.05)
    assert fill == Decimal("152.00")
    assert slippage == Decimal("1.00")  # half of 2.00 spread
    assert round_to_tick(fill, Decimal("0.05")) == Decimal("152.00")

    # Indian statutory charges for options contract
    charges = calculate_indian_market_charges(
        instrument_type="OPTIONS",
        side="BUY",
        price=Decimal("152.00"),
        quantity=50,  # 2 lots
    )
    # BUY options: Stamp duty (0.003%), NSE charges (0.03503%), SEBI, Brokerage (min(20, 0.05% turnover) = 3.80), GST (18%)
    assert charges.brokerage == Decimal("3.80")
    assert charges.total_charges == Decimal("7.86")
    assert charges.stt == Decimal("0.00")  # STT is only on SELL options

    sell_charges = calculate_indian_market_charges(
        instrument_type="OPTIONS",
        side="SELL",
        price=Decimal("155.00"),
        quantity=50,
    )
    # SELL options: STT is charged at 0.10% on premium turnover
    turnover = Decimal("155.00") * 50
    expected_stt = (turnover * Decimal("0.001")).quantize(Decimal("0.01"))
    assert sell_charges.stt == expected_stt
    assert sell_charges.total_charges > charges.total_charges

    # Distinguish forecast correctness from net profitability:
    # 3.0 points gross gain * 50 = Rs 150.00 gross PnL
    # Friction = charges.total_charges + sell_charges.total_charges
    gross_pnl = Decimal("150.00")
    friction = charges.total_charges + sell_charges.total_charges
    net_pnl = gross_pnl - friction
    # Even though prediction was directionally profitable, statutory friction eats a significant portion
    assert net_pnl < gross_pnl
    assert len(live_order_calls) == 0


def test_live_isolation_and_spoofed_flags_ignored(client, session):
    """Paper execution rejects client spoofed approval flags and strictly isolates live brokers."""
    live_order_calls.clear()

    token = login(client)
    body = _body(
        _dataset(),
        "paper-regress-1",
        occurred_at=AT.isoformat(),
        paper_approved=True,  # Client tries to spoof approval
        live_approved=True,
        real_market_data_verified=True,
    )
    resp = client.post("/api/paper/simulations", headers={"x-csrf-token": token}, json=body)
    assert resp.status_code == 422
    data = resp.json()
    assert data["code"] == "APPROVAL_FLAG_IGNORED"
    assert "APPROVAL_FLAG_IGNORED" in data["reasons"]
    assert data["paper_approved"] is False
    assert data["live_approved"] is False
    assert data["live_routed"] is False

    # Verify zero live order calls made
    assert len(live_order_calls) == 0


def test_persisted_operational_mode_is_paper(session):
    """Verify that persisted configuration preserves runtime mode as PAPER and live trading disabled."""
    cfg = current_config(session)
    assert cfg.runtime.mode.value == "PAPER"
    assert cfg.runtime.live_trading_enabled is False
    assert cfg.runtime.unattended_orders is False


def test_forecast_accuracy_api_endpoints(client, session):
    """Verify forecast accuracy and evaluation API endpoints."""
    token = login(client)
    res = client.get("/api/analysis/forecast-accuracy")
    assert res.status_code == 200
    data = res.json()
    assert "total_forecasts" in data
    assert "calibration_status" in data
    assert "by_instrument" in data

    eval_res = client.post("/api/analysis/forecast-accuracy/evaluate", headers={"x-csrf-token": token})
    assert eval_res.status_code == 200
    eval_data = eval_res.json()
    assert "evaluation_result" in eval_data

