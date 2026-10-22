"""Signal direction and decision-path regression tests.

Covers: PE targets below spot, crude sign applied once, India VIX vs other VIX rows,
technical analysis on a single instrument, one gated decision path, and the
instrument master. Offline; no provider is called.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.analysis.agent_config import AgentRole
from app.analysis.agent_nodes import technical_analyst_node
from app.analysis.intelligence import _evaluate_market_consensus, _market
from app.analysis.nodes import apply_decision_gate
from app.instrument_specs import get_spec, lot_size_for, strike_step_for
from app.instruments import is_india_vix_row
from app.market.groww_market_snapshot import build_groww_market_observations
from app.risk.portfolio_risk import calculate_volatility_parity_size

INDIA_VIX = {"instrument": "VIX", "name": "India VIX (Volatility Index)", "last_price": 14.2, "category": "GLOBAL_MARKET",
             "claim": "Groww reported indicator India VIX (Volatility Index) at 14.2 pts."}


@pytest.fixture(autouse=True)
def _no_live_chain(monkeypatch):
    import app.market.groww_options as go

    monkeypatch.setattr(go, "get_live_option_quote", lambda *a, **k: None)


# --- PE direction --------------------------------------------------------------

def test_bearish_pe_call_puts_target_below_spot():
    spot = 25000.0
    rows = [
        {"instrument": "NIFTY", "last_price": spot, "category": "INDIAN_MARKET",
         "ohlc": {"open": 25200.0, "close": 25200.0}},  # -0.79% vs reference close
        INDIA_VIX,
    ]
    news = [{"directions": ["BEARISH"]}]
    rec = _market(rows, "NIFTY", news)["manual_trade_recommendation"]
    assert "PE" in rec["call"]
    assert rec["target_spot"] < spot
    assert rec["stop_loss_spot"] > spot


# --- Crude sign ----------------------------------------------------------------

def test_snapshot_crude_rows_carry_raw_move_and_equity_implication():
    stamp = "2026-10-16T05:00:00+00:00"
    obs = build_groww_market_observations(
        [
            {"instrument": "CRUDEOILMINI", "last_price": 6200.0, "day_change": 45.0, "retrieved_at": stamp},
            {"instrument": "GOLD", "last_price": 72000.0, "day_change": -100.0, "retrieved_at": stamp},
            {"instrument": "CRUDE", "last_price": 6150.0, "day_change": None, "retrieved_at": stamp},
        ],
        [{"instrument": "VIX", "last_price": 18.0, "day_change": 1.2, "retrieved_at": stamp}],
        [],
    )
    by = {o["instrument"]: o for o in obs}
    assert by["CRUDEOILMINI"]["price_direction"] == "UP"
    assert by["CRUDEOILMINI"]["directional_implication"] == "BEARISH"  # rising crude: equity headwind
    assert by["GOLD"]["directional_implication"] == "UNKNOWN"  # no established equity implication
    assert by["CRUDE"]["price_direction"] == "UNKNOWN"  # missing change is never treated as 0
    assert by["VIX"]["directional_implication"] == "BEARISH"  # rising volatility is risk-off


def _macro_vote(consensus: dict) -> dict:
    return next(v for v in consensus["agent_votes"] if v["agent"] == "Macro & Cross-Asset Agent")


def test_rising_crude_is_a_headwind_for_nifty():
    rows = [
        {"instrument": "NIFTY", "last_price": 25000.0, "category": "INDIAN_MARKET"},
        {"instrument": "CRUDE", "category": "MACRO", "price_direction": "UP", "directional_implication": "BEARISH",
         "last_price": 6200.0, "claim": "crude"},
    ]
    vote = _macro_vote(_evaluate_market_consensus(rows, "NIFTY"))
    assert vote["stance"] == "BEARISH"
    assert "Crude rising" in vote["summary"]


def test_crudeoilmini_trend_uses_its_own_price_move():
    rows = [{"instrument": "CRUDEOILMINI", "category": "MACRO", "price_direction": "UP",
             "directional_implication": "BEARISH", "last_price": 6200.0, "claim": "crude mini"}]
    consensus = _evaluate_market_consensus(rows, "CRUDEOILMINI")
    tech = next(v for v in consensus["agent_votes"] if v["agent"] == "Indian Technicals Agent")
    assert tech["stance"] == "BULLISH"
    assert consensus["iv"] is None  # India VIX is not crude volatility


# --- VIX -------------------------------------------------------------------------

def test_india_vix_detection():
    assert is_india_vix_row(INDIA_VIX)
    assert is_india_vix_row({"instrument": "INDIA_VIX"})
    assert not is_india_vix_row({"instrument": "VIX", "name": "CBOE Volatility Index"})


def test_non_india_vix_is_not_used_for_sizing():
    rows = [
        {"instrument": "NIFTY", "last_price": 25000.0, "category": "INDIAN_MARKET"},
        {"instrument": "VIX", "name": "CBOE Volatility Index", "last_price": 30.0, "category": "GLOBAL_MARKET", "claim": "cboe"},
    ]
    assert _evaluate_market_consensus(rows, "NIFTY")["iv"] is None


# --- Technical analyst -------------------------------------------------------

def test_technical_analyst_ignores_other_instruments():
    state = {
        "instruments": ["NIFTY"],
        "agent_outputs": {},
        "evidence": [
            {"category": "INDIAN_MARKET", "instrument": "NIFTY", "last_price": 25000.0, "evidence_id": "n1"},
            {"category": "INDIAN_MARKET", "instrument": "SENSEX", "last_price": 82000.0, "evidence_id": "s1"},
        ],
    }
    out = technical_analyst_node(state)["agent_outputs"][AgentRole.TECHNICAL.value]
    assert out["directional_bias"] == "UNKNOWN"  # one NIFTY observation, no reference close
    assert "s1" not in out["evidence_references"]


def test_technical_analyst_uses_reference_close_for_single_quote():
    state = {
        "instruments": ["NIFTY"],
        "agent_outputs": {},
        "evidence": [{"category": "INDIAN_MARKET", "instrument": "NIFTY", "last_price": 25125.0,
                      "ohlc": {"close": 25000.0}, "evidence_id": "n1"}],
    }
    out = technical_analyst_node(state)["agent_outputs"][AgentRole.TECHNICAL.value]
    assert out["directional_bias"] == "BULLISH"


# --- Decision gate -----------------------------------------------------------

def _intel_with_call(call: str, bias: str) -> dict:
    return {"markets": {"NIFTY": {
        "decision": call,
        "bias": bias,
        "options_evaluation": {"verdict": "ACTIVE"},
        "risk_veto": {"vetoed": False},
        "manual_trade_recommendation": {
            "call": call, "bias": bias, "target_spot": 25100.0, "stop_loss_spot": 24950.0,
            "expected_move_points": 100.0, "stop_loss_points": 50.0,
            "top_5_options": [{"strike": 25000, "entry_premium": 110.0, "target_premium": 160.0, "stop_loss_premium": 85.0}],
            "alternate_options": [],
        },
    }}}


def test_no_trade_gates_every_directional_field():
    intel = _intel_with_call("BUY CE (CALL OPTION)", "BULLISH")
    apply_decision_gate(intel, decision="NO_TRADE", vetoes=["SAFETY_GATE_ACTIVE"], consensus_direction="NEUTRAL")
    m = intel["markets"]["NIFTY"]
    rec = m["manual_trade_recommendation"]
    assert m["decision"] == "NO_TRADE"
    assert m["options_evaluation"]["verdict"] == "NO_TRADE"
    assert m["risk_veto"]["vetoed"] is True
    assert rec["call"] == "STAND ASIDE (NO TRADE)"
    assert rec["ungated_signal"]["call"] == "BUY CE (CALL OPTION)"
    pick = rec["top_5_options"][0]
    assert pick["entry_premium"] == 110.0  # reference only
    assert pick["target_premium"] is None and pick["stop_loss_premium"] is None


def test_call_conflicting_with_consensus_is_gated():
    intel = _intel_with_call("BUY PE (PUT OPTION)", "BEARISH")
    apply_decision_gate(intel, decision="BUY_CE", vetoes=[], consensus_direction="BULLISH")
    rec = intel["markets"]["NIFTY"]["manual_trade_recommendation"]
    assert rec["call"] == "STAND ASIDE (NO TRADE)"
    assert "CALL_CONFLICTS_WITH_CONSENSUS" in rec["gating_vetoes"]


def test_call_conflicting_with_fused_bias_is_gated():
    intel = _intel_with_call("BUY CE (CALL OPTION)", "BEARISH (QUANT OVERRIDE)")
    apply_decision_gate(intel, decision="BUY_CE", vetoes=[], consensus_direction="BULLISH")
    rec = intel["markets"]["NIFTY"]["manual_trade_recommendation"]
    assert "CALL_CONFLICTS_WITH_FUSED_BIAS" in rec["gating_vetoes"]


def test_consistent_call_is_left_actionable():
    intel = _intel_with_call("BUY CE (CALL OPTION)", "BULLISH")
    apply_decision_gate(intel, decision="BUY_CE", vetoes=[], consensus_direction="BULLISH")
    assert intel["markets"]["NIFTY"]["manual_trade_recommendation"]["call"] == "BUY CE (CALL OPTION)"


# --- Instrument master -------------------------------------------------------

def test_instrument_master_is_the_source_for_contract_specs():
    assert get_spec("CRUDEMINI").instrument == "CRUDEOILMINI"
    assert lot_size_for("SENSEX") == 20
    assert strike_step_for("NIFTY") == 50
    assert get_spec("BANKNIFTY") is None


def test_sizing_refuses_unknown_instrument():
    res = calculate_volatility_parity_size(
        instrument="BANKNIFTY", total_capital_inr=1_000_000.0, entry_price=100.0,
        stop_loss_price=80.0, atr_value=10.0,
    )
    assert res.decision == "NO_TRADE"
    assert "INVALID_LOT_SIZE" in res.reasons


def test_simulation_lot_size_never_defaults():
    from app.execution.simulation import _resolve_lot_size

    assert _resolve_lot_size(None, "NIFTY") == Decimal(lot_size_for("NIFTY"))
    assert _resolve_lot_size("75", "NIFTY") == Decimal("75")
    with pytest.raises(ValueError):
        _resolve_lot_size(None, "BANKNIFTY")


def test_untracked_instrument_gets_no_strikes():
    m = _market([{"instrument": "BANKNIFTY", "last_price": 52000.0, "category": "INDIAN_MARKET"}], "BANKNIFTY")
    assert m["status"] == "NOT_IN_INSTRUMENT_MASTER"
    assert m["manual_trade_recommendation"] is None
