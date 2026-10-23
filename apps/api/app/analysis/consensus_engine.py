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
    semantic_type: str = "UNKNOWN"
    is_probability: bool = False
    is_calibrated: bool = False
    provenance_verified: bool = False


@dataclass
class ConsensusEvaluation:
    consensus_score: float                  # S_consensus in [-1.0, +1.0]
    disagreement_index: float               # D in [0.0, 1.0] (0 = unanimous, 1 = complete opposition)
    epistemic_uncertainty: float            # U_total in [0.0, 1.0]
    active_specialist_count: int            # Backward-compatible alias for reporting_specialist_count
    total_effective_weight: float
    directional_recommendation: str         # "BULLISH", "BEARISH", or "NEUTRAL"
    vetoes: list[str]                       # Active deterministic risk vetoes
    reason_codes: list[str]                 # Reason codes for audit trails
    specialist_scores: dict[str, dict[str, Any]]
    gating_threshold: float = 0.45
    safety_invariants_preserved: bool = True
    configured_specialist_count: int = 6
    reporting_specialist_count: int = 0
    missing_specialist_count: int = 0
    failed_specialist_count: int = 0
    skipped_specialist_count: int = 0
    fallback_only_specialist_count: int = 0
    directional_voter_count: int = 0
    directional_participation_rate: float = 0.0


def compute_specialist_quality_score(
    output: dict[str, Any],
    missing_items: list[str] | None = None,
    provenance_verified: bool = True,
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

    final_score = max(0.10, min(1.0, score))
    # If market data provenance is unverified, cap quality score at 0.50
    if not provenance_verified:
        final_score = min(0.50, final_score)
    return final_score


def compute_specialist_confidence(output: dict[str, Any]) -> float | None:
    """The specialist's reported confidence, clamped to [0.10, 1.00].

    None when no confidence was reported: an unreported confidence is not imputed,
    and such a specialist carries no weight in the consensus.
    """
    raw_conf = output.get("confidence")
    if raw_conf is None:
        return None
    try:
        val = float(raw_conf)
    except (ValueError, TypeError):
        return None
    if output.get("semantic_type") == "MEASURED_HIT_RATE" and output.get("is_calibrated"):
        # A measured hit rate weighs by its skill over a coin flip: 50% carries no weight
        return max(0.0, min(1.0, 2.0 * val - 1.0))
    return max(0.10, min(1.0, val))


def evaluate_multi_agent_consensus(
    agent_outputs: dict[str, Any],
    state: dict[str, Any] | None = None,
    base_weights: dict[str, float] | None = None,
    uncertainty_veto_threshold: float = 0.45,
    consensus_activation_threshold: float = 0.30,
    provenance_verified: bool | None = None,
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

    # Check global market data provenance from findings or state
    if provenance_verified is None:
        mkt_out = agent_outputs.get(AgentRole.MARKET_DATA.value) or {}
        mkt_findings = " ".join(mkt_out.get("findings") or []).upper()
        if (
            "UNVERIFIED OR SYNTHETIC" in mkt_findings
            or "STRICT VERIFICATION NOT MET" in mkt_findings
            or state.get("quality", {}).get("status") == "FAIL"
            or mkt_out.get("provenance_verified") is False
        ):
            provenance_verified = False
        else:
            provenance_verified = True

    specialist_scores: dict[str, SpecialistScore] = {}
    vetoes: list[str] = []
    reason_codes: list[str] = []

    # Quorum and category counters
    configured_count = len(base_weights)
    reporting_count = 0
    missing_count = 0
    failed_count = 0
    skipped_count = 0
    fallback_only_count = 0

    # Step 1: Score each specialist analyst that reported in agent_outputs
    for role, w_base in base_weights.items():
        if role not in agent_outputs:
            missing_count += 1
            continue

        out = agent_outputs.get(role) or {}
        st = out.get("status", "UNKNOWN")
        if st == "FAILED":
            failed_count += 1
            continue
        if st == "SKIPPED":
            skipped_count += 1
            continue

        reporting_count += 1

        is_fallback = (
            st in ("PARTIAL", "FALLBACK_USED")
            or bool(out.get("fallback_used"))
            or (role == AgentRole.OPTIONS.value and "no verified options" in " ".join(out.get("findings") or []).lower())
        )
        if is_fallback:
            fallback_only_count += 1

        bias_str = str(out.get("directional_bias", "UNKNOWN")).upper()
        bias_num = BIAS_MAP.get(bias_str, 0.0)

        q_score = compute_specialist_quality_score(out, missing_items, provenance_verified=provenance_verified)
        conf = compute_specialist_confidence(out)

        # Semantic metadata extraction
        sem_type = str(out.get("semantic_type") or "UNKNOWN")
        is_prob = bool(out.get("is_probability", False))
        is_cal = bool(out.get("is_calibrated", False))
        node_prov = bool(out.get("provenance_verified", provenance_verified))

        # Effective weight: Base weight * confidence * quality.
        # Zero weight for: fallback options node, failed/skipped nodes, a bias that carries
        # no directional information (UNKNOWN/MIXED), or no reported confidence.
        if role == AgentRole.OPTIONS.value and is_fallback:
            w_eff = 0.0
        elif st in ("FAILED", "SKIPPED"):
            w_eff = 0.0
        elif bias_str not in {"BULLISH", "BEARISH", "NEUTRAL"} or conf is None:
            w_eff = 0.0
        else:
            w_eff = w_base * conf * q_score

        specialist_scores[role] = SpecialistScore(
            role=role,
            directional_bias=bias_str,
            bias_numeric=bias_num,
            confidence=conf if conf is not None else 0.0,
            quality_score=q_score,
            base_weight=w_base,
            effective_weight=w_eff,
            semantic_type=sem_type,
            is_probability=is_prob,
            is_calibrated=is_cal,
            provenance_verified=node_prov,
        )

    # Step 2: Compute weighted consensus score
    total_w = sum(s.effective_weight for s in specialist_scores.values())
    active_specialists = [s for s in specialist_scores.values() if s.effective_weight > 0.0]

    if total_w > 0.0:
        consensus_score = float(sum(s.effective_weight * s.bias_numeric for s in specialist_scores.values()) / total_w)
    else:
        consensus_score = 0.0

    # Step 3: Directional Voting, Disagreement Index and Epistemic Uncertainty
    directional_voters = [s for s in specialist_scores.values() if s.bias_numeric != 0.0 and s.effective_weight > 0.0]
    directional_voter_count = len(directional_voters)
    directional_participation_rate = round(directional_voter_count / reporting_count, 4) if reporting_count > 0 else 0.0

    if directional_voter_count <= 1:
        # Zero disagreement among active directional voters; neutral nodes do not inject artificial conflict
        disagreement_index = 0.0
    else:
        # Weighted: a low-weight dissenter moves the index less than a high-weight one
        voter_weight = sum(s.effective_weight for s in directional_voters)
        signed = abs(sum(s.effective_weight * s.bias_numeric for s in directional_voters))
        disagreement_index = 1.0 - (signed / voter_weight) if voter_weight > 0 else 0.0

    if total_w > 0.0:
        avg_q = float(sum(s.effective_weight * s.quality_score for s in active_specialists) / total_w)
        avg_c = float(sum(s.effective_weight * s.confidence for s in active_specialists) / total_w)
    else:
        avg_q = 0.0
        avg_c = 0.0

    # Linear composite epistemic uncertainty preserving exact existing formula:
    # 0.50 * D + 0.30 * (1.0 - avg_q) + 0.20 * (1.0 - avg_c)
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
    if not provenance_verified:
        vetoes.append("UNVERIFIED_DATA_PROVENANCE")
        reason_codes.append("REAL_MARKET_DATA_UNVERIFIED")

    # Veto F: Insufficient Directional Participation (33% minimum condition)
    if reporting_count > 0 and directional_participation_rate < 0.33 and consensus_score != 0.0:
        vetoes.append("INSUFFICIENT_DIRECTIONAL_PARTICIPATION")
        reason_codes.append("INSUFFICIENT_DIRECTIONAL_PARTICIPATION")

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
    if "SAFETY_GATE_ACTIVE" not in reason_codes:
        reason_codes.append("SAFETY_GATE_ACTIVE")
    if "LIVE_ROUTING_DISABLED" not in reason_codes:
        reason_codes.append("LIVE_ROUTING_DISABLED")

    return ConsensusEvaluation(
        consensus_score=round(consensus_score, 4),
        disagreement_index=round(disagreement_index, 4),
        epistemic_uncertainty=round(epistemic_uncertainty, 4),
        active_specialist_count=reporting_count,
        total_effective_weight=round(total_w, 4),
        directional_recommendation=directional_rec,
        vetoes=vetoes,
        reason_codes=sorted(list(set(reason_codes))),
        specialist_scores={k: asdict(v) for k, v in specialist_scores.items()},
        gating_threshold=round(uncertainty_veto_threshold, 4),
        safety_invariants_preserved=True,
        configured_specialist_count=configured_count,
        reporting_specialist_count=reporting_count,
        missing_specialist_count=missing_count,
        failed_specialist_count=failed_count,
        skipped_specialist_count=skipped_count,
        fallback_only_specialist_count=fallback_only_count,
        directional_voter_count=directional_voter_count,
        directional_participation_rate=directional_participation_rate,
    )
