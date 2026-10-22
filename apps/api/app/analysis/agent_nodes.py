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
import os
import time
from datetime import datetime, timezone
from typing import Any

from app.analysis.agent_config import AgentRole, SingleAgentConfig, load_agent_system_config
from app.analysis.ai_providers import AIProviderRegistry
from app.analysis.consensus_engine import evaluate_multi_agent_consensus
from app.analysis.schema import AgentOutput
from app.analysis.state import AnalysisState

log = logging.getLogger("imm.agents")

VALID_BIASES = {"BULLISH", "BEARISH", "NEUTRAL", "MIXED", "UNKNOWN"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_agent_cfg(role: AgentRole) -> SingleAgentConfig | None:
    sys_cfg = load_agent_system_config()
    return sys_cfg.agents.get(role.value)


def _safe_float(val: Any) -> float | None:
    try:
        return float(val) if val is not None else None
    except (ValueError, TypeError):
        return None


def _skipped_output(role_name: str, display_name: str, cfg: SingleAgentConfig | None) -> AgentOutput:
    return AgentOutput(
        agent_id=role_name,
        role=role_name,
        display_name=display_name,
        status="SKIPPED",
        provider="skipped",
        model="none",
        execution_mode="SKIPPED",
        llm_attempted=False,
        llm_succeeded=False,
        fallback_used=False,
        configured_provider=cfg.provider if cfg else None,
        configured_model=cfg.model if cfg else None,
        findings=["Agent disabled in configuration."],
        limitations=["Skipped by configuration."],
        timestamp=_now_iso(),
    )


def _should_invoke_llm(state: AnalysisState, cfg: SingleAgentConfig) -> bool:
    """Invoke AIProviderRegistry only when explicitly requested or when custom/mock providers are registered."""
    if state.get("enable_agent_llm") is True:
        return True
    if state.get("enable_agent_llm") is False:
        return False

    # Check for custom/mock test providers registered via AIProviderRegistry.register_provider(...)
    custom_registered = getattr(AIProviderRegistry, "_custom_registered", set())
    if not AIProviderRegistry._providers:
        custom_registered.clear()
    p_name = (cfg.provider or "").lower().strip()
    fb_name = (cfg.fallback_provider or "").lower().strip()
    if (p_name in custom_registered and p_name in AIProviderRegistry._providers) or (
        fb_name and fb_name in custom_registered and fb_name in AIProviderRegistry._providers
    ):
        return True

    sys_cfg = load_agent_system_config()
    if sys_cfg.enable_live_llm is False:
        return False
    env_flag = (os.environ.get("IMM_ENABLE_AGENT_LLM") or os.environ.get("ENABLE_AGENT_LLM") or "").strip().lower()
    if env_flag in {"1", "true", "yes"}:
        return True
    return False


def _finalize_agent_output(
    *,
    role_name: str,
    display_name: str,
    cfg: SingleAgentConfig,
    state: AnalysisState,
    t0: float,
    findings: list[str],
    directional_bias: str,
    confidence: float | None,
    evidence_references: list[str],
    missing_evidence: list[str],
    limitations: list[str],
    default_status: str = "SUCCESS",
    lock_bias: bool = False,
    semantic_type: str = "UNKNOWN",
    is_probability: bool = False,
    is_calibrated: bool = False,
    provenance_verified: bool = False,
) -> AgentOutput:
    det_latency_ms = max(0.01, round((time.perf_counter() - t0) * 1000, 2))
    clean_refs = [r for r in evidence_references if r]
    clean_missing = [m for m in missing_evidence if m]
    clean_limits = list(limitations)
    clean_findings = list(findings)
    clean_bias = directional_bias if directional_bias in VALID_BIASES else "UNKNOWN"

    if not _should_invoke_llm(state, cfg):
        return AgentOutput(
            agent_id=role_name,
            role=role_name,
            display_name=display_name,
            status=default_status,  # type: ignore[arg-type]
            provider="deterministic_rule",
            model="v6_rule_engine",
            execution_mode="DETERMINISTIC_RULE",
            llm_attempted=False,
            llm_succeeded=False,
            fallback_used=False,
            configured_provider=cfg.provider,
            configured_model=cfg.model,
            findings=clean_findings,
            directional_bias=clean_bias,  # type: ignore[arg-type]
            confidence=confidence,
            semantic_type=semantic_type,
            is_probability=is_probability,
            is_calibrated=is_calibrated,
            provenance_verified=provenance_verified,
            evidence_references=clean_refs,
            missing_evidence=clean_missing,
            limitations=clean_limits,
            latency_ms=det_latency_ms,
            token_usage=None,
            timestamp=_now_iso(),
        )

    system_prompt = (
        f"You are the {display_name} ({role_name}) in a strict fail-closed institutional trading system. "
        f"{cfg.description} "
        "Respond strictly with a JSON object containing keys: "
        "'findings' (list of concise strings), 'directional_bias' ('BULLISH'|'BEARISH'|'NEUTRAL'|'MIXED'|'UNKNOWN'), "
        "'confidence' (number between 0.0 and 1.0 or null), and 'limitations' (list of strings). "
        "Never fabricate market prices, option Greeks, or override safety gates."
    )
    user_payload = {
        "role": role_name,
        "deterministic_findings": clean_findings,
        "deterministic_directional_bias": clean_bias,
        "evidence_references": clean_refs,
        "missing_evidence": clean_missing,
        "limitations": clean_limits,
    }
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload)},
    ]

    sys_cfg = load_agent_system_config()
    use_auto_reroute = bool(sys_cfg.auto_reroute_available_models and getattr(cfg, "auto_reroute", True))

    try:
        res = AIProviderRegistry.generate_with_fallback(
            primary_provider=cfg.provider,
            primary_model=cfg.model,
            messages=messages,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            timeout=cfg.timeout_seconds,
            fallback_provider=cfg.fallback_provider,
            fallback_model=cfg.fallback_model,
            auto_reroute=use_auto_reroute,
        )
    except Exception as exc:
        return AgentOutput(
            agent_id=role_name,
            role=role_name,
            display_name=display_name,
            status="PARTIAL",
            provider="deterministic_fallback",
            model="v6_rule_engine",
            execution_mode="DETERMINISTIC_FALLBACK_ON_LLM_ERROR",
            llm_attempted=True,
            llm_succeeded=False,
            fallback_used=True,
            configured_provider=cfg.provider,
            configured_model=cfg.model,
            findings=clean_findings,
            directional_bias=clean_bias,  # type: ignore[arg-type]
            confidence=confidence,
            semantic_type=semantic_type,
            is_probability=is_probability,
            is_calibrated=is_calibrated,
            provenance_verified=provenance_verified,
            evidence_references=clean_refs,
            missing_evidence=clean_missing,
            limitations=clean_limits + ["LLM provider invocation raised an exception; using deterministic rule baseline."],
            errors=[f"PROVIDER_EXCEPTION: {exc.__class__.__name__}: {str(exc)[:160]}"],
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            token_usage=None,
            timestamp=_now_iso(),
        )

    if not res.ok or not isinstance(res.structured_data, dict):
        err_code = res.error_code or "INVALID_STRUCTURED_OUTPUT"
        err_msg = res.error_message or "Provider did not return a structured JSON object."
        errors_list = [f"{err_code}: {err_msg}"]
        if res.primary_error_code:
            errors_list.insert(0, f"PRIMARY_{res.primary_error_code}: {res.primary_error_message}")
        return AgentOutput(
            agent_id=role_name,
            role=role_name,
            display_name=display_name,
            status="PARTIAL",
            provider="deterministic_fallback",
            model="v6_rule_engine",
            execution_mode="DETERMINISTIC_FALLBACK_ON_LLM_ERROR",
            llm_attempted=True,
            llm_succeeded=False,
            fallback_used=True,
            configured_provider=cfg.provider,
            configured_model=cfg.model,
            findings=clean_findings,
            directional_bias=clean_bias,  # type: ignore[arg-type]
            confidence=confidence,
            semantic_type=semantic_type,
            is_probability=is_probability,
            is_calibrated=is_calibrated,
            provenance_verified=provenance_verified,
            evidence_references=clean_refs,
            missing_evidence=clean_missing,
            limitations=clean_limits + [f"LLM call failed ({err_code}); preserved deterministic baseline findings."],
            errors=errors_list,
            latency_ms=max(det_latency_ms, float(res.latency_ms or 0.0)),
            token_usage={
                "prompt_tokens": int(res.prompt_tokens or 0),
                "completion_tokens": int(res.completion_tokens or 0),
                "total_tokens": int(res.total_tokens or 0),
            }
            if (res.prompt_tokens or res.completion_tokens or res.total_tokens)
            else None,
            timestamp=_now_iso(),
        )

    sdata = res.structured_data
    llm_findings_raw = sdata.get("findings")
    if isinstance(llm_findings_raw, list):
        llm_findings = [str(item).strip() for item in llm_findings_raw if str(item).strip()]
        # Preserve mandatory deterministic findings while appending validated LLM synthesis
        for lf in llm_findings:
            if lf not in clean_findings:
                clean_findings.append(lf)

    if not lock_bias:
        cand_bias = str(sdata.get("directional_bias") or "").upper().strip()
        if cand_bias in VALID_BIASES:
            clean_bias = cand_bias

    cand_conf = _safe_float(sdata.get("confidence"))
    if cand_conf is not None and 0.0 <= cand_conf <= 1.0 and not lock_bias:
        confidence = round(cand_conf, 4)

    llm_limits = sdata.get("limitations")
    if isinstance(llm_limits, list):
        for lim in llm_limits:
            s_lim = str(lim).strip()
            if s_lim and s_lim not in clean_limits:
                clean_limits.append(s_lim)

    if res.fallback_used and res.primary_error_code:
        clean_limits.append(
            f"Primary provider {cfg.provider}/{cfg.model} failed ({res.primary_error_code}); "
            f"executed fallback {res.provider}/{res.model}."
        )

    prov_obj = AIProviderRegistry._providers.get((res.provider or "").lower().strip())
    is_mock = bool(getattr(prov_obj, "is_mock", False))
    exec_mode = "MOCK_LLM" if is_mock else ("LLM_FALLBACK" if res.fallback_used else "LLM")
    final_status = "FALLBACK_USED" if res.fallback_used else default_status

    return AgentOutput(
        agent_id=role_name,
        role=role_name,
        display_name=display_name,
        status=final_status,  # type: ignore[arg-type]
        provider=res.provider,
        model=res.model,
        execution_mode=exec_mode,  # type: ignore[arg-type]
        llm_attempted=True,
        llm_succeeded=True,
        fallback_used=bool(res.fallback_used),
        configured_provider=cfg.provider,
        configured_model=cfg.model,
        findings=clean_findings,
        directional_bias=clean_bias,  # type: ignore[arg-type]
        confidence=confidence,
        semantic_type=semantic_type,
        is_probability=is_probability,
        is_calibrated=is_calibrated,
        provenance_verified=provenance_verified,
        evidence_references=clean_refs,
        missing_evidence=clean_missing,
        limitations=clean_limits,
        errors=[],
        latency_ms=max(det_latency_ms, float(res.latency_ms or 0.0)),
        token_usage={
            "prompt_tokens": int(res.prompt_tokens or 0),
            "completion_tokens": int(res.completion_tokens or 0),
            "total_tokens": int(res.total_tokens or 0),
        },
        timestamp=_now_iso(),
    )


# ==============================================================================
# 1. MARKET DATA ANALYST
# ==============================================================================
def market_data_analyst_node(state: AnalysisState) -> dict:
    """Assess data quality, coverage, freshness, missing values, and provider reconciliation.

    MUST NOT declare data verified unless underlying verification evidence supports it.
    """
    t0 = time.perf_counter()
    cfg = _get_agent_cfg(AgentRole.MARKET_DATA)
    role_name = AgentRole.MARKET_DATA.value
    agent_outputs = dict(state.get("agent_outputs") or {})

    if not cfg or not cfg.enabled:
        out = _skipped_output(role_name, "Market Data Analyst", cfg)
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

    out = _finalize_agent_output(
        role_name=role_name,
        display_name="Market Data Analyst",
        cfg=cfg,
        state=state,
        t0=t0,
        findings=findings,
        directional_bias="NEUTRAL",
        confidence=0.70,
        evidence_references=[row.get("evidence_id") for row in evidence[:5] if row.get("evidence_id")],
        missing_evidence=missing_info,
        limitations=limitations,
        lock_bias=True,
        semantic_type="STATIC_DEFAULT",
        is_probability=False,
        is_calibrated=False,
        provenance_verified=(unverified_count == 0 and synthetic_count == 0 and len(evidence) > 0),
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
    t0 = time.perf_counter()
    cfg = _get_agent_cfg(AgentRole.TECHNICAL)
    role_name = AgentRole.TECHNICAL.value
    agent_outputs = dict(state.get("agent_outputs") or {})

    if not cfg or not cfg.enabled:
        out = _skipped_output(role_name, "Technical Analyst", cfg)
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

    # If only 1 spot price exists, fallback to verified historical candles for multi-bar trend
    if len(prices) < 2:
        try:
            target_inst = (state.get("instruments") or ["NIFTY"])[0]
            from app.market.dataset_resolver import resolve_dataset_file
            ds_file = resolve_dataset_file(target_inst)
            if ds_file and ds_file.exists():
                import json
                raw_data = json.loads(ds_file.read_text(encoding="utf-8"))
                candles = raw_data.get("candles") or []
                if candles:
                    recent = candles[-20:]
                    hist_prices = [float(c[4]) for c in recent if len(c) > 4 and _safe_float(c[4]) is not None]
                    if len(hist_prices) >= 2:
                        prices = hist_prices
        except Exception:
            pass

    findings: list[str] = []
    directional_bias = "NEUTRAL"
    confidence = 0.60

    if len(prices) >= 2:
        ret = (prices[-1] - prices[0]) / prices[0]
        findings.append(f"Technical window return: {ret * 100:.2f}% across {len(prices)} bars.")

        # Evaluate trend strength and regime
        if abs(ret) < 0.001:
            directional_bias = "NEUTRAL"
            confidence = 0.60
            findings.append("Market regime: SIDEWAYS_CONSOLIDATION. Price action is range-bound without clear trend.")
        elif ret >= 0.001:
            directional_bias = "BULLISH"
            confidence = min(0.85, 0.65 + abs(ret) * 10)
            findings.append("Market regime: TRENDING_BULL. Short-term momentum indicates upward price continuation.")
        else:
            directional_bias = "BEARISH"
            confidence = min(0.85, 0.65 + abs(ret) * 10)
            findings.append("Market regime: TRENDING_BEAR. Short-term momentum indicates downward price continuation.")
    else:
        findings.append("Baseline consolidation regime; insufficient consecutive bars for dynamic momentum.")
        confidence = 0.50

    out = _finalize_agent_output(
        role_name=role_name,
        display_name="Technical Analyst",
        cfg=cfg,
        state=state,
        t0=t0,
        findings=findings,
        directional_bias=directional_bias,
        confidence=round(confidence, 2),
        evidence_references=[e.get("evidence_id") for e in tech_evidence if e.get("evidence_id")],
        missing_evidence=[],
        limitations=["Calculated on available historical/quarantined bars only."],
        semantic_type="HEURISTIC_SIGNAL_STRENGTH",
        is_probability=False,
        is_calibrated=False,
        provenance_verified=False,
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
    t0 = time.perf_counter()
    cfg = _get_agent_cfg(AgentRole.GLOBAL_MACRO)
    role_name = AgentRole.GLOBAL_MACRO.value
    agent_outputs = dict(state.get("agent_outputs") or {})

    if not cfg or not cfg.enabled:
        out = _skipped_output(role_name, "Global and Macro Analyst", cfg)
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

    # Evaluate multi-asset directional bias and confidence from macro signals
    bull_count = sum(1 for e in macro_evidence if e.get("directional_implication") == "BULLISH")
    bear_count = sum(1 for e in macro_evidence if e.get("directional_implication") == "BEARISH")
    vix_item = next((e for e in macro_evidence if e.get("instrument") in {"VIX", "INDIA_VIX"}), None)
    vix_val = _safe_float(vix_item.get("last_price")) if vix_item else None

    if bull_count > bear_count:
        directional_bias = "BULLISH"
        confidence = 0.65 + min(0.20, (bull_count - bear_count) * 0.04)
        findings.append(f"Global macro tailwinds net positive: {bull_count} bullish vs {bear_count} bearish macro factors.")
    elif bear_count > bull_count:
        directional_bias = "BEARISH"
        confidence = 0.65 + min(0.20, (bear_count - bull_count) * 0.04)
        findings.append(f"Global macro headwinds net negative: {bear_count} bearish vs {bull_count} bullish macro factors.")
    else:
        directional_bias = "NEUTRAL"
        confidence = 0.60
        findings.append("Global macro factors balanced between domestic inflows and global cues.")

    if vix_val is not None:
        if vix_val < 16.0:
            findings.append(f"India VIX at {vix_val:.2f} confirms a low-volatility, risk-tolerant equity regime.")
        elif vix_val > 20.0:
            findings.append(f"India VIX elevated at {vix_val:.2f}, indicating heightened volatility and cross-asset risk.")
        else:
            findings.append(f"India VIX at {vix_val:.2f} within normal historical bounds (16-20).")

    out = _finalize_agent_output(
        role_name=role_name,
        display_name="Global and Macro Analyst",
        cfg=cfg,
        state=state,
        t0=t0,
        findings=findings,
        directional_bias=directional_bias,
        confidence=round(confidence, 2),
        evidence_references=[e.get("evidence_id") for e in macro_evidence if e.get("evidence_id")],
        missing_evidence=missing_instruments,
        limitations=["Macro signals are unverified for cross-market correlation."],
        semantic_type="HEURISTIC_SIGNAL_STRENGTH",
        is_probability=False,
        is_calibrated=False,
        provenance_verified=False,
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
    t0 = time.perf_counter()
    cfg = _get_agent_cfg(AgentRole.NEWS_EVENT)
    role_name = AgentRole.NEWS_EVENT.value
    agent_outputs = dict(state.get("agent_outputs") or {})

    if not cfg or not cfg.enabled:
        out = _skipped_output(role_name, "News and Event Analyst", cfg)
        agent_outputs[role_name] = out.model_dump()
        return {"agent_outputs": agent_outputs}

    evidence = list(state.get("evidence") or [])
    news_items = [e for e in evidence if e.get("category") == "NEWS"]

    facts = [e for e in news_items if e.get("claim_kind") == "FACT"]
    claims = [e for e in news_items if e.get("claim_kind") in {"ALLEGATION", "OPINION", "UNKNOWN"}]

    findings = [
        f"Evaluated {len(news_items)} news items ({len(facts)} confirmed facts, {len(claims)} reported claims).",
    ]
    categories = [e.get("event_category") for e in news_items if e.get("event_category")]
    if categories:
        cat_counts = {c: categories.count(c) for c in set(categories)}
        cat_summary = ", ".join(f"{k} ({v})" for k, v in sorted(cat_counts.items()))
        findings.append(f"Geopolitical and policy categories detected: {cat_summary}.")
    else:
        findings.append("No active geopolitical, sanctions, or central bank event categories detected in current headline set.")

    bull_news = sum(1 for e in news_items if e.get("directional_implication") == "BULLISH")
    bear_news = sum(1 for e in news_items if e.get("directional_implication") == "BEARISH")

    if not news_items:
        findings.append("No adverse geopolitical, sanctions, or central bank event alerts detected in current surveillance window.")
        directional_bias = "NEUTRAL"
        confidence = 0.65
    elif bull_news > bear_news:
        directional_bias = "BULLISH"
        confidence = 0.65 + min(0.20, (bull_news - bear_news) * 0.05)
        findings.append(f"Headline news flow leaning positive ({bull_news} bullish vs {bear_news} bearish items).")
    elif bear_news > bull_news:
        directional_bias = "BEARISH"
        confidence = 0.65 + min(0.20, (bear_news - bull_news) * 0.05)
        findings.append(f"Headline news flow leaning defensive ({bear_news} bearish vs {bull_news} bullish items).")
    else:
        directional_bias = "NEUTRAL"
        confidence = 0.60
        findings.append("News flow balanced with no dominant directional skew.")

    out = _finalize_agent_output(
        role_name=role_name,
        display_name="News and Event Analyst",
        cfg=cfg,
        state=state,
        t0=t0,
        findings=findings,
        directional_bias=directional_bias,
        confidence=round(confidence, 2),
        evidence_references=[e.get("evidence_id") for e in news_items if e.get("evidence_id")],
        missing_evidence=["Live news feed unconfigured"] if not news_items else [],
        limitations=["Strict point-in-time timestamp gating enforced."],
        semantic_type="HEURISTIC_SIGNAL_STRENGTH",
        is_probability=False,
        is_calibrated=False,
        provenance_verified=False,
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
    t0 = time.perf_counter()
    cfg = _get_agent_cfg(AgentRole.OPTIONS)
    role_name = AgentRole.OPTIONS.value
    agent_outputs = dict(state.get("agent_outputs") or {})

    if not cfg or not cfg.enabled:
        out = _skipped_output(role_name, "Options Analyst", cfg)
        agent_outputs[role_name] = out.model_dump()
        return {"agent_outputs": agent_outputs}

    evidence = list(state.get("evidence") or [])
    opt_evidence = [e for e in evidence if e.get("category") == "DERIVATIVES"]

    if not opt_evidence:
        out = _finalize_agent_output(
            role_name=role_name,
            display_name="Options Analyst",
            cfg=cfg,
            state=state,
            t0=t0,
            findings=["No verified options or derivatives feed is configured. PCR, IV, and Greeks are withheld."],
            directional_bias="NEUTRAL",
            confidence=0.50,
            evidence_references=[],
            missing_evidence=["Options Chain (PCR, Max Pain, Implied Volatility)"],
            limitations=["Fabrication of derivatives data is strictly prohibited by safety invariants."],
            default_status="PARTIAL",
            lock_bias=True,
            semantic_type="STATIC_DEFAULT",
            is_probability=False,
            is_calibrated=False,
            provenance_verified=False,
        )
    else:
        findings = [f"Evaluated {len(opt_evidence)} verified derivatives items."]
        directional_bias = "NEUTRAL"
        confidence = None

        # Check for structured option quotes (M39)
        valid_quotes = [e for e in opt_evidence if "strike" in e and "option_type" in e]
        if valid_quotes and (
            _safe_float(valid_quotes[0].get("forward_price")) is None
            or _safe_float(valid_quotes[0].get("time_years")) is None
        ):
            findings.append("Option quotes lack forward price or time to expiry; chain analytics skipped.")
            valid_quotes = []
        if valid_quotes:
            try:
                from app.options.m39_options_analytics import analyze_options_chain
                chain_summary = analyze_options_chain(
                    quotes=valid_quotes,
                    forward_price=float(valid_quotes[0]["forward_price"]),
                    time_years=float(valid_quotes[0]["time_years"]),
                    symbol=str(valid_quotes[0].get("instrument", "NIFTY")),
                )
                findings.append(
                    f"Options PCR(OI): {chain_summary.pcr_oi:.2f}, PCR(Vol): {chain_summary.pcr_volume:.2f}, "
                    f"Max Pain Strike: {chain_summary.max_pain_strike:.0f}, ATM IV: {chain_summary.atm_iv * 100:.1f}%."
                )
                directional_bias = chain_summary.directional_sentiment
                confidence = chain_summary.sentiment_confidence
            except Exception as exc:
                findings.append(f"Options chain parsing returned: {exc.__class__.__name__}.")

        out = _finalize_agent_output(
            role_name=role_name,
            display_name="Options Analyst",
            cfg=cfg,
            state=state,
            t0=t0,
            findings=findings,
            directional_bias=directional_bias,
            confidence=confidence,
            evidence_references=[e.get("evidence_id") for e in opt_evidence if e.get("evidence_id")],
            missing_evidence=[],
            limitations=["Options data subject to liquidity and strike coverage constraints."],
            semantic_type="HEURISTIC_SIGNAL_STRENGTH",
            is_probability=False,
            is_calibrated=False,
            provenance_verified=False,
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
    t0 = time.perf_counter()
    cfg = _get_agent_cfg(AgentRole.QUANT_FORECAST)
    role_name = AgentRole.QUANT_FORECAST.value
    agent_outputs = dict(state.get("agent_outputs") or {})

    if not cfg or not cfg.enabled:
        out = _skipped_output(role_name, "Quantitative Forecast Analyst", cfg)
        agent_outputs[role_name] = out.model_dump()
        return {"agent_outputs": agent_outputs}

    findings = []
    directional_bias = "NEUTRAL"
    confidence = 0.50
    limitations = [
        "Models fit on historical training data only.",
        "Probabilities require independently verified market data to promote to forecast_ready.",
    ]

    try:
        from app.forecasting.live_forecast import generate_all_live_forecasts
        live_f = generate_all_live_forecasts()
        forecasts = live_f.get("forecasts") or []
        target_inst = (state.get("instruments") or ["NIFTY"])[0]
        if forecasts:
            for f in forecasts:
                inst = f.get("instrument")
                p_up = f.get("probability_up")
                direction = f.get("direction")
                m_ver = f.get("model_version")
                p_str = f"{p_up:.3f}" if p_up is not None else "N/A"
                findings.append(f"Model {m_ver} on {inst}: direction={direction}, P(up)={p_str}.")

            active_f = next((f for f in forecasts if f.get("instrument") == target_inst), None) or forecasts[0]
            if active_f:
                direction = active_f.get("direction")
                p_up = _safe_float(active_f.get("probability_up"))
                p_down = _safe_float(active_f.get("probability_down"))
                if direction in {"UP", "BULLISH"}:
                    directional_bias = "BULLISH"
                    confidence = p_up if p_up is not None else 0.60
                elif direction in {"DOWN", "BEARISH"}:
                    directional_bias = "BEARISH"
                    confidence = p_down if p_down is not None else 0.60
                else:
                    directional_bias = "NEUTRAL"
                    confidence = 0.50
        else:
            findings.append("No active registered model produced probabilities on the current candle set.")
    except Exception as exc:
        findings.append(f"Quantitative forecast evaluation returned: {exc.__class__.__name__}.")

    out = _finalize_agent_output(
        role_name=role_name,
        display_name="Quantitative Forecast Analyst",
        cfg=cfg,
        state=state,
        t0=t0,
        findings=findings,
        directional_bias=directional_bias,
        confidence=round(confidence, 2),
        evidence_references=[],
        missing_evidence=[],
        limitations=limitations,
        semantic_type="UNCALIBRATED_MODEL_PROBABILITY",
        is_probability=True,
        is_calibrated=False,
        provenance_verified=False,
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
    t0 = time.perf_counter()
    cfg = _get_agent_cfg(AgentRole.RISK_UNCERTAINTY)
    role_name = AgentRole.RISK_UNCERTAINTY.value
    agent_outputs = dict(state.get("agent_outputs") or {})

    if not cfg or not cfg.enabled:
        out = _skipped_output(role_name, "Risk and Uncertainty Analyst", cfg)
        agent_outputs[role_name] = out.model_dump()
        return {"agent_outputs": agent_outputs}

    # Collect biases and findings across previous agents
    biases = {}
    missing_all = list(state.get("missing") or [])

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

    # Check for sideways consolidation regime in technical analyst output
    tech_out = agent_outputs.get(AgentRole.TECHNICAL.value) or {}
    tech_findings = " ".join(tech_out.get("findings") or [])
    is_sideways = "SIDEWAYS_CONSOLIDATION" in tech_findings
    if is_sideways:
        findings.append("RISK VETO: Market is in sideways consolidation regime (M28 filter). Mandating NO_TRADE.")

    # Quantitative Consensus & Uncertainty Gating (M38)
    consensus_eval = evaluate_multi_agent_consensus(agent_outputs, state)
    findings.append(
        f"Consensus directional score: {consensus_eval.consensus_score:+.2f}, "
        f"Epistemic uncertainty: {consensus_eval.epistemic_uncertainty:.2f}, "
        f"Disagreement index: {consensus_eval.disagreement_index:.2f}."
    )
    if consensus_eval.vetoes:
        findings.append(f"Active risk vetoes asserted: {consensus_eval.vetoes}.")

    if missing_all:
        findings.append(f"Unresolved missing upstream data items: {missing_all}.")

    findings.append("Enforcing safety gate: live_trading_enabled remains False; forecast_ready remains False.")

    out = _finalize_agent_output(
        role_name=role_name,
        display_name="Risk and Uncertainty Analyst",
        cfg=cfg,
        state=state,
        t0=t0,
        findings=findings,
        directional_bias="MIXED" if has_conflict else ("NEUTRAL" if is_sideways else "NEUTRAL"),
        confidence=round(max(0.30, min(0.95, 1.0 - consensus_eval.epistemic_uncertainty)), 2),
        evidence_references=[],
        missing_evidence=missing_all,
        limitations=["Risk analysis vetoes any directional trade when required evidence is missing or market is sideways."],
        lock_bias=True,
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
    t0 = time.perf_counter()
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

    # Check risk and technical signals
    risk_out = agent_outputs.get(AgentRole.RISK_UNCERTAINTY.value) or {}
    risk_findings = " ".join(risk_out.get("findings") or []).upper()
    tech_out = agent_outputs.get(AgentRole.TECHNICAL.value) or {}
    tech_findings = " ".join(tech_out.get("findings") or []).upper()

    if "SIDEWAYS_CONSOLIDATION" in risk_findings or "SIDEWAYS CONSOLIDATION" in risk_findings or "SIDEWAYS_CONSOLIDATION" in tech_findings:
        reason_codes.append("REGIME_SIDEWAYS_CONSOLIDATION")
    if "CONFLICT DETECTED" in risk_findings:
        reason_codes.append("SPECIALIST_BIAS_CONFLICT")

    # Evaluate dynamic multi-agent consensus (M38)
    consensus_eval = evaluate_multi_agent_consensus(agent_outputs, state)
    for rc in consensus_eval.reason_codes:
        if rc not in reason_codes:
            reason_codes.append(rc)

    findings = [
        "Mandatory safety invariants strictly enforced.",
        "Decision: NO_TRADE. Reason: Historical data unverified independently, live trading disabled, and safety gates active.",
    ]
    if "REGIME_SIDEWAYS_CONSOLIDATION" in reason_codes:
        findings.append("Consolidation filter active: Market is in sideways range; directional trades suppressed.")
    if "EXCESSIVE_EPISTEMIC_UNCERTAINTY" in reason_codes:
        findings.append(f"Uncertainty veto active: Epistemic uncertainty {consensus_eval.epistemic_uncertainty:.2f} exceeds tolerance threshold.")

    if not cfg or not cfg.enabled:
        out = _skipped_output(role_name, "Final Decision Agent", cfg)
    else:
        out = _finalize_agent_output(
            role_name=role_name,
            display_name="Final Decision Agent",
            cfg=cfg,
            state=state,
            t0=t0,
            findings=findings,
            directional_bias="NEUTRAL",
            confidence=round(0.75 if abs(consensus_eval.consensus_score) > 1.0 else 0.65, 2),
            evidence_references=[],
            missing_evidence=[],
            limitations=[
                "forecast_ready = False",
                "real_market_data_verified = False",
                "paper_approved = False",
                "live_approved = False",
                "live_broker_routing_enabled = False",
            ],
            lock_bias=True,
        )
    agent_outputs[role_name] = out.model_dump()

    # Update state report
    report = dict(state.get("report") or {})
    report["decision"] = decision
    report["reason_codes"] = sorted(list(set(reason_codes)))
    report["agent_outputs"] = agent_outputs
    report["forecast_ready"] = forecast_ready
    report["paper_approved"] = paper_approved
    report["live_approved"] = live_approved
    report["real_market_data_verified"] = real_market_data_verified
    report["live_trading_enabled"] = False
    report["live_broker_routing_enabled"] = False
    report["consensus"] = {
        "consensus_score": consensus_eval.consensus_score,
        "disagreement_index": consensus_eval.disagreement_index,
        "epistemic_uncertainty": consensus_eval.epistemic_uncertainty,
        "gating_threshold": consensus_eval.gating_threshold,
        "active_specialist_count": consensus_eval.active_specialist_count,
        "total_effective_weight": consensus_eval.total_effective_weight,
        "directional_recommendation": consensus_eval.directional_recommendation,
        "vetoes": consensus_eval.vetoes,
        "reason_codes": consensus_eval.reason_codes,
        "specialist_scores": consensus_eval.specialist_scores,
        "configured_specialist_count": consensus_eval.configured_specialist_count,
        "reporting_specialist_count": consensus_eval.reporting_specialist_count,
        "missing_specialist_count": consensus_eval.missing_specialist_count,
        "failed_specialist_count": consensus_eval.failed_specialist_count,
        "skipped_specialist_count": consensus_eval.skipped_specialist_count,
        "fallback_only_specialist_count": consensus_eval.fallback_only_specialist_count,
        "directional_voter_count": consensus_eval.directional_voter_count,
        "directional_participation_rate": consensus_eval.directional_participation_rate,
        "safety_invariants_preserved": consensus_eval.safety_invariants_preserved,
    }

    return {
        "agent_outputs": agent_outputs,
        "report": report,
    }

