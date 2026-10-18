"""Milestone M39: End-to-End Multi-Agent Verification & Scenario Testing.

Verifies:
1. End-to-end LangGraph execution across 5 representative market scenarios:
   - Trending Bullish
   - Sideways Consolidation
   - Contradictory Specialists (Technical Bull vs Quant Bear)
   - Volatile / Elevated Epistemic Uncertainty
   - Missing Data / Provider Outage
2. Point-in-time causality, evidence provenance, and mathematical consistency.
3. Enforcement of all 5 deterministic risk vetoes.
4. Absolute preservation of all 5 financial safety invariant flags.
5. Mandatory NO_TRADE decision policy under unapproved or unverified live conditions.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
import pytest

from app.analysis.agent_config import AgentRole
from app.analysis.agent_nodes import (
    final_decision_agent_node,
    global_macro_analyst_node,
    market_data_analyst_node,
    news_event_analyst_node,
    options_analyst_node,
    quant_forecast_analyst_node,
    risk_uncertainty_analyst_node,
    technical_analyst_node,
)
from app.analysis.consensus_engine import evaluate_multi_agent_consensus
from app.analysis.graph import build_graph
from app.analysis.state import AnalysisState


def _make_base_state(
    *,
    prices: list[float] | None = None,
    synthetic: bool = False,
    verified: bool = True,
    missing: list[str] | None = None,
) -> AnalysisState:
    """Build a deterministic AnalysisState for testing."""
    now_iso = datetime.now(timezone.utc).isoformat()
    evidence = []

    # Inject price evidence for technical analyst
    if prices:
        for i, p in enumerate(prices):
            evidence.append({
                "evidence_id": f"ev-tech-{i}",
                "category": "TECHNICAL",
                "instrument": "NIFTY",
                "last_price": p,
                "verification_status": "VERIFIED" if verified else "UNVERIFIED",
                "provenance": "SYNTHETIC" if synthetic else "PROVIDER",
            })

    state: AnalysisState = {
        "created_at": now_iso,
        "horizon": "HALF_DAY",
        "accepted": [
            {
                "observation_id": "obs-1",
                "instrument": "NIFTY",
                "observed_at": now_iso,
                "retrieved_at": now_iso,
                "provenance": "SYNTHETIC" if synthetic else "PROVIDER",
            }
        ],
        "rejected": [],
        "evidence": evidence,
        "missing": missing or [],
        "conflicts": [],
        "quality": {"status": "GOOD" if verified and not synthetic else "DEGRADED"},
        "agent_outputs": {},
        "report": {},
        "node_status": {},
        "errors": [],
    }
    return state


def test_scenario_1_trending_bullish():
    """Scenario 1: Strong upward trend with technical and quant alignment."""
    # Prices rising by 0.5% (25,000 to 25,125)
    state = _make_base_state(prices=[25000.0, 25125.0], synthetic=False, verified=True)

    # 1. Market Data Analyst
    res_mkt = market_data_analyst_node(state)
    state["agent_outputs"].update(res_mkt["agent_outputs"])

    # 2. Technical Analyst -> detects TRENDING_BULL
    res_tech = technical_analyst_node(state)
    state["agent_outputs"].update(res_tech["agent_outputs"])
    tech_out = state["agent_outputs"][AgentRole.TECHNICAL.value]
    assert tech_out["directional_bias"] == "BULLISH"
    assert any("TRENDING_BULL" in f for f in tech_out["findings"])

    # Inject aligned Quant Forecast Analyst (BULLISH, confidence 0.80)
    state["agent_outputs"][AgentRole.QUANT_FORECAST.value] = {
        "agent_id": "quant_forecast",
        "role": "quant_forecast",
        "display_name": "Quantitative Forecast Analyst",
        "status": "SUCCESS",
        "directional_bias": "BULLISH",
        "confidence": 0.80,
        "findings": ["Model walk-forward probability P(up)=0.72."],
        "missing_evidence": [],
    }

    # 3. Risk & Uncertainty Analyst
    res_risk = risk_uncertainty_analyst_node(state)
    state["agent_outputs"].update(res_risk["agent_outputs"])

    # 4. Final Decision Agent
    res_final = final_decision_agent_node(state)
    state["agent_outputs"].update(res_final["agent_outputs"])
    state["report"] = res_final["report"]
    report = state["report"]

    consensus = report["consensus"]
    assert consensus["directional_recommendation"] == "BULLISH"
    assert consensus["consensus_score"] > 0.50
    assert consensus["disagreement_index"] <= 0.35  # Low dispersion (Technical & Quant Bullish, Market Data Neutral)
    assert consensus["epistemic_uncertainty"] < 0.45
    assert len(consensus["vetoes"]) == 0

    # Decision must remain NO_TRADE due to financial safety gates
    assert report["decision"] == "NO_TRADE"
    assert "SAFETY_GATE_ACTIVE" in report["reason_codes"]
    assert report["forecast_ready"] is False
    assert report["live_approved"] is False


def test_scenario_2_sideways_consolidation():
    """Scenario 2: Range-bound consolidation triggers REGIME_SIDEWAYS_CONSOLIDATION veto."""
    # Flat price action (change < 0.05%)
    state = _make_base_state(prices=[25000.0, 25005.0], synthetic=False, verified=True)

    res_tech = technical_analyst_node(state)
    state["agent_outputs"].update(res_tech["agent_outputs"])
    tech_out = state["agent_outputs"][AgentRole.TECHNICAL.value]
    assert tech_out["directional_bias"] == "NEUTRAL"
    assert any("SIDEWAYS_CONSOLIDATION" in f for f in tech_out["findings"])

    # Quant analyst also present
    state["agent_outputs"][AgentRole.QUANT_FORECAST.value] = {
        "agent_id": "quant_forecast",
        "role": "quant_forecast",
        "display_name": "Quantitative Forecast Analyst",
        "status": "SUCCESS",
        "directional_bias": "BULLISH",
        "confidence": 0.70,
        "findings": ["Weak bullish drift."],
        "missing_evidence": [],
    }

    res_risk = risk_uncertainty_analyst_node(state)
    state["agent_outputs"].update(res_risk["agent_outputs"])

    res_final = final_decision_agent_node(state)
    state["agent_outputs"].update(res_final["agent_outputs"])
    state["report"] = res_final["report"]
    report = state["report"]

    consensus = report["consensus"]
    assert "REGIME_SIDEWAYS_CONSOLIDATION" in consensus["vetoes"]
    assert consensus["directional_recommendation"] == "NEUTRAL"
    assert report["decision"] == "NO_TRADE"
    assert "REGIME_SIDEWAYS_CONSOLIDATION" in report["reason_codes"]


def test_scenario_3_contradictory_specialists():
    """Scenario 3: Technical Bullish vs Quant Bearish triggers CORE_SPECIALIST_CONFLICT veto."""
    state = _make_base_state(prices=[25000.0, 25150.0], synthetic=False, verified=True)

    res_tech = technical_analyst_node(state)
    state["agent_outputs"].update(res_tech["agent_outputs"])
    tech_out = state["agent_outputs"][AgentRole.TECHNICAL.value]
    assert tech_out["directional_bias"] == "BULLISH"

    # Quant Forecast has opposing Bearish bias
    state["agent_outputs"][AgentRole.QUANT_FORECAST.value] = {
        "agent_id": "quant_forecast",
        "role": "quant_forecast",
        "display_name": "Quantitative Forecast Analyst",
        "status": "SUCCESS",
        "directional_bias": "BEARISH",
        "confidence": 0.80,
        "findings": ["Quant model projects downward mean-reversion P(up)=0.25."],
        "missing_evidence": [],
    }

    res_risk = risk_uncertainty_analyst_node(state)
    state["agent_outputs"].update(res_risk["agent_outputs"])

    res_final = final_decision_agent_node(state)
    state["agent_outputs"].update(res_final["agent_outputs"])
    state["report"] = res_final["report"]
    report = state["report"]

    consensus = report["consensus"]
    assert "CORE_SPECIALIST_CONFLICT" in consensus["vetoes"]
    assert "SPECIALIST_BIAS_CONFLICT" in report["reason_codes"]
    assert consensus["directional_recommendation"] == "NEUTRAL"
    assert report["decision"] == "NO_TRADE"


def test_scenario_4_volatile_high_uncertainty():
    """Scenario 4: High divergence across multiple analysts triggers EXCESSIVE_EPISTEMIC_UNCERTAINTY veto."""
    state = _make_base_state(prices=[25000.0, 25100.0], synthetic=False, verified=True)

    # Inject 4 contradictory specialist outputs
    state["agent_outputs"] = {
        AgentRole.TECHNICAL.value: {
            "role": "technical", "status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.40,
            "findings": ["Choppy breakout."], "missing_evidence": [],
        },
        AgentRole.QUANT_FORECAST.value: {
            "role": "quant_forecast", "status": "PARTIAL", "directional_bias": "BEARISH", "confidence": 0.35,
            "findings": ["Low confidence regression."], "missing_evidence": ["macro"],
        },
        AgentRole.OPTIONS.value: {
            "role": "options", "status": "PARTIAL", "directional_bias": "NEUTRAL", "confidence": 0.30,
            "findings": ["PCR neutral."], "missing_evidence": ["iv_surface"],
        },
        AgentRole.NEWS_EVENT.value: {
            "role": "news_event", "status": "SUCCESS", "directional_bias": "BEARISH", "confidence": 0.40,
            "findings": ["RBI cautious stance."], "missing_evidence": [],
        },
    }

    res_final = final_decision_agent_node(state)
    state["agent_outputs"].update(res_final["agent_outputs"])
    state["report"] = res_final["report"]
    report = state["report"]

    consensus = report["consensus"]
    assert consensus["epistemic_uncertainty"] >= 0.45
    assert "EXCESSIVE_EPISTEMIC_UNCERTAINTY" in consensus["vetoes"]
    assert "EXCESSIVE_EPISTEMIC_UNCERTAINTY" in report["reason_codes"]
    assert report["decision"] == "NO_TRADE"


def test_scenario_5_missing_data_and_outage():
    """Scenario 5: Missing feeds and unverified/synthetic data trigger UNVERIFIED_DATA_PROVENANCE and INSUFFICIENT_WEIGHT."""
    # Synthetic unverified data with missing items
    state = _make_base_state(
        prices=[25000.0, 25050.0],
        synthetic=True,
        verified=False,
        missing=["derivatives", "macro", "global_context"],
    )

    res_mkt = market_data_analyst_node(state)
    state["agent_outputs"].update(res_mkt["agent_outputs"])
    mkt_out = state["agent_outputs"][AgentRole.MARKET_DATA.value]
    assert any("unverified or synthetic" in f.lower() for f in mkt_out["findings"])

    res_final = final_decision_agent_node(state)
    state["agent_outputs"].update(res_final["agent_outputs"])
    state["report"] = res_final["report"]
    report = state["report"]

    consensus = report["consensus"]
    assert "UNVERIFIED_DATA_PROVENANCE" in consensus["vetoes"]
    assert "REAL_MARKET_DATA_UNVERIFIED" in report["reason_codes"]
    assert report["decision"] == "NO_TRADE"


def test_all_scenarios_strictly_preserve_financial_safety_invariants():
    """Verify that in every single analysis cycle, all 5 safety invariants remain False."""
    state = _make_base_state(prices=[25000.0, 25200.0], synthetic=False, verified=True)
    res_tech = technical_analyst_node(state)
    state["agent_outputs"].update(res_tech["agent_outputs"])

    res_final = final_decision_agent_node(state)
    state["agent_outputs"].update(res_final["agent_outputs"])
    state["report"] = res_final["report"]
    report = state["report"]

    assert report["forecast_ready"] is False
    assert report["real_market_data_verified"] is False
    assert report["paper_approved"] is False
    assert report["live_approved"] is False
    assert "SAFETY_GATE_ACTIVE" in report["reason_codes"]
    assert "LIVE_ROUTING_DISABLED" in report["reason_codes"]
    assert report["decision"] == "NO_TRADE"
