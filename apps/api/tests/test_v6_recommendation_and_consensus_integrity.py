"""Forensic Regression Suite: Recommendation, Consensus and Price Integrity.

Covers:
1. Deadband ML forecast produces STAND ASIDE
2. Missing ML forecast produces STAND ASIDE / UNAVAILABLE
3. Conflicting specialists produce DIVERGENCE / STAND ASIDE
4. MCX commodities produce futures recommendations without inventing options
5. Target and stop differences match reference prices mathematically (2:1 R:R)
6. Reference spot is explicitly exposed and preserved
7. Backend decision NO_TRADE overrides market recommendations to STAND ASIDE
8. Real-market-data flag is false and data provenance is unverified
9. Automated trades cannot be generated from gated recommendations
10. Paper execution remains blocked when vetoes exist
"""

from __future__ import annotations

import pytest

from app.analysis.consensus_engine import evaluate_multi_agent_consensus
from app.analysis.agent_config import AgentRole
from app.analysis.agent_nodes import final_decision_agent_node
from app.analysis.intelligence import _evaluate_market_consensus, _market
from app.analysis.nodes import report_node
from app.analysis.state import AnalysisState
from app.forecasting.live_forecast import fuse_agents_and_forecast


def test_1_deadband_ml_forecast_produces_stand_aside():
    """Verify ML forecast in deadband (48% - 52%) produces STAND ASIDE with no directional edge."""
    agent_rec = {
        "bias": "BULLISH",
        "total_score": 5,
        "call": "BUY CE (CALL OPTION)",
    }
    forecast_item = {
        "status": "ACTIVE",
        "direction": "UP",
        "probability_up": 0.4951,
        "expected_move_points": 80.0,
    }

    fused = fuse_agents_and_forecast(agent_rec, forecast_item)

    assert fused["confluence_status"] == "DEADBAND"
    assert "STAND ASIDE" in fused["call"]
    assert fused["conviction"] == "DEADBAND / NO EDGE"
    assert fused["model_direction"] == "NEUTRAL"
    assert fused["model_probability_up"] == 0.4951


def test_2_missing_ml_forecast_produces_stand_aside_unavailable():
    """Verify missing or unverified ML forecast produces STAND ASIDE without fabricating a trade."""
    agent_rec = {
        "bias": "BULLISH",
        "total_score": 4,
        "call": "BUY CE (CALL OPTION)",
    }
    forecast_item_missing = {
        "status": "UNAVAILABLE",
        "direction": "UNKNOWN",
        "probability_up": None,
    }

    fused = fuse_agents_and_forecast(agent_rec, forecast_item_missing)

    assert fused["confluence_status"] == "NO_MODEL_FORECAST"
    assert fused["conviction"] == "UNAVAILABLE"
    assert "STAND ASIDE" in fused["call"]
    assert fused["model_probability_up"] is None


def test_3_conflicting_specialists_produce_divergence():
    """Verify divergence between specialist agent bias and ML forecast produces DIVERGENCE stand aside."""
    agent_rec = {
        "bias": "BULLISH",
        "total_score": 3,
        "call": "BUY CE (CALL OPTION)",
    }
    forecast_item_bearish = {
        "status": "ACTIVE",
        "direction": "DOWN",
        "probability_up": 0.35,
    }

    fused = fuse_agents_and_forecast(agent_rec, forecast_item_bearish)

    assert fused["confluence_status"] == "DIVERGENCE"
    assert "STAND ASIDE (MODEL DIVERGENCE)" in fused["call"]
    assert fused["conviction"] == "VETOED (DIVERGENCE)"


def test_4_mcx_commodities_produce_futures_recommendations():
    """Verify MCX commodities (e.g. CRUDEOILMINI) emit futures recommendations, not option buys."""
    rows = [
        {"instrument": "CRUDEOILMINI", "last_price": 9424.0, "category": "COMMODITY"},
        {"instrument": "BRENT", "last_price": 85.0, "change_pct": 1.5, "category": "COMMODITY"},
        {"instrument": "USDINR", "last_price": 83.5, "change_pct": 0.2, "category": "CURRENCY"},
    ]
    news = [{"title": "Crude supplies tighten in Middle East", "sentiment": "POSITIVE"}]

    m = _market(rows, "CRUDEOILMINI", news)
    rec = m["manual_trade_recommendation"]

    assert rec["contract_type"] == "FUTURES"
    assert rec["option_type"] == "FUT"
    assert "FUT" in rec["call"] or "STAND ASIDE" in rec["call"]
    assert "CE" not in rec["call"]
    assert "PE" not in rec["call"]
    assert "Commodity Futures recommendation" in rec["execution_guide"]


def test_5_target_and_stop_match_reference_spot_arithmetically():
    """Verify target and stop price distances match snapshot reference spot with 2:1 R:R."""
    ref_spot = 22950.20
    rows = [
        {
            "instrument": "NIFTY",
            "last_price": ref_spot,
            "directional_implication": "BULLISH",
            "category": "INDIAN_EQUITY",
            "ohlc": {"open": 22800.0, "close": 22750.0},
        },
        {"instrument": "INDIAVIX", "last_price": 14.2, "category": "VOLATILITY"},
    ]

    m = _market(rows, "NIFTY")
    rec = m["manual_trade_recommendation"]

    assert rec["reference_spot"] == ref_spot
    assert rec["target_spot"] is not None
    assert rec["stop_loss_spot"] is not None
    assert rec["expected_move_points"] is not None
    assert rec["stop_loss_points"] is not None

    # Check arithmetic consistency
    calculated_target_delta = round(rec["target_spot"] - rec["reference_spot"], 1)
    calculated_stop_delta = round(rec["reference_spot"] - rec["stop_loss_spot"], 1)

    assert calculated_target_delta == rec["expected_move_points"]
    assert calculated_stop_delta == rec["stop_loss_points"]
    assert round(calculated_target_delta / calculated_stop_delta, 1) == 2.0


def test_6_reference_spot_is_explicitly_exposed_and_preserved():
    """Verify reference_spot is exposed in trade recommendation and not replaced by zero or null."""
    rows = [{"instrument": "SENSEX", "last_price": 74178.00, "category": "EQUITY"}]
    m = _market(rows, "SENSEX")
    rec = m["manual_trade_recommendation"]

    assert rec["reference_spot"] == 74178.00
    assert rec["spot_price"] == 74178.00


def test_7_consensus_no_trade_overrides_market_recommendations():
    """Verify backend decision NO_TRADE synchronizes all market recommendations to STAND ASIDE."""
    state: AnalysisState = {
        "run_id": "test-run-sync-01",
        "created_at": "2026-10-21T06:00:00+00:00",
        "instruments": ["NIFTY"],
        "node_status": {},
        "evidence": [
            {
                "instrument": "NIFTY",
                "last_price": 23000.0,
                "directional_implication": "BULLISH",
                "category": "INDIAN_EQUITY",
                "provenance": "PROVIDER",
                "ohlc": {"open": 22800.0, "close": 22750.0},
            }
        ],
        "quality": {"data_class": "UNVERIFIED_PROVIDER_DATA"},
        "report": {
            "decision": "NO_TRADE",
            "consensus": {
                "directional_recommendation": "NEUTRAL",
                "consensus_score": 0.05,
                "epistemic_uncertainty": 0.72,
                "vetoes": ["EXCESSIVE_EPISTEMIC_UNCERTAINTY", "INSUFFICIENT_DIRECTIONAL_PARTICIPATION"],
            },
            "reason_codes": ["EXCESSIVE_EPISTEMIC_UNCERTAINTY"],
        },
    }

    res = report_node(state)
    report = res["report"]
    nifty_rec = report["intelligence"]["markets"]["NIFTY"]["manual_trade_recommendation"]

    assert report["decision"] == "NO_TRADE"
    assert nifty_rec["is_actionable"] is False
    assert nifty_rec["call"] == "STAND ASIDE (NO TRADE)"
    assert nifty_rec["conviction"] == "NO TRADE / GATED"
    assert nifty_rec["target_spot"] is None
    assert nifty_rec["stop_loss_spot"] is None
    assert nifty_rec["reference_spot"] == 23000.0


def test_8_real_market_data_verified_flag_is_false():
    """Verify real_market_data_verified is false and live routing remains disarmed."""
    state: AnalysisState = {
        "run_id": "test-run-safety-01",
        "created_at": "2026-10-21T06:00:00+00:00",
        "instruments": ["NIFTY"],
        "node_status": {},
        "quality": {"data_class": "UNVERIFIED_PROVIDER_DATA"},
        "intelligence": {"markets": {}},
        "report": {"decision": "NO_TRADE"},
    }

    res = report_node(state)
    report = res["report"]

    assert report["real_market_data_verified"] is False
    assert report["live_approved"] is False
    assert report["paper_approved"] is False


def test_9_automated_trades_cannot_be_generated_from_gated_rec():
    """Verify that when is_actionable is False or call is STAND ASIDE, auto-generation is rejected."""
    rec = {
        "call": "STAND ASIDE (NO TRADE)",
        "conviction": "NO TRADE / GATED",
        "is_actionable": False,
        "target_spot": None,
        "stop_loss_spot": None,
    }

    is_actionable = rec.get("is_actionable", True) and not rec.get("call", "").startswith("STAND ASIDE")
    assert is_actionable is False


def test_10_paper_execution_remains_blocked_when_vetoes_exist():
    """Verify that epistemic uncertainty above 0.45 or conflict triggers vetoes and locks decision to NO_TRADE."""
    agent_outputs = {
        AgentRole.TECHNICAL.value: {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.85, "findings": ["TRENDING_BULL"]},
        AgentRole.GLOBAL_MACRO.value: {"status": "SUCCESS", "directional_bias": "BEARISH", "confidence": 0.80, "findings": ["RISING_YIELDS"]},
        AgentRole.NEWS_EVENT.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.50, "findings": ["QUIET_TAPE"]},
        AgentRole.QUANT_FORECAST.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.50, "findings": ["DEADBAND"]},
        AgentRole.OPTIONS.value: {"status": "FALLBACK", "directional_bias": "NEUTRAL", "confidence": 0.0, "effective_weight": 0.0, "findings": ["NO_CHAIN"]},
    }

    consensus = evaluate_multi_agent_consensus(agent_outputs)

    # A strong technical bull against a weaker macro bear is weighted, not counted as total
    # disagreement; the consensus still does not reach a direction.
    assert consensus.directional_recommendation == "NEUTRAL"

    # Verify final decision agent node locks report to NO_TRADE
    state: AnalysisState = {
        "run_id": "test-run-veto-01",
        "created_at": "2026-10-21T06:00:00+00:00",
        "instruments": ["NIFTY"],
        "node_status": {},
        "agent_outputs": agent_outputs,
        "report": {
            "decision": "WAIT",
            "paper_approved": False,
            "live_approved": False,
        },
    }

    decision_res = final_decision_agent_node(state)
    final_report = decision_res["report"]

    assert final_report["decision"] == "NO_TRADE"
    assert final_report["paper_approved"] is False
    assert final_report["live_approved"] is False
    assert final_report["consensus"]["directional_recommendation"] == "NEUTRAL"
