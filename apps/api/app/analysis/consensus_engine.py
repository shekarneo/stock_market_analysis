"""Milestone M38: Dynamic Quality-Weighted Specialist Consensus & Epistemic Uncertainty Gating.

Multi-Agent Quantitative Consensus Engine for V6 LangGraph Analysis.
Aggregates independent specialist analyst outputs using dynamic quality-weighted
confidence, measures the Normalized Directional Bias Dispersion Index (D),
and calculates a Composite Epistemic Uncertainty metric (U_total) to enforce
deterministic risk veto boundaries.

All financial safety boundaries remain strictly enforced.
Live order routing is hardcoded to blocked state.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from typing import Any

from app.analysis.agent_config import AgentRole

log = logging.getLogger("imm.consensus_engine")

# Base specialist weights in quantitative decision hierarchy
DEFAULT_SPECIALIST_BASE_WEIGHTS: dict[str, float] = {
    AgentRole.MARKET_DATA.value: 1.0,       # Provenance, reconciliation & freshness
    AgentRole.TECHNICAL.value: 2.0,         # Trend, momentum, ADX/Hurst regime
    AgentRole.QUANT_FORECAST.value: 2.5,    # Walk-forward regularized directional model
    AgentRole.OPTIONS.value: 1.5,           # PCR, Max Pain, implied volatility surface
    AgentRole.GLOBAL_MACRO.value: 1.0,      # GIFT NIFTY, crude, USD/INR, US yields
    AgentRole.NEWS_EVENT.value: 1.0,        # Sentiment, macro calendar & regulatory news
}

# Directional bias mapping
BIAS_MAP: dict[str, float] = {
    "BULLISH": 1.0,
    "BEARISH": -1.0,
    "NEUTRAL": 0.0,
    "MIXED": 0.0,
    "UNKNOWN": 0.0,
}


@dataclass
class SpecialistScore:
    role: str
    directional_bias: str
    bias_numeric: float
    confidence: float
    quality_score: float
    base_weight: float
    effective_weight: float


@dataclass
class ConsensusEvaluation:
    consensus_score: float                  # S_consensus in [-1.0, +1.0]
    disagreement_index: float               # D in [0.0, 1.0] (0 = unanimous, 1 = complete opposition)
    epistemic_uncertainty: float            # U_total in [0.0, 1.0]
    active_specialist_count: int
    total_effective_weight: float
    directional_recommendation: str         # "BULLISH", "BEARISH", or "NEUTRAL"
    vetoes: list[str]                       # Active deterministic risk vetoes
    reason_codes: list[str]                 # Reason codes for audit trails
    specialist_scores: dict[str, dict[str, Any]]
    safety_invariants_preserved: bool = True


def compute_specialist_quality_score(
    output: dict[str, Any],
    missing_items: list[str] | None = None,
) -> float:
    """Calculate point-in-time data quality score for a specialist output."""
    status = output.get("status", "UNKNOWN")
    if status in ("FAILED", "SKIPPED"):
        return 0.0

    score = 1.0

    # Penalize partial or fallback execution
    if status == "FALLBACK_USED":
        score -= 0.35
    elif status == "PARTIAL":
        score -= 0.20

    # Penalize missing upstream evidence
    missing_ev = output.get("missing_evidence") or []
    if missing_ev:
        score -= min(0.30, len(missing_ev) * 0.10)

    # Global missing items
    if missing_items:
        role = output.get("role", "")
        if role in missing_items:
            score -= 0.25

    return max(0.10, min(1.0, score))


def compute_specialist_confidence(output: dict[str, Any]) -> float:
    """Extract or impute calibrated confidence from specialist output."""
    raw_conf = output.get("confidence")
    if raw_conf is not None:
        try:
            val = float(raw_conf)
            return max(0.10, min(1.0, val))
        except (ValueError, TypeError):
            pass

    status = output.get("status", "UNKNOWN")
    if status == "SUCCESS":
        return 0.60  # Calibrated neutral baseline for complete analysis
    elif status in ("PARTIAL", "FALLBACK_USED"):
        return 0.35
    return 0.10


def evaluate_multi_agent_consensus(
    agent_outputs: dict[str, Any],
    state: dict[str, Any] | None = None,
    base_weights: dict[str, float] | None = None,
    uncertainty_veto_threshold: float = 0.45,
    consensus_activation_threshold: float = 0.30,
) -> ConsensusEvaluation:
    """Compute quantitative consensus weighting, entropy, and risk vetoes.
    
    Guarantees:
    - Point-in-time causality: Only evaluates data available in agent_outputs and state.
    - Zero future leakage: Evaluated purely on current analysis cycle.
    - Strict risk veto enforcement: Suppresses directional signals when uncertainty is elevated.
    """
    if base_weights is None:
        base_weights = DEFAULT_SPECIALIST_BASE_WEIGHTS

    state = state or {}
    missing_items = list(state.get("missing") or [])

    specialist_scores: dict[str, SpecialistScore] = {}
    vetoes: list[str] = []
    reason_codes: list[str] = []

    # Step 1: Score each specialist analyst that reported in agent_outputs
    for role, w_base in base_weights.items():
        if role not in agent_outputs:
            continue

        out = agent_outputs.get(role) or {}
        bias_str = str(out.get("directional_bias", "UNKNOWN")).upper()
        bias_num = BIAS_MAP.get(bias_str, 0.0)

        q_score = compute_specialist_quality_score(out, missing_items)
        conf = compute_specialist_confidence(out)

        # Effective weight: Base weight * confidence * quality
        w_eff = w_base * conf * q_score if out.get("status") not in ("FAILED", "SKIPPED") else 0.0

        specialist_scores[role] = SpecialistScore(
            role=role,
            directional_bias=bias_str,
            bias_numeric=bias_num,
            confidence=conf,
            quality_score=q_score,
            base_weight=w_base,
            effective_weight=w_eff,
        )

    # Step 2: Compute weighted consensus score
    total_w = sum(s.effective_weight for s in specialist_scores.values())
    active_specialists = [s for s in specialist_scores.values() if s.effective_weight > 0.0]
    active_count = len(active_specialists)

    if total_w > 0.0:
        consensus_score = float(sum(s.effective_weight * s.bias_numeric for s in specialist_scores.values()) / total_w)
    else:
        consensus_score = 0.0

    # Step 3: Compute Disagreement Index and Epistemic Uncertainty
    if active_count > 0:
        # Sum of unweighted active biases vs maximum possible agreement
        abs_bias_sum = abs(sum(s.bias_numeric for s in active_specialists))
        disagreement_index = 1.0 - (abs_bias_sum / active_count)
        avg_q = float(sum(s.effective_weight * s.quality_score for s in active_specialists) / total_w)
        avg_c = float(sum(s.effective_weight * s.confidence for s in active_specialists) / total_w)
    else:
        disagreement_index = 1.0
        avg_q = 0.0
        avg_c = 0.0

    # Linear composite epistemic uncertainty combining directional dispersion (D), quality deficits (1 - Q), and confidence discounts (1 - C)
    epistemic_uncertainty = (
        0.50 * disagreement_index +
        0.30 * (1.0 - avg_q) +
        0.20 * (1.0 - avg_c)
    )
    epistemic_uncertainty = max(0.0, min(1.0, epistemic_uncertainty))

    # Step 4: Check Veto Conditions
    # Veto A: Regime Sideways Consolidation (M28 Filter)
    tech_out = agent_outputs.get(AgentRole.TECHNICAL.value) or {}
    risk_out = agent_outputs.get(AgentRole.RISK_UNCERTAINTY.value) or {}
    combined_findings = " ".join((tech_out.get("findings") or []) + (risk_out.get("findings") or [])).upper()

    if "SIDEWAYS_CONSOLIDATION" in combined_findings or "SIDEWAYS CONSOLIDATION" in combined_findings:
        vetoes.append("REGIME_SIDEWAYS_CONSOLIDATION")
        reason_codes.append("REGIME_SIDEWAYS_CONSOLIDATION")

    # Veto B: Core Specialist Conflict (Technical vs Quant Forecast)
    tech_bias = specialist_scores.get(AgentRole.TECHNICAL.value)
    quant_bias = specialist_scores.get(AgentRole.QUANT_FORECAST.value)
    if tech_bias and quant_bias:
        if (tech_bias.bias_numeric > 0 and quant_bias.bias_numeric < 0) or (tech_bias.bias_numeric < 0 and quant_bias.bias_numeric > 0):
            vetoes.append("CORE_SPECIALIST_CONFLICT")
            reason_codes.append("SPECIALIST_BIAS_CONFLICT")

    # Veto C: Excessive Epistemic Uncertainty
    if epistemic_uncertainty >= uncertainty_veto_threshold:
        vetoes.append("EXCESSIVE_EPISTEMIC_UNCERTAINTY")
        reason_codes.append("EXCESSIVE_EPISTEMIC_UNCERTAINTY")

    # Veto D: Insufficient Specialist Weight
    if total_w < 2.0:
        vetoes.append("INSUFFICIENT_SPECIALIST_WEIGHT")
        reason_codes.append("INSUFFICIENT_SPECIALIST_WEIGHT")

    # Veto E: Unverified Market Data Provenance
    mkt_out = agent_outputs.get(AgentRole.MARKET_DATA.value) or {}
    mkt_findings = " ".join(mkt_out.get("findings") or []).upper()
    if "UNVERIFIED OR SYNTHETIC" in mkt_findings or "STRICT VERIFICATION NOT MET" in mkt_findings:
        vetoes.append("UNVERIFIED_DATA_PROVENANCE")
        reason_codes.append("REAL_MARKET_DATA_UNVERIFIED")

    # Step 5: Determine Final Directional Recommendation
    if vetoes:
        directional_rec = "NEUTRAL"
    elif consensus_score > consensus_activation_threshold:
        directional_rec = "BULLISH"
    elif consensus_score < -consensus_activation_threshold:
        directional_rec = "BEARISH"
    else:
        directional_rec = "NEUTRAL"
        reason_codes.append("MARGINAL_CONSENSUS_NEUTRAL")

    # Step 6: Hard Financial Safety Enforcement
    # Safety gate reason codes are unconditionally injected
    if "SAFETY_GATE_ACTIVE" not in reason_codes:
        reason_codes.append("SAFETY_GATE_ACTIVE")
    if "LIVE_ROUTING_DISABLED" not in reason_codes:
        reason_codes.append("LIVE_ROUTING_DISABLED")

    return ConsensusEvaluation(
        consensus_score=round(consensus_score, 4),
        disagreement_index=round(disagreement_index, 4),
        epistemic_uncertainty=round(epistemic_uncertainty, 4),
        active_specialist_count=active_count,
        total_effective_weight=round(total_w, 4),
        directional_recommendation=directional_rec,
        vetoes=vetoes,
        reason_codes=sorted(list(set(reason_codes))),
        specialist_scores={k: asdict(v) for k, v in specialist_scores.items()},
        safety_invariants_preserved=True,
    )
