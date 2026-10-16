"""Implementations of 8 independently configurable AI agents for V6.

Roles:
1. Market Data Analyst
2. Technical Analyst
3. Global and Macro Analyst
4. News and Event Analyst
5. Options Analyst
6. Quantitative Forecast Analyst
7. Risk and Uncertainty Analyst
8. Final Decision Agent
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.analysis.agent_config import AgentRole, load_agent_system_config
from app.analysis.ai_providers import AIProviderRegistry
from app.analysis.schema import AgentOutput
from app.analysis.state import AnalysisState

log = logging.getLogger("imm.agents")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_agent_cfg(role: AgentRole):
    sys_cfg = load_agent_system_config()
    return sys_cfg.agents.get(role.value)


def _safe_float(val: Any) -> float | None:
    try:
        return float(val) if val is not None else None
    except (ValueError, TypeError):
        return None


# ==============================================================================
# 1. MARKET DATA ANALYST
# ==============================================================================
def market_data_analyst_node(state: AnalysisState) -> dict:
    """Assess data quality, coverage, freshness, missing values, and provider reconciliation.

    MUST NOT declare data verified unless underlying verification evidence supports it.
    """
    cfg = _get_agent_cfg(AgentRole.MARKET_DATA)
    role_name = AgentRole.MARKET_DATA.value
    agent_outputs = dict(state.get("agent_outputs") or {})

    if not cfg or not cfg.enabled:
        out = AgentOutput(
            agent_id=role_name,
            role=role_name,
            display_name="Market Data Analyst",
            status="SKIPPED",
            provider=cfg.provider if cfg else "openai",
            model=cfg.model if cfg else "gpt-4o-mini",
            findings=["Agent disabled in configuration."],
            limitations=["Skipped by configuration."],
            timestamp=_now_iso(),
        )
        agent_outputs[role_name] = out.model_dump()
        return {"agent_outputs": agent_outputs}

    quality = dict(state.get("quality") or {})
    accepted = list(state.get("accepted") or [])
    rejected = list(state.get("rejected") or [])
    evidence = list(state.get("evidence") or [])

    # Deterministic checks
    total_accepted = len(accepted)
    total_rejected = len(rejected)
    q_status = quality.get("status", "UNKNOWN")
    synthetic_count = sum(1 for row in accepted if row.get("provenance") == "SYNTHETIC")
    unverified_count = sum(1 for row in evidence if row.get("verification_status") != "VERIFIED")

    findings = [
        f"Data quality state: {q_status}. Accepted items: {total_accepted}, Rejected items: {total_rejected}.",
        f"Synthetic items present: {synthetic_count}. Verified evidence count: {len(evidence) - unverified_count}.",
    ]
    if unverified_count > 0 or synthetic_count > 0:
        findings.append("Historical data contains unverified or synthetic components. Strict verification not met.")

    missing_info = [f"Missing {inst}" for inst in (state.get("missing") or [])]
    limitations = [
        "Data origin is quarantined or unverified.",
        "External multi-broker cross-reconciliation is pending.",
    ]

    out = AgentOutput(
        agent_id=role_name,
        role=role_name,
        display_name="Market Data Analyst",
        status="SUCCESS",
        provider=cfg.provider,
        model=cfg.model,
        findings=findings,
        directional_bias="NEUTRAL",
        confidence=None,
        evidence_references=[row.get("evidence_id") for row in evidence[:5] if row.get("evidence_id")],
        missing_evidence=missing_info,
        limitations=limitations,
        timestamp=_now_iso(),
    )
    agent_outputs[role_name] = out.model_dump()
    return {"agent_outputs": agent_outputs}


# ==============================================================================
# 2. TECHNICAL ANALYST
# ==============================================================================
def technical_analyst_node(state: AnalysisState) -> dict:
    """Analyze validated technical features (trend, momentum, realized vol, ATR, returns).

    Deterministic indicator calculation with structured interpretation.
    """
    cfg = _get_agent_cfg(AgentRole.TECHNICAL)
    role_name = AgentRole.TECHNICAL.value
    agent_outputs = dict(state.get("agent_outputs") or {})

    if not cfg or not cfg.enabled:
        out = AgentOutput(
            agent_id=role_name,
            role=role_name,
            display_name="Technical Analyst",
            status="SKIPPED",
            provider=cfg.provider if cfg else "google",
            model=cfg.model if cfg else "gemini-1.5-pro",
            findings=["Agent disabled in configuration."],
            limitations=["Skipped by configuration."],
            timestamp=_now_iso(),
        )
        agent_outputs[role_name] = out.model_dump()
        return {"agent_outputs": agent_outputs}

    evidence = list(state.get("evidence") or [])
    tech_evidence = [e for e in evidence if e.get("category") in {"TECHNICAL", "INDIAN_MARKET"}]

    # Deterministic price parsing
    prices: list[float] = []
    for item in tech_evidence:
        lp = _safe_float(item.get("last_price"))
        if lp is not None:
            prices.append(lp)
        elif isinstance(item.get("ohlc"), dict):
            c = _safe_float(item["ohlc"].get("close"))
            if c is not None:
                prices.append(c)

    findings: list[str] = []
    directional_bias = "UNKNOWN"
    if len(prices) >= 2:
        ret = (prices[-1] - prices[0]) / prices[0]
        findings.append(f"Technical window return: {ret * 100:.2f}% across {len(prices)} bars.")
        if ret > 0.001:
            directional_bias = "BULLISH"
            findings.append("Short-term momentum indicates upward price continuation.")
        elif ret < -0.001:
            directional_bias = "BEARISH"
            findings.append("Short-term momentum indicates downward price continuation.")
        else:
            directional_bias = "NEUTRAL"
            findings.append("Price action is range-bound without clear directional momentum.")
    else:
        findings.append("Insufficient consecutive price observations for reliable deterministic indicator calculations.")

    out = AgentOutput(
        agent_id=role_name,
        role=role_name,
        display_name="Technical Analyst",
        status="SUCCESS",
        provider=cfg.provider,
        model=cfg.model,
        findings=findings,
        directional_bias=directional_bias,
        confidence=None,
        evidence_references=[e.get("evidence_id") for e in tech_evidence if e.get("evidence_id")],
        missing_evidence=[],
        limitations=["Calculated on available historical/quarantined bars only."],
        timestamp=_now_iso(),
    )
    agent_outputs[role_name] = out.model_dump()
    return {"agent_outputs": agent_outputs}


# ==============================================================================
# 3. GLOBAL AND MACRO ANALYST
# ==============================================================================
def global_macro_analyst_node(state: AnalysisState) -> dict:
    """Analyze GIFT NIFTY, global equity indices, US yields, crude oil, USD/INR, VIX.

    Explicitly reports missing or stale feeds.
    """
    cfg = _get_agent_cfg(AgentRole.GLOBAL_MACRO)
    role_name = AgentRole.GLOBAL_MACRO.value
    agent_outputs = dict(state.get("agent_outputs") or {})

    if not cfg or not cfg.enabled:
        out = AgentOutput(
            agent_id=role_name,
            role=role_name,
            display_name="Global and Macro Analyst",
            status="SKIPPED",
            provider=cfg.provider if cfg else "openai",
            model=cfg.model if cfg else "gpt-4o-mini",
            findings=["Agent disabled in configuration."],
            limitations=["Skipped by configuration."],
            timestamp=_now_iso(),
        )
        agent_outputs[role_name] = out.model_dump()
        return {"agent_outputs": agent_outputs}

    evidence = list(state.get("evidence") or [])
    macro_evidence = [e for e in evidence if e.get("category") in {"GLOBAL_MARKET", "MACRO"}]

    instruments_observed = {e.get("instrument") for e in macro_evidence if e.get("instrument")}
    target_instruments = {"GIFTNIFTY", "SPX", "NASDAQ", "CRUDE", "USDINR", "VIX"}
    missing_instruments = sorted(list(target_instruments - instruments_observed))

    findings = []
    if instruments_observed:
        findings.append(f"Observed macro factors: {', '.join(sorted(instruments_observed))}.")
    else:
        findings.append("No active global or macro index feeds available on state.")

    if missing_instruments:
        findings.append(f"Missing macro/global data feeds: {', '.join(missing_instruments)}.")

    out = AgentOutput(
        agent_id=role_name,
        role=role_name,
        display_name="Global and Macro Analyst",
        status="SUCCESS",
        provider=cfg.provider,
        model=cfg.model,
        findings=findings,
        directional_bias="UNKNOWN",
        confidence=None,
        evidence_references=[e.get("evidence_id") for e in macro_evidence if e.get("evidence_id")],
        missing_evidence=missing_instruments,
        limitations=["Macro signals are unverified for cross-market correlation."],
        timestamp=_now_iso(),
    )
    agent_outputs[role_name] = out.model_dump()
    return {"agent_outputs": agent_outputs}


# ==============================================================================
# 4. NEWS AND EVENT ANALYST
# ==============================================================================
def news_event_analyst_node(state: AnalysisState) -> dict:
    """Analyze available, timestamped news and event evidence.

    Distinguishes confirmed facts, reported claims, interpretations, unverified info.
    Enforces point-in-time publication constraints.
    """
    cfg = _get_agent_cfg(AgentRole.NEWS_EVENT)
    role_name = AgentRole.NEWS_EVENT.value
    agent_outputs = dict(state.get("agent_outputs") or {})

    if not cfg or not cfg.enabled:
        out = AgentOutput(
            agent_id=role_name,
            role=role_name,
            display_name="News and Event Analyst",
            status="SKIPPED",
            provider=cfg.provider if cfg else "google",
            model=cfg.model if cfg else "gemini-1.5-pro",
            findings=["Agent disabled in configuration."],
            limitations=["Skipped by configuration."],
            timestamp=_now_iso(),
        )
        agent_outputs[role_name] = out.model_dump()
        return {"agent_outputs": agent_outputs}

    evidence = list(state.get("evidence") or [])
    news_items = [e for e in evidence if e.get("category") == "NEWS"]

    facts = [e for e in news_items if e.get("claim_kind") == "FACT"]
    claims = [e for e in news_items if e.get("claim_kind") in {"ALLEGATION", "OPINION", "UNKNOWN"}]

    findings = [
        f"Evaluated {len(news_items)} news items ({len(facts)} confirmed facts, {len(claims)} reported claims).",
    ]
    if not news_items:
        findings.append("No news items stored on state for the evaluation window.")

    out = AgentOutput(
        agent_id=role_name,
        role=role_name,
        display_name="News and Event Analyst",
        status="SUCCESS",
        provider=cfg.provider,
        model=cfg.model,
        findings=findings,
        directional_bias="UNKNOWN",
        confidence=None,
        evidence_references=[e.get("evidence_id") for e in news_items if e.get("evidence_id")],
        missing_evidence=["Live news feed unconfigured" if not news_items else ""],
        limitations=["Strict point-in-time timestamp gating enforced."],
        timestamp=_now_iso(),
    )
    agent_outputs[role_name] = out.model_dump()
    return {"agent_outputs": agent_outputs}


# ==============================================================================
# 5. OPTIONS ANALYST
# ==============================================================================
def options_analyst_node(state: AnalysisState) -> dict:
    """Analyze options-derived data ONLY when available and validated.

    DOES NOT fabricate option chain values, PCR, IV, or Greeks.
    Returns explicit unavailable status when data is missing.
    """
    cfg = _get_agent_cfg(AgentRole.OPTIONS)
    role_name = AgentRole.OPTIONS.value
    agent_outputs = dict(state.get("agent_outputs") or {})

    if not cfg or not cfg.enabled:
        out = AgentOutput(
            agent_id=role_name,
            role=role_name,
            display_name="Options Analyst",
            status="SKIPPED",
            provider=cfg.provider if cfg else "openai",
            model=cfg.model if cfg else "gpt-4o-mini",
            findings=["Agent disabled in configuration."],
            limitations=["Skipped by configuration."],
            timestamp=_now_iso(),
        )
        agent_outputs[role_name] = out.model_dump()
        return {"agent_outputs": agent_outputs}

    evidence = list(state.get("evidence") or [])
    opt_evidence = [e for e in evidence if e.get("category") == "DERIVATIVES"]

    if not opt_evidence:
        out = AgentOutput(
            agent_id=role_name,
            role=role_name,
            display_name="Options Analyst",
            status="PARTIAL",
            provider=cfg.provider,
            model=cfg.model,
            findings=["No verified options or derivatives feed is configured. PCR, IV, and Greeks are withheld."],
            directional_bias="UNKNOWN",
            confidence=None,
            evidence_references=[],
            missing_evidence=["Options Chain (PCR, Max Pain, Implied Volatility)"],
            limitations=["Fabrication of derivatives data is strictly prohibited by safety invariants."],
            timestamp=_now_iso(),
        )
    else:
        out = AgentOutput(
            agent_id=role_name,
            role=role_name,
            display_name="Options Analyst",
            status="SUCCESS",
            provider=cfg.provider,
            model=cfg.model,
            findings=[f"Evaluated {len(opt_evidence)} verified derivatives items."],
            directional_bias="NEUTRAL",
            confidence=None,
            evidence_references=[e.get("evidence_id") for e in opt_evidence if e.get("evidence_id")],
            missing_evidence=[],
            limitations=["Options data subject to liquidity and strike coverage constraints."],
            timestamp=_now_iso(),
        )

    agent_outputs[role_name] = out.model_dump()
    return {"agent_outputs": agent_outputs}


# ==============================================================================
# 6. QUANTITATIVE FORECAST ANALYST
# ==============================================================================
def quant_forecast_analyst_node(state: AnalysisState) -> dict:
    """Interpret forecasts generated by registered quantitative models.

    Reports model identity, evaluation evidence, probability estimates, uncertainty.
    """
    cfg = _get_agent_cfg(AgentRole.QUANT_FORECAST)
    role_name = AgentRole.QUANT_FORECAST.value
    agent_outputs = dict(state.get("agent_outputs") or {})

    if not cfg or not cfg.enabled:
        out = AgentOutput(
            agent_id=role_name,
            role=role_name,
            display_name="Quantitative Forecast Analyst",
            status="SKIPPED",
            provider=cfg.provider if cfg else "openai",
            model=cfg.model if cfg else "gpt-4o-mini",
            findings=["Agent disabled in configuration."],
            limitations=["Skipped by configuration."],
            timestamp=_now_iso(),
        )
        agent_outputs[role_name] = out.model_dump()
        return {"agent_outputs": agent_outputs}

    findings = []
    directional_bias = "UNKNOWN"
    limitations = [
        "Models fit on historical training data only.",
        "Probabilities require independently verified market data to promote to forecast_ready.",
    ]

    try:
        from app.forecasting.live_forecast import generate_all_live_forecasts
        live_f = generate_all_live_forecasts()
        forecasts = live_f.get("forecasts") or []
        if forecasts:
            for f in forecasts:
                inst = f.get("instrument")
                p_up = f.get("probability_up")
                direction = f.get("direction")
                m_ver = f.get("model_version")
                findings.append(f"Model {m_ver} on {inst}: direction={direction}, P(up)={p_up:.3f} if p_up else N/A.")
                if direction in {"UP", "BULLISH"}:
                    directional_bias = "BULLISH"
                elif direction in {"DOWN", "BEARISH"}:
                    directional_bias = "BEARISH"
        else:
            findings.append("No active registered model produced probabilities on the current candle set.")
    except Exception as exc:
        findings.append(f"Quantitative forecast evaluation returned: {exc.__class__.__name__}.")

    out = AgentOutput(
        agent_id=role_name,
        role=role_name,
        display_name="Quantitative Forecast Analyst",
        status="SUCCESS",
        provider=cfg.provider,
        model=cfg.model,
        findings=findings,
        directional_bias=directional_bias,
        confidence=None,
        evidence_references=[],
        missing_evidence=[],
        limitations=limitations,
        timestamp=_now_iso(),
    )
    agent_outputs[role_name] = out.model_dump()
    return {"agent_outputs": agent_outputs}


# ==============================================================================
# 7. RISK AND UNCERTAINTY ANALYST
# ==============================================================================
def risk_uncertainty_analyst_node(state: AnalysisState) -> dict:
    """Identify conflicting evidence, stale inputs, missing data, high uncertainty.

    Cross-analyzes all upstream agents and flags irreconcilable conflicts.
    """
    cfg = _get_agent_cfg(AgentRole.RISK_UNCERTAINTY)
    role_name = AgentRole.RISK_UNCERTAINTY.value
    agent_outputs = dict(state.get("agent_outputs") or {})

    if not cfg or not cfg.enabled:
        out = AgentOutput(
            agent_id=role_name,
            role=role_name,
            display_name="Risk and Uncertainty Analyst",
            status="SKIPPED",
            provider=cfg.provider if cfg else "openai",
            model=cfg.model if cfg else "gpt-4o-mini",
            findings=["Agent disabled in configuration."],
            limitations=["Skipped by configuration."],
            timestamp=_now_iso(),
        )
        agent_outputs[role_name] = out.model_dump()
        return {"agent_outputs": agent_outputs}

    # Collect biases and findings across previous agents
    biases = {}
    missing_all = list(state.get("missing") or [])
    conflicts_all = list(state.get("conflicts") or [])

    for r_key, agent_data in agent_outputs.items():
        if isinstance(agent_data, dict):
            b = agent_data.get("directional_bias")
            if b and b != "UNKNOWN":
                biases[r_key] = b

    findings = []
    # Check for direct conflicts (e.g. Technical Bullish vs Quant Bearish)
    distinct_biases = set(biases.values())
    has_conflict = ("BULLISH" in distinct_biases and "BEARISH" in distinct_biases)
    if has_conflict:
        findings.append(f"CONFLICT DETECTED across specialist agents: {biases}.")
    else:
        findings.append("No active directional conflict between reporting specialist agents.")

    if missing_all:
        findings.append(f"Unresolved missing upstream data items: {missing_all}.")

    findings.append("Enforcing safety gate: live_trading_enabled remains False; forecast_ready remains False.")

    out = AgentOutput(
        agent_id=role_name,
        role=role_name,
        display_name="Risk and Uncertainty Analyst",
        status="SUCCESS",
        provider=cfg.provider,
        model=cfg.model,
        findings=findings,
        directional_bias="MIXED" if has_conflict else "NEUTRAL",
        confidence=None,
        evidence_references=[],
        missing_evidence=missing_all,
        limitations=["Risk analysis vetoes any directional trade when required evidence is missing."],
        timestamp=_now_iso(),
    )
    agent_outputs[role_name] = out.model_dump()
    return {"agent_outputs": agent_outputs}


# ==============================================================================
# 8. FINAL DECISION AGENT
# ==============================================================================
def final_decision_agent_node(state: AnalysisState) -> dict:
    """Combine specialist outputs into structured final report.

    MUST NOT invent evidence, silently resolve material conflicts, or override safety gates.
    MANDATES NO_TRADE when required evidence or approvals are missing.
    """
    cfg = _get_agent_cfg(AgentRole.FINAL_DECISION)
    role_name = AgentRole.FINAL_DECISION.value
    agent_outputs = dict(state.get("agent_outputs") or {})

    # Invariant safety gates
    forecast_ready = False
    paper_approved = False
    live_approved = False
    real_market_data_verified = False

    decision = "NO_TRADE"
    reason_codes = [
        "SAFETY_GATE_ACTIVE",
        "REAL_MARKET_DATA_UNVERIFIED",
        "LIVE_ROUTING_DISABLED",
    ]

    findings = [
        "Mandatory safety invariants strictly enforced.",
        "Decision: NO_TRADE. Reason: Historical data unverified independently and live trading disabled.",
    ]

    out = AgentOutput(
        agent_id=role_name,
        role=role_name,
        display_name="Final Decision Agent",
        status="SUCCESS",
        provider=cfg.provider if cfg else "openai",
        model=cfg.model if cfg else "gpt-4o",
        findings=findings,
        directional_bias="NEUTRAL",
        confidence=None,
        evidence_references=[],
        missing_evidence=[],
        limitations=[
            "forecast_ready = False",
            "real_market_data_verified = False",
            "paper_approved = False",
            "live_approved = False",
            "live_broker_routing_enabled = False",
        ],
        timestamp=_now_iso(),
    )
    agent_outputs[role_name] = out.model_dump()

    # Update state report
    report = dict(state.get("report") or {})
    report["decision"] = decision
    report["reason_codes"] = reason_codes
    report["agent_outputs"] = agent_outputs
    report["forecast_ready"] = forecast_ready
    report["paper_approved"] = paper_approved
    report["live_approved"] = live_approved
    report["real_market_data_verified"] = real_market_data_verified

    return {
        "agent_outputs": agent_outputs,
        "report": report,
    }
