"""Test suite for Milestone M30: LangGraph Multi-Agent Decision Orchestration & Causal Regime Integration.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
import pytest

from app.analysis.agent_config import AgentRole
from app.analysis.agent_nodes import (
    final_decision_agent_node,
    risk_uncertainty_analyst_node,
    technical_analyst_node,
)
from app.analysis.graph import build_graph
from app.analysis.schema import AgentOutput
from app.analysis.state import AnalysisState


def test_technical_analyst_detects_sideways_regime():
    """Verify Technical Analyst node classifies range-bound action as SIDEWAYS_CONSOLIDATION."""
    # Flat observations: 25000.0 to 25002.0 (< 0.1% change)
    flat_evidence = [
        {"category": "TECHNICAL", "last_price": 25000.0, "evidence_id": "ev1"},
        {"category": "TECHNICAL", "last_price": 25001.0, "evidence_id": "ev2"},
        {"category": "TECHNICAL", "last_price": 25000.5, "evidence_id": "ev3"},
    ]
    state: AnalysisState = {"evidence": flat_evidence, "agent_outputs": {}}

    res = technical_analyst_node(state)
    out = res["agent_outputs"][AgentRole.TECHNICAL.value]

    assert out["directional_bias"] == "NEUTRAL"
    assert any("SIDEWAYS_CONSOLIDATION" in f for f in out["findings"])


def test_technical_analyst_detects_trending_bull_and_bear():
    """Verify Technical Analyst node identifies directional momentum."""
    # Bullish observations (+0.5% return)
    bull_evidence = [
        {"category": "TECHNICAL", "last_price": 25000.0, "evidence_id": "ev1"},
        {"category": "TECHNICAL", "last_price": 25125.0, "evidence_id": "ev2"},
    ]
    state_bull: AnalysisState = {"evidence": bull_evidence, "agent_outputs": {}}
    res_bull = technical_analyst_node(state_bull)
    out_bull = res_bull["agent_outputs"][AgentRole.TECHNICAL.value]

    assert out_bull["directional_bias"] == "BULLISH"
    assert any("TRENDING_BULL" in f for f in out_bull["findings"])

    # Bearish observations (-0.5% return)
    bear_evidence = [
        {"category": "TECHNICAL", "last_price": 25000.0, "evidence_id": "ev1"},
        {"category": "TECHNICAL", "last_price": 24875.0, "evidence_id": "ev2"},
    ]
    state_bear: AnalysisState = {"evidence": bear_evidence, "agent_outputs": {}}
    res_bear = technical_analyst_node(state_bear)
    out_bear = res_bear["agent_outputs"][AgentRole.TECHNICAL.value]

    assert out_bear["directional_bias"] == "BEARISH"
    assert any("TRENDING_BEAR" in f for f in out_bear["findings"])


def test_risk_analyst_vetoes_sideways_consolidation():
    """Verify Risk and Uncertainty Analyst asserts a risk veto when market is sideways."""
    tech_output = {
        "agent_id": "technical_analyst",
        "role": "technical_analyst",
        "findings": ["Market regime: SIDEWAYS_CONSOLIDATION. Price action is range-bound."],
        "directional_bias": "NEUTRAL",
    }
    state: AnalysisState = {
        "agent_outputs": {"technical_analyst": tech_output},
        "missing": [],
    }

    res = risk_uncertainty_analyst_node(state)
    out = res["agent_outputs"][AgentRole.RISK_UNCERTAINTY.value]

    assert any("RISK VETO" in f and "sideways consolidation" in f for f in out["findings"])


def test_risk_analyst_detects_specialist_conflict():
    """Verify Risk Analyst flags conflicts between opposing analyst biases."""
    agent_outputs = {
        "technical_analyst": {"directional_bias": "BULLISH", "findings": []},
        "quant_forecast_analyst": {"directional_bias": "BEARISH", "findings": []},
    }
    state: AnalysisState = {
        "agent_outputs": agent_outputs,
        "missing": [],
    }

    res = risk_uncertainty_analyst_node(state)
    out = res["agent_outputs"][AgentRole.RISK_UNCERTAINTY.value]

    assert out["directional_bias"] == "MIXED"
    assert any("CONFLICT DETECTED" in f for f in out["findings"])


def test_final_decision_agent_includes_regime_and_conflict_reasons():
    """Verify Final Decision Agent includes structured reason codes and enforces NO_TRADE."""
    agent_outputs = {
        "risk_uncertainty_analyst": {
            "findings": [
                "CONFLICT DETECTED across specialist agents: {'technical_analyst': 'BULLISH'}.",
                "RISK VETO: Market is in sideways consolidation regime (M28 filter).",
            ]
        }
    }
    state: AnalysisState = {"agent_outputs": agent_outputs, "report": {}}

    res = final_decision_agent_node(state)
    report = res["report"]

    assert report["decision"] == "NO_TRADE"
    assert "SAFETY_GATE_ACTIVE" in report["reason_codes"]
    assert "REAL_MARKET_DATA_UNVERIFIED" in report["reason_codes"]
    assert "REGIME_SIDEWAYS_CONSOLIDATION" in report["reason_codes"]
    assert "SPECIALIST_BIAS_CONFLICT" in report["reason_codes"]
    assert report["forecast_ready"] is False
    assert report["paper_approved"] is False
    assert report["live_approved"] is False
    assert report["real_market_data_verified"] is False


def test_full_langgraph_pipeline_with_regime_awareness():
    """Verify compiled LangGraph DAG runs completely and enforces all safety invariants."""
    graph = build_graph()
    initial_state: AnalysisState = {
        "run_id": "test_m30_run",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "instruments": ["NIFTY"],
        "evidence": [
            {"category": "TECHNICAL", "last_price": 25000.0, "evidence_id": "ev1"},
            {"category": "TECHNICAL", "last_price": 25001.0, "evidence_id": "ev2"},
        ],
        "agent_outputs": {},
        "missing": [],
        "errors": [],
        "accepted": [],
        "rejected": [],
        "quality": {"status": "PASS"},
        "node_status": {},
    }

    config = {"configurable": {"thread_id": "m30_test_thread"}}
    final_state = graph.invoke(initial_state, config)

    assert "report" in final_state
    rep = final_state["report"]
    assert rep["decision"] == "NO_TRADE"
    assert rep["forecast_ready"] is False
    assert rep["paper_approved"] is False
    assert rep["live_approved"] is False
    assert rep["real_market_data_verified"] is False

    # Check that all 8 specialist agents executed
    outputs = final_state.get("agent_outputs") or {}
    assert "market_data_analyst" in outputs
    assert "technical_analyst" in outputs
    assert "quant_forecast_analyst" in outputs
    assert "risk_uncertainty_analyst" in outputs
    assert "final_decision_agent" in outputs
