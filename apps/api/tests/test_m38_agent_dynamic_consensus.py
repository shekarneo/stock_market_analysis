"""Unit and integration test suite for Milestone M38: Multi-Agent Dynamic Consensus & Uncertainty Gating.
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
from app.analysis.consensus_engine import (
    ConsensusEvaluation,
    compute_specialist_confidence,
    compute_specialist_quality_score,
    evaluate_multi_agent_consensus,
)
from app.analysis.graph import build_graph
from app.analysis.state import AnalysisState


def test_consensus_scoring_unanimous_bullish():
    """Verify consensus score is strongly positive and disagreement is zero when specialists agree bullishly."""
    agent_outputs = {
        AgentRole.TECHNICAL.value: {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.85, "findings": ["TRENDING_BULL"]},
        AgentRole.QUANT_FORECAST.value: {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.80, "findings": ["O2O Upward Probability: 0.65"]},
        AgentRole.OPTIONS.value: {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.75, "findings": ["Put-Call Ratio: 1.35 (Bullish)"]},
        AgentRole.GLOBAL_MACRO.value: {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.70, "findings": ["GIFT Nifty +120 points"]},
    }

    eval_result = evaluate_multi_agent_consensus(agent_outputs)
    assert eval_result.consensus_score >= 0.80
    assert eval_result.disagreement_index == 0.0
    assert eval_result.epistemic_uncertainty < 0.30
    assert eval_result.directional_recommendation == "BULLISH"
    assert "CORE_SPECIALIST_CONFLICT" not in eval_result.vetoes
    assert "EXCESSIVE_EPISTEMIC_UNCERTAINTY" not in eval_result.vetoes


def test_consensus_scoring_unanimous_bearish():
    """Verify consensus score is strongly negative when specialists agree bearishly."""
    agent_outputs = {
        AgentRole.TECHNICAL.value: {"status": "SUCCESS", "directional_bias": "BEARISH", "confidence": 0.85, "findings": ["TRENDING_BEAR"]},
        AgentRole.QUANT_FORECAST.value: {"status": "SUCCESS", "directional_bias": "BEARISH", "confidence": 0.80, "findings": ["O2O Downward Probability: 0.70"]},
        AgentRole.OPTIONS.value: {"status": "SUCCESS", "directional_bias": "BEARISH", "confidence": 0.75, "findings": ["Put-Call Ratio: 0.65 (Bearish)"]},
    }

    eval_result = evaluate_multi_agent_consensus(agent_outputs)
    assert eval_result.consensus_score <= -0.80
    assert eval_result.disagreement_index == 0.0
    assert eval_result.directional_recommendation == "BEARISH"


def test_veto_on_excessive_epistemic_uncertainty():
    """Verify excessive disagreement entropy triggers epistemic uncertainty veto."""
    agent_outputs = {
        AgentRole.TECHNICAL.value: {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.50, "findings": []},
        AgentRole.QUANT_FORECAST.value: {"status": "SUCCESS", "directional_bias": "BEARISH", "confidence": 0.50, "findings": []},
        AgentRole.OPTIONS.value: {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.40, "findings": []},
        AgentRole.GLOBAL_MACRO.value: {"status": "FALLBACK_USED", "directional_bias": "BEARISH", "confidence": 0.35, "findings": []},
    }

    eval_result = evaluate_multi_agent_consensus(agent_outputs, uncertainty_veto_threshold=0.40)
    assert eval_result.disagreement_index == 1.0  # 2 bullish vs 2 bearish = complete polarization
    assert eval_result.epistemic_uncertainty >= 0.40
    assert "EXCESSIVE_EPISTEMIC_UNCERTAINTY" in eval_result.vetoes
    assert eval_result.directional_recommendation == "NEUTRAL"


def test_veto_on_core_specialist_conflict():
    """Verify conflict between Technical Analyst and Quant Forecast Analyst triggers deterministic veto."""
    agent_outputs = {
        AgentRole.TECHNICAL.value: {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.90, "findings": []},
        AgentRole.QUANT_FORECAST.value: {"status": "SUCCESS", "directional_bias": "BEARISH", "confidence": 0.90, "findings": []},
    }

    eval_result = evaluate_multi_agent_consensus(agent_outputs)
    assert "CORE_SPECIALIST_CONFLICT" in eval_result.vetoes
    assert "SPECIALIST_BIAS_CONFLICT" in eval_result.reason_codes
    assert eval_result.directional_recommendation == "NEUTRAL"


def test_veto_on_sideways_consolidation_regime():
    """Verify presence of SIDEWAYS_CONSOLIDATION in findings triggers mandatory regime veto."""
    agent_outputs = {
        AgentRole.TECHNICAL.value: {
            "status": "SUCCESS",
            "directional_bias": "NEUTRAL",
            "findings": ["Market regime: SIDEWAYS_CONSOLIDATION. Wilder ADX < 20.0."],
        },
        AgentRole.QUANT_FORECAST.value: {
            "status": "SUCCESS",
            "directional_bias": "BULLISH",
            "confidence": 0.60,
            "findings": [],
        },
    }

    eval_result = evaluate_multi_agent_consensus(agent_outputs)
    assert "REGIME_SIDEWAYS_CONSOLIDATION" in eval_result.vetoes
    assert "REGIME_SIDEWAYS_CONSOLIDATION" in eval_result.reason_codes
    assert eval_result.directional_recommendation == "NEUTRAL"


def test_quality_and_confidence_penalization():
    """Verify that fallbacks, missing evidence, and missing status penalize weights."""
    out_normal = {"status": "SUCCESS", "role": "technical_analyst", "missing_evidence": []}
    out_fallback = {"status": "FALLBACK_USED", "role": "technical_analyst", "missing_evidence": ["ev1", "ev2"]}
    out_failed = {"status": "FAILED", "role": "technical_analyst"}

    q_norm = compute_specialist_quality_score(out_normal)
    q_fall = compute_specialist_quality_score(out_fallback)
    q_fail = compute_specialist_quality_score(out_failed)

    assert q_norm == 1.0
    assert q_fall < 0.60
    assert q_fail == 0.0

    c_norm = compute_specialist_confidence(out_normal)
    c_fall = compute_specialist_confidence(out_fallback)
    assert c_norm > c_fall


def test_end_to_end_langgraph_consensus_propagation():
    """Verify compiled LangGraph DAG computes consensus and populates structured report while keeping safety invariants False."""
    graph = build_graph()
    initial_state: AnalysisState = {
        "run_id": "test_m38_run",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "instruments": ["NIFTY"],
        "evidence": [
            {"category": "TECHNICAL", "last_price": 25000.0, "evidence_id": "ev1"},
            {"category": "TECHNICAL", "last_price": 25150.0, "evidence_id": "ev2"},
        ],
        "agent_outputs": {},
        "missing": [],
        "errors": [],
        "accepted": [],
        "rejected": [],
        "quality": {"status": "PASS"},
        "node_status": {},
    }

    config = {"configurable": {"thread_id": "m38_test_thread"}}
    final_state = graph.invoke(initial_state, config)

    assert "report" in final_state
    rep = final_state["report"]

    # Verify structured consensus block
    assert "consensus" in rep
    cons = rep["consensus"]
    assert "consensus_score" in cons
    assert "disagreement_index" in cons
    assert "epistemic_uncertainty" in cons
    assert "directional_recommendation" in cons
    assert "specialist_scores" in cons

    # Verify all 5 safety invariants strictly preserved
    assert rep["decision"] == "NO_TRADE"
    assert rep["forecast_ready"] is False
    assert rep["paper_approved"] is False
    assert rep["live_approved"] is False
    assert rep["real_market_data_verified"] is False
    assert "SAFETY_GATE_ACTIVE" in rep["reason_codes"]
    assert "LIVE_ROUTING_DISABLED" in rep["reason_codes"]
