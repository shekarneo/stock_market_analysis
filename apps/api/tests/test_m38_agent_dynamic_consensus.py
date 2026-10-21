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
    assert "configured_specialist_count" in cons
    assert "reporting_specialist_count" in cons
    assert "directional_voter_count" in cons
    assert "directional_participation_rate" in cons

    # Verify all 5 safety invariants strictly preserved
    assert rep["decision"] == "NO_TRADE"
    assert rep["forecast_ready"] is False
    assert rep["paper_approved"] is False
    assert rep["live_approved"] is False
    assert rep["real_market_data_verified"] is False
    assert "SAFETY_GATE_ACTIVE" in rep["reason_codes"]
    assert "LIVE_ROUTING_DISABLED" in rep["reason_codes"]


def test_scenario_a_all_specialists_neutral():
    """Scenario A: All 6 specialists neutral."""
    agent_outputs = {
        AgentRole.MARKET_DATA.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.70, "semantic_type": "STATIC_DEFAULT"},
        AgentRole.TECHNICAL.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.50, "semantic_type": "HEURISTIC_SIGNAL_STRENGTH"},
        AgentRole.QUANT_FORECAST.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.50, "semantic_type": "UNCALIBRATED_MODEL_PROBABILITY"},
        AgentRole.OPTIONS.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.50, "semantic_type": "STATIC_DEFAULT", "findings": ["no verified options"]},
        AgentRole.GLOBAL_MACRO.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.50, "semantic_type": "HEURISTIC_SIGNAL_STRENGTH"},
        AgentRole.NEWS_EVENT.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.50, "semantic_type": "HEURISTIC_SIGNAL_STRENGTH"},
    }

    eval_result = evaluate_multi_agent_consensus(agent_outputs)
    assert eval_result.configured_specialist_count == 6
    assert eval_result.reporting_specialist_count == 6
    assert eval_result.directional_voter_count == 0
    assert eval_result.directional_participation_rate == 0.0
    assert eval_result.disagreement_index == 0.0
    assert eval_result.consensus_score == 0.0
    assert eval_result.directional_recommendation == "NEUTRAL"
    assert "INSUFFICIENT_DIRECTIONAL_PARTICIPATION" not in eval_result.vetoes
    assert "MARGINAL_CONSENSUS_NEUTRAL" in eval_result.reason_codes


def test_scenario_b_one_directional_five_neutral_participation_veto():
    """Scenario B: 1 Bullish, 5 Neutral triggers insufficient directional participation veto."""
    agent_outputs = {
        AgentRole.MARKET_DATA.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.70},
        AgentRole.TECHNICAL.value: {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.85},
        AgentRole.QUANT_FORECAST.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.50},
        AgentRole.OPTIONS.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.50, "findings": ["no verified options"]},
        AgentRole.GLOBAL_MACRO.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.50},
        AgentRole.NEWS_EVENT.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.50},
    }

    eval_result = evaluate_multi_agent_consensus(agent_outputs)
    assert eval_result.reporting_specialist_count == 6
    assert eval_result.directional_voter_count == 1
    assert eval_result.directional_participation_rate == round(1 / 6, 4)
    assert eval_result.disagreement_index == 0.0  # Lone voter has zero disagreement
    assert "INSUFFICIENT_DIRECTIONAL_PARTICIPATION" in eval_result.vetoes
    assert eval_result.directional_recommendation == "NEUTRAL"


def test_scenario_c_one_bullish_one_bearish_specialist_conflict():
    """Scenario C: 1 Bullish, 1 Bearish, 4 Neutral triggers deterministic specialist conflict veto."""
    agent_outputs = {
        AgentRole.MARKET_DATA.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.70},
        AgentRole.TECHNICAL.value: {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.85},
        AgentRole.QUANT_FORECAST.value: {"status": "SUCCESS", "directional_bias": "BEARISH", "confidence": 0.80},
        AgentRole.OPTIONS.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.50, "findings": ["no verified options"]},
        AgentRole.GLOBAL_MACRO.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.50},
        AgentRole.NEWS_EVENT.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.50},
    }

    eval_result = evaluate_multi_agent_consensus(agent_outputs)
    assert eval_result.directional_voter_count == 2
    assert eval_result.directional_participation_rate == round(2 / 6, 4)  # 33.3% >= 33%
    assert eval_result.disagreement_index == 1.0  # 1 Bullish vs 1 Bearish = complete opposition
    assert "CORE_SPECIALIST_CONFLICT" in eval_result.vetoes
    assert "EXCESSIVE_EPISTEMIC_UNCERTAINTY" in eval_result.vetoes
    assert eval_result.directional_recommendation == "NEUTRAL"


def test_scenario_d_missing_specialists_quorum_accounting():
    """Scenario D: 2 missing specialists correctly reflected in quorum breakdown."""
    agent_outputs = {
        AgentRole.TECHNICAL.value: {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.85},
        AgentRole.QUANT_FORECAST.value: {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.80},
        AgentRole.OPTIONS.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.50},
        AgentRole.NEWS_EVENT.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.50},
    }

    eval_result = evaluate_multi_agent_consensus(agent_outputs)
    assert eval_result.configured_specialist_count == 6
    assert eval_result.reporting_specialist_count == 4
    assert eval_result.missing_specialist_count == 2
    assert eval_result.failed_specialist_count == 0
    assert eval_result.directional_voter_count == 2
    assert eval_result.directional_participation_rate == 0.50  # 2 directional / 4 reporting = 50%


def test_scenario_e_unconfigured_options_zero_effective_weight():
    """Scenario E: Unconfigured options fallback assigned zero effective weight."""
    agent_outputs = {
        AgentRole.MARKET_DATA.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.70},
        AgentRole.TECHNICAL.value: {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.85},
        AgentRole.QUANT_FORECAST.value: {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.80},
        AgentRole.OPTIONS.value: {"status": "FALLBACK_USED", "directional_bias": "NEUTRAL", "confidence": 0.50, "findings": ["no verified options contracts"]},
        AgentRole.GLOBAL_MACRO.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.50},
        AgentRole.NEWS_EVENT.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.50},
    }

    eval_result = evaluate_multi_agent_consensus(agent_outputs)
    assert eval_result.fallback_only_specialist_count == 1
    opt_score = eval_result.specialist_scores[AgentRole.OPTIONS.value]
    assert opt_score["effective_weight"] == 0.0
    assert opt_score["base_weight"] == 1.5


def test_scenario_f_unverified_provenance_capping_and_veto():
    """Scenario F: Unverified market data caps quality score <= 0.50 and engages veto."""
    agent_outputs = {
        AgentRole.MARKET_DATA.value: {
            "status": "SUCCESS",
            "directional_bias": "NEUTRAL",
            "confidence": 0.70,
            "findings": ["Data unverified or synthetic fallback active"],
            "provenance_verified": False,
        },
        AgentRole.TECHNICAL.value: {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.85},
        AgentRole.QUANT_FORECAST.value: {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.80},
    }

    eval_result = evaluate_multi_agent_consensus(agent_outputs, provenance_verified=False)
    assert "UNVERIFIED_DATA_PROVENANCE" in eval_result.vetoes
    assert eval_result.directional_recommendation == "NEUTRAL"
    # Quality of all specialists capped at 0.50
    for score in eval_result.specialist_scores.values():
        assert score["quality_score"] <= 0.50


def test_scenario_g_two_bullish_adequate_participation():
    """Scenario G: 2 Bullish, 4 Neutral satisfies 33% participation and yields BULLISH recommendation."""
    agent_outputs = {
        AgentRole.MARKET_DATA.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.70},
        AgentRole.TECHNICAL.value: {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.85},
        AgentRole.QUANT_FORECAST.value: {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.80},
        AgentRole.OPTIONS.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.50, "findings": ["no verified options"]},
        AgentRole.GLOBAL_MACRO.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.50},
        AgentRole.NEWS_EVENT.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL", "confidence": 0.50},
    }

    eval_result = evaluate_multi_agent_consensus(agent_outputs)
    assert eval_result.directional_voter_count == 2
    assert eval_result.directional_participation_rate >= 0.33
    assert eval_result.disagreement_index == 0.0
    assert "INSUFFICIENT_DIRECTIONAL_PARTICIPATION" not in eval_result.vetoes
    assert "CORE_SPECIALIST_CONFLICT" not in eval_result.vetoes
    assert eval_result.consensus_score > 0.30
    assert eval_result.directional_recommendation == "BULLISH"


def test_scenario_h_simultaneous_multiple_vetoes():
    """Scenario H: Simultaneous vetoes are all captured without masking."""
    agent_outputs = {
        AgentRole.MARKET_DATA.value: {
            "status": "FALLBACK_USED",
            "directional_bias": "NEUTRAL",
            "confidence": 0.30,
            "findings": ["UNVERIFIED OR SYNTHETIC DATA FEED"],
        },
        AgentRole.TECHNICAL.value: {
            "status": "SUCCESS",
            "directional_bias": "BULLISH",
            "confidence": 0.90,
            "findings": ["Wilder ADX indicates SIDEWAYS_CONSOLIDATION regime"],
        },
        AgentRole.QUANT_FORECAST.value: {
            "status": "SUCCESS",
            "directional_bias": "BEARISH",
            "confidence": 0.90,
            "findings": [],
        },
    }

    eval_result = evaluate_multi_agent_consensus(agent_outputs, provenance_verified=False)
    assert "CORE_SPECIALIST_CONFLICT" in eval_result.vetoes
    assert "REGIME_SIDEWAYS_CONSOLIDATION" in eval_result.vetoes
    assert "EXCESSIVE_EPISTEMIC_UNCERTAINTY" in eval_result.vetoes
    assert "UNVERIFIED_DATA_PROVENANCE" in eval_result.vetoes
    assert eval_result.directional_recommendation == "NEUTRAL"

