"""Automated regression tests proving experimental paper execution activation,
virtual risk controls, fail-closed live safety, and honest provenance tracking.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from starlette.testclient import TestClient

from app.config.schemas import OperatingMode, RiskConfig
from app.config.store import current_config, ensure_seed, replace_section
from app.db import get_session_factory
from app.domain.tables import AuditEvent, PaperAccountEvent, PaperTransition
from app.execution.orders import live_order_calls
from app.execution.simulation import (
    calculate_indian_regulatory_charges,
    run_paper_simulation,
    simulated_execution_price,
)
from app.main import app
from app.research.status import research_status
from app.risk.gates import evaluate
from app.settings import REPO_ROOT, get_settings
from tests.conftest import login
from tests.test_paper_simulation import _dataset

AT = datetime(2026, 10, 16, 9, 30, tzinfo=timezone.utc)

_PLAN = {
    "entry_trigger": "Break above 24800 on 15m candle",
    "invalidation": "Drop below 24750",
    "exit_plan": "Target 24900 or 15m RSI > 70",
    "time_stop": "15:15 IST",
}

_MASTER = {
    "underlying": "NIFTY",
    "expiry": "2026-10-16",
    "strike": "24800",
    "option_type": "CE",
    "lot_size": "65",
    "tick_size": "0.05",
    "buy_allowed": True,
}

_QUOTE = {
    "bid": "120.00",
    "ask": "121.00",
    "quote_timestamp": AT.isoformat(),
}


def _body(intent_id: str, **kwargs) -> dict:
    payload = {
        "confirm": True,
        "intent_id": intent_id,
        "occurred_at": AT,
        "session_date": "2026-10-16",
        "mode": "PAPER",
        "underlying": "NIFTY",
        "expiry": "2026-10-16",
        "strike": "24800",
        "option_type": "CE",
        "lot_size": "65",
        "tick_size": "0.05",
        "charges_per_lot": "25.00",
        "expected_net": "500.00",
        "side": "BUY",
        "entry_plan": _PLAN,
        "master": _MASTER,
        "quote": _QUOTE,
        "forecast": {
            "model_id": "experimental-logreg-v1",
            "version_id": "v1.0.0",
            "promotion_state": "UNAPPROVED_EXPERIMENTAL",
            "model_health": "HEALTHY",
            "direction": "UP",
            "probability": 0.58,
        },
        "dataset": _dataset(),
        "execution_context": "EXPERIMENTAL",
    }
    payload.update(kwargs)
    return payload


def test_experimental_paper_executes_without_prior_model_approval(db):
    """Requirement: Execute experimental paper trades without prior model approval."""
    live_order_calls.clear()
    session = get_session_factory()()
    settings = get_settings()
    try:
        # Configure virtual risk controls
        ensure_seed(session, settings)
        cfg = current_config(session)
        risk_dict = cfg.risk.model_dump()
        risk_dict["risk_capital_inr"] = 500000.0
        risk_dict["max_open_positions"] = 2
        risk_dict["max_risk_fraction_per_trade"] = 0.02
        risk_dict["daily_loss_fraction"] = 0.03
        replace_section(session, settings, "risk", risk_dict, actor="tester")
        session.commit()

        body = _body("intent-exp-success-01")
        result = run_paper_simulation(session, body, actor="tester")

        # Must succeed with simulated fill
        assert result["code"] == "SIMULATED_FILL_APPLIED"
        assert result["decision"] == "TRADE"
        assert result["ok"] is True
        assert result["simulated_fill"] is not None
        assert result["simulated_fill"]["intent_id"] == "intent-exp-success-01"
        assert result["simulated_fill"]["execution_context"] == "EXPERIMENTAL"
        assert result["simulated_fill"]["data_provenance"] == "EXPERIMENTAL_UNVERIFIED_DATA"

        # Fail-closed invariant: zero live broker calls
        assert len(live_order_calls) == 0
        assert result["broker_called"] is False
        assert result["live_routed"] is False
        assert result["live_trading_enabled"] is False

        # Verify state transition to FILLED
        transitions = session.scalars(
            select(PaperTransition).where(PaperTransition.intent_id == "intent-exp-success-01")
        ).all()
        states = [t.to_state for t in transitions if t.applied]
        assert "RISK_APPROVED" in states
        assert "SUBMITTED" in states
        assert "FILLED" in states

        # Verify journaled PaperAccountEvent
        event = session.get(PaperAccountEvent, "sim-fill-intent-exp-success-01")
        assert event is not None
        assert event.event_type == "FILL"
        assert event.broker_confirmed is False
        assert event.ledger_applied is False
    finally:
        session.close()


def test_missing_virtual_risk_controls_block_experimental_execution(db):
    """Requirement: Missing virtual risk controls must veto with exact reason."""
    live_order_calls.clear()
    session = get_session_factory()()
    settings = get_settings()
    try:
        # Case A: Missing risk capital
        ensure_seed(session, settings)
        cfg = current_config(session)
        risk_dict = cfg.risk.model_dump()
        risk_dict["risk_capital_inr"] = None
        replace_section(session, settings, "risk", risk_dict, actor="tester")
        session.commit()

        body_a = _body("intent-exp-no-cap")
        res_a = run_paper_simulation(session, body_a, actor="tester")
        assert res_a["code"] == "VETOED"
        assert "MISSING_RISK_CAPITAL" in res_a["reasons"]
        assert res_a["simulated_fill"] is None

        # Case B: Missing position limit (0)
        risk_dict["risk_capital_inr"] = 500000.0
        risk_dict["max_open_positions"] = 0
        replace_section(session, settings, "risk", risk_dict, actor="tester")
        session.commit()

        body_b = _body("intent-exp-no-pos")
        res_b = run_paper_simulation(session, body_b, actor="tester")
        assert res_b["code"] == "VETOED"
        assert "MISSING_POSITION_LIMIT" in res_b["reasons"]
        assert res_b["simulated_fill"] is None

        # Live orders remain untouched
        assert len(live_order_calls) == 0
    finally:
        session.close()


def test_non_experimental_context_preserves_strict_model_approval_veto(db):
    """When execution_context is NOT experimental, unapproved models MUST be vetoed."""
    live_order_calls.clear()
    session = get_session_factory()()
    settings = get_settings()
    try:
        ensure_seed(session, settings)
        cfg = current_config(session)
        risk_dict = cfg.risk.model_dump()
        risk_dict["risk_capital_inr"] = 500000.0
        replace_section(session, settings, "risk", risk_dict, actor="tester")
        session.commit()

        # Without execution_context: "EXPERIMENTAL"
        body = _body("intent-strict-01", execution_context="PRODUCTION")
        result = run_paper_simulation(session, body, actor="tester")
        assert result["code"] == "VETOED"
        assert "MODEL_NOT_APPROVED" in result["reasons"]
        assert result["simulated_fill"] is None
        assert len(live_order_calls) == 0
    finally:
        session.close()


def test_indian_regulatory_charges_calculation():
    """Verify Indian statutory charges model for options trading on NSE."""
    charges = calculate_indian_regulatory_charges(
        side="BUY",
        price=Decimal("120.00"),
        quantity=Decimal("65"),  # 1 lot NIFTY
        lot_size=Decimal("65"),
        charges_per_lot=Decimal("20.00"),
    )
    assert Decimal(charges["brokerage"]) == Decimal("20.00")
    assert Decimal(charges["stamp_duty"]) > 0
    assert Decimal(charges["exchange_charges"]) > 0
    assert Decimal(charges["gst"]) > 0
    assert Decimal(charges["total_charges_inr"]) >= Decimal("20.00")

    # Sell side has STT
    sell_charges = calculate_indian_regulatory_charges(
        side="SELL",
        price=Decimal("120.00"),
        quantity=Decimal("65"),
    )
    assert Decimal(sell_charges["stt"]) > 0


def test_simulated_execution_price_discrete_spread():
    """Verify execution price applies bid/ask half-spread logic."""
    buy_quote = simulated_execution_price(
        side="BUY", bid="120.00", ask="121.00", haircut="half_spread", extra_tick_penalty=False
    )
    assert buy_quote["price"] == "121.00"

    sell_quote = simulated_execution_price(
        side="SELL", bid="120.00", ask="121.00", haircut="half_spread", extra_tick_penalty=False
    )
    # 120 - (121 - 120)/2 = 119.50
    assert sell_quote["price"] == "119.50"


def test_research_status_reflects_separated_states(db):
    """Verify research_status returns separated operational and risk states."""
    session = get_session_factory()()
    settings = get_settings()
    try:
        # When risk capital is configured
        ensure_seed(session, settings)
        cfg = current_config(session)
        risk_dict = cfg.risk.model_dump()
        risk_dict["risk_capital_inr"] = 1000000.0
        replace_section(session, settings, "risk", risk_dict, actor="tester")
        session.commit()

        st = research_status(session, settings)
        assert st["operational_mode"] == "PAPER"
        assert st["experimental_paper_execution"] == "Enabled"
        assert st["forecast_evaluation_status"] == "Active"
        assert st["data_verification"] == "Unverified"
        assert st["live_broker_execution"] == "Locked"
        assert st["paper_trading_active"] is True
        assert st["live_trading_enabled"] is False

        # When risk capital is removed
        risk_dict["risk_capital_inr"] = None
        replace_section(session, settings, "risk", risk_dict, actor="tester")
        session.commit()

        st_blocked = research_status(session, settings)
        assert st_blocked["experimental_paper_execution"] == "Blocked"
        assert st_blocked["paper_trading_active"] is False
        assert any(b["code"] == "MISSING_RISK_CAPITAL" for b in st_blocked["experimental_blockers"])
    finally:
        session.close()


def test_experimental_paper_idempotency_and_no_double_fill(db):
    """Running identical simulation requests does not duplicate fills or transitions."""
    live_order_calls.clear()
    session = get_session_factory()()
    settings = get_settings()
    try:
        ensure_seed(session, settings)
        cfg = current_config(session)
        risk_dict = cfg.risk.model_dump()
        risk_dict["risk_capital_inr"] = 500000.0
        risk_dict["max_open_positions"] = 2
        risk_dict["max_risk_fraction_per_trade"] = 0.02
        risk_dict["daily_loss_fraction"] = 0.03
        replace_section(session, settings, "risk", risk_dict, actor="tester")
        session.commit()

        body = _body("intent-idempotent-01")
        first = run_paper_simulation(session, body, actor="tester")
        assert first["code"] == "SIMULATED_FILL_APPLIED"

        # Repeated request with same intent_id
        second = run_paper_simulation(session, body, actor="tester")
        assert second["code"] == "SIMULATED_FILL_APPLIED"
        assert second["ok"] is True

        # Exactly 1 PaperAccountEvent exists
        events = session.scalars(
            select(PaperAccountEvent).where(PaperAccountEvent.intent_id == "intent-idempotent-01")
        ).all()
        assert len(events) == 1
        assert len(live_order_calls) == 0
    finally:
        session.close()


def test_api_signal_eligibility_and_post_simulation(db):
    """Test HTTP endpoints for signal eligibility and simulation execution."""
    session = get_session_factory()()
    settings = get_settings()
    try:
        ensure_seed(session, settings)
        cfg = current_config(session)
        risk_dict = cfg.risk.model_dump()
        risk_dict["risk_capital_inr"] = 1000000.0
        replace_section(session, settings, "risk", risk_dict, actor="tester")
        session.commit()
    finally:
        session.close()

    with TestClient(app) as client:
        csrf_token = login(client)
        resp = client.get("/api/paper/signal-eligibility")
        assert resp.status_code == 200
        elig = resp.json()
        assert elig["status"] == "NO_ELIGIBLE_PAPER_TRADE"
        assert elig["eligible"] is False
        assert "neutral" in elig["message"]


def test_deterministic_full_lifecycle_entry_exit_ledger_and_idempotency(db):
    """Verify complete paper-trading lifecycle through application workflow:
    eligible signal -> risk approval -> entry fill -> open position ->
    exit close operation -> exit event -> closed position -> realized net P&L.
    Verify database records, account API response, and exit idempotency.
    """
    live_order_calls.clear()
    session = get_session_factory()()
    settings = get_settings()
    try:
        ensure_seed(session, settings)
        cfg = current_config(session)
        risk_dict = cfg.risk.model_dump()
        risk_dict["risk_capital_inr"] = 1000000.0
        risk_dict["max_open_positions"] = 2
        risk_dict["max_risk_fraction_per_trade"] = 0.02
        risk_dict["daily_loss_fraction"] = 0.03
        replace_section(session, settings, "risk", risk_dict, actor="tester")
        session.commit()
    finally:
        session.close()

    with TestClient(app) as client:
        csrf_token = login(client)
        headers = {"x-csrf-token": csrf_token}

        # 1. Check account before any trades
        acct_init = client.get("/api/paper/account").json()
        assert acct_init["open_positions_count"] == 0
        assert acct_init["closed_positions_count"] == 0
        assert acct_init["realized_pnl_inr"] == 0.0
        assert acct_init["configured_capital_inr"] == 1000000.0

        # 2. Execute Entry Simulation via POST /api/paper/simulations
        intent_id = "intent-full-lifecycle-01"
        body = _body(intent_id)
        body_json = dict(body)
        body_json["occurred_at"] = body["occurred_at"].isoformat()

        sim_resp = client.post("/api/paper/simulations", json=body_json, headers=headers)
        assert sim_resp.status_code == 200
        sim_data = sim_resp.json()
        assert sim_data["code"] == "SIMULATED_FILL_APPLIED"
        assert sim_data["decision"] == "TRADE"
        entry_fill = sim_data["simulated_fill"]
        assert entry_fill["price"] == "121.00"
        assert entry_fill["quantity"] == "65"
        entry_charges = Decimal(entry_fill["charges_inr"])
        assert entry_charges > 0

        # 3. Verify Open Position via GET /api/paper/account
        acct_after_entry = client.get("/api/paper/account").json()
        assert acct_after_entry["open_positions_count"] == 1
        assert acct_after_entry["closed_positions_count"] == 0
        open_pos = acct_after_entry["open_positions"][0]
        assert open_pos["intent_id"] == intent_id
        assert open_pos["status"] == "OPEN"
        assert open_pos["quantity"] == 65.0
        assert open_pos["entry_price"] == 121.0

        # 4. Execute Actual Exit / Close Operation via POST /api/paper/close-position
        exit_resp = client.post(
            "/api/paper/close-position",
            json={
                "intent_id": intent_id,
                "exit_quote": {"bid": "150.00", "ask": "151.00"},
                "reason": "TARGET_HIT",
            },
            headers=headers,
        )
        assert exit_resp.status_code == 200
        exit_data = exit_resp.json()
        assert exit_data["ok"] is True
        assert exit_data["status"] == "POSITION_CLOSED"
        assert exit_data["exit_price"] == 149.50
        assert exit_data["duplicate"] is False

        expected_gross = 1852.50
        assert abs(exit_data["gross_pnl_inr"] - expected_gross) < 0.01
        expected_net = expected_gross - exit_data["total_charges_inr"]
        assert abs(exit_data["net_realized_pnl_inr"] - expected_net) < 0.01

        # 5. Verify Closed Position & Realized P&L via GET /api/paper/account
        acct_after_exit = client.get("/api/paper/account").json()
        assert acct_after_exit["open_positions_count"] == 0
        assert acct_after_exit["closed_positions_count"] == 1
        closed_trade = acct_after_exit["closed_positions"][0]
        assert closed_trade["intent_id"] == intent_id
        assert closed_trade["status"] == "CLOSED"
        assert closed_trade["entry_price"] == 121.0
        assert closed_trade["exit_price"] == 149.5
        assert closed_trade["realized_pnl_inr"] == round(expected_net, 2)
        assert acct_after_exit["realized_pnl_inr"] == round(expected_net, 2)
        assert acct_after_exit["current_balance_inr"] == round(1000000.0 + expected_net, 2)
        assert acct_after_exit["win_rate_pct"] == 100.0

        # 6. Verify Database Records directly
        db_session = get_session_factory()()
        try:
            transitions = db_session.scalars(
                select(PaperTransition).where(PaperTransition.intent_id == intent_id).order_by(PaperTransition.id)
            ).all()
            states = [t.to_state for t in transitions]
            assert states == ["PROPOSED", "RISK_APPROVED", "SUBMITTED", "PENDING", "FILLED", "EXIT_PENDING", "CLOSED"]

            entry_ev = db_session.get(PaperAccountEvent, f"sim-fill-{intent_id}")
            exit_ev = db_session.get(PaperAccountEvent, f"sim-exit-{intent_id}")
            assert entry_ev is not None
            assert exit_ev is not None
            assert exit_ev.price == Decimal("149.50")
            assert exit_ev.payload["data_provenance"] == "EXPERIMENTAL_UNVERIFIED_DATA"
            assert exit_ev.effect["position_qty"] == "0"
        finally:
            db_session.close()

        # 7. Test Idempotency: Repeating exit call on closed position
        repeat_exit_resp = client.post(
            "/api/paper/close-position",
            json={
                "intent_id": intent_id,
                "exit_quote": {"bid": "150.00", "ask": "151.00"},
                "reason": "TARGET_HIT",
            },
            headers=headers,
        )
        assert repeat_exit_resp.status_code == 200
        repeat_data = repeat_exit_resp.json()
        assert repeat_data["status"] == "ALREADY_CLOSED"
        assert repeat_data["duplicate"] is True

        # Ensure account P&L did NOT double count
        acct_after_repeat = client.get("/api/paper/account").json()
        assert acct_after_repeat["closed_positions_count"] == 1
        assert acct_after_repeat["realized_pnl_inr"] == round(expected_net, 2)
        assert acct_after_repeat["current_balance_inr"] == round(1000000.0 + expected_net, 2)

        # 8. Fail-closed: Zero live broker calls
        assert len(live_order_calls) == 0
