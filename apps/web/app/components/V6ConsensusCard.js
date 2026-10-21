"use client";

import { useState } from "react";
import { csrfToken as csrf } from "./session";

const AGENT_ROLES = [
  { id: "market_data_analyst", legacyId: "market_data", name: "Market Data Specialist", baseWeight: 1.0, role: "Data Integrity & Lineage", icon: "📊" },
  { id: "technical_analyst", legacyId: "technical_analysis", name: "Technical Analyst", baseWeight: 2.0, role: "Swing & Indicator Regime", icon: "📈" },
  { id: "global_macro_analyst", legacyId: "global_macro", name: "Global Macro Analyst", baseWeight: 1.0, role: "Commodities, FX & Yields", icon: "🌐" },
  { id: "news_event_analyst", legacyId: "news_events", name: "News & Events Analyst", baseWeight: 1.0, role: "Headline Sentiment & Claims", icon: "📰" },
  { id: "options_analyst", legacyId: "options_analysis", name: "Options Analyst", baseWeight: 1.5, role: "Black-76, Greeks & PCR", icon: "⚡" },
  { id: "quant_forecast_analyst", legacyId: "quantitative_forecasting", name: "Quant Forecaster", baseWeight: 2.5, role: "HTF Resampling & Deadband", icon: "🔬" },
  { id: "risk_uncertainty_analyst", legacyId: "risk_uncertainty", name: "Risk & Uncertainty Analyst", baseWeight: 2.0, role: "Bayesian Epistemic Gating", icon: "🛡️" },
  { id: "final_decision_agent", legacyId: "final_decision", name: "Final Decision Arbiter", baseWeight: 3.0, role: "LangGraph Consensus Engine", icon: "⚖️" },
];

const VETO_DESCRIPTIONS = {
  EXCESSIVE_EPISTEMIC_UNCERTAINTY: "Composite epistemic uncertainty exceeds safety threshold (0.45)",
  REGIME_SIDEWAYS_CONSOLIDATION: "Market in sideways consolidation regime; directional trades suppressed",
  CORE_SPECIALIST_CONFLICT: "Core specialist directional conflict between Quant and Technical analysts",
  INSUFFICIENT_SPECIALIST_WEIGHT: "Combined active specialist weight below minimum quorum",
  REAL_MARKET_DATA_UNVERIFIED: "Historical dataset pending independent exchange Bhavcopy verification",
  SAFETY_GATE_ACTIVE: "Mandatory fail-closed safety gate active",
};

export default function V6ConsensusCard({ reportData, onRefresh }) {
  const [running, setRunning] = useState(false);
  const [activeTab, setActiveTab] = useState("matrix");
  const [error, setError] = useState("");
  const [localReport, setLocalReport] = useState(null);

  const effectiveReport = localReport || reportData || null;
  const rawConsensus = effectiveReport?.consensus || null;
  const rawAgentOutputs = effectiveReport?.agent_outputs || {};

  const dispersionVal = rawConsensus
    ? (rawConsensus.disagreement_index ?? rawConsensus.directional_dispersion ?? null)
    : null;
  const uncertaintyVal = rawConsensus
    ? (rawConsensus.epistemic_uncertainty ?? rawConsensus.composite_epistemic_uncertainty ?? null)
    : null;
  const thresholdVal = rawConsensus?.gating_threshold ?? 0.45;
  const finalBias = rawConsensus
    ? (rawConsensus.directional_recommendation || rawConsensus.final_bias || effectiveReport?.decision || "NEUTRAL")
    : "NOT_EVALUATED";

  const specialistScoreMap = {};
  if (Array.isArray(rawConsensus?.specialist_scores)) {
    for (const item of rawConsensus.specialist_scores) {
      if (item && item.role) {
        specialistScoreMap[item.role] = item;
      }
    }
  }

  const vetoList = (() => {
    if (Array.isArray(rawConsensus?.risk_vetoes)) {
      return rawConsensus.risk_vetoes;
    }
    const activeSet = new Set([
      ...(Array.isArray(rawConsensus?.vetoes) ? rawConsensus.vetoes : []),
      ...(Array.isArray(rawConsensus?.reason_codes) ? rawConsensus.reason_codes : []),
      ...(Array.isArray(effectiveReport?.reason_codes) ? effectiveReport.reason_codes : []),
    ]);
    return Object.entries(VETO_DESCRIPTIONS).map(([code, reason]) => ({
      code,
      triggered: activeSet.has(code),
      reason,
    }));
  })();

  async function triggerConsensusRun() {
    setRunning(true);
    setError("");
    try {
      const res = await fetch("/api/market-analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf() },
        body: JSON.stringify({
          instruments: ["NIFTY", "SENSEX"],
          horizon: "INTRADAY",
          include_news: true,
          include_macro: true,
          include_derivatives: true,
          include_forecast: true,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.message || `Analysis run failed with status ${res.status}`);
      }
      setLocalReport(data);
      if (onRefresh) onRefresh(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  const dispersionPct = dispersionVal !== null ? Math.round(dispersionVal * 100) : 0;
  const uncertaintyPct = uncertaintyVal !== null ? Math.round(uncertaintyVal * 100) : 0;
  const thresholdPct = Math.round(thresholdVal * 100);
  const triggeredVetoesCount = vetoList.filter((v) => v.triggered).length;
  const isGated = uncertaintyVal === null || uncertaintyVal >= thresholdVal || triggeredVetoesCount > 0 || effectiveReport?.decision === "NO_TRADE";

  return (
    <div className="v6-consensus-panel">
      {/* Header with Title and Control Buttons */}
      <div className="v6-panel-head">
        <div>
          <div className="v6-badge-row">
            <span className="v6-pill cyan">M38 CONSENSUS ENGINE</span>
            <span className="v6-pill indigo">BAYESIAN UNCERTAINTY GATING</span>
            <span className={`v6-pill ${isGated ? "amber" : "emerald"}`}>
              {isGated ? "⚡ GATED TO NO TRADE" : "PASS TO EXECUTION"}
            </span>
          </div>
          <h3 className="v6-panel-title">LangGraph Multi-Agent Dynamic Consensus</h3>
          <p className="v6-panel-sub">
            8 specialist agents weighted dynamically by confidence and data quality (W_i = w_i^base × c_i × q_i). Gated by directional dispersion and composite epistemic uncertainty.
          </p>
        </div>
        <button
          className="v6-btn primary"
          type="button"
          onClick={triggerConsensusRun}
          disabled={running}
        >
          {running ? "Synthesizing Consensus…" : "Run Consensus Cycle"}
        </button>
      </div>

      {error ? <div className="v6-alert error" role="alert">{error}</div> : null}

      {/* Mathematical Uncertainty & Dispersion Telemetry */}
      <div className="v6-telemetry-grid">
        <div className="v6-metric-card">
          <span className="v6-metric-label">Directional Dispersion Index (D)</span>
          <div className="v6-metric-val">{dispersionVal !== null ? dispersionVal.toFixed(3) : "—"}</div>
          <div className="v6-progress-track">
            <div className="v6-progress-fill cyan" style={{ width: `${dispersionPct}%` }} />
          </div>
          <span className="v6-metric-sub">Entropy across agent directional votes</span>
        </div>

        <div className="v6-metric-card">
          <span className="v6-metric-label">Composite Epistemic Uncertainty (U)</span>
          <div className={`v6-metric-val ${isGated ? "rose-text" : "emerald-text"}`}>
            {uncertaintyVal !== null ? uncertaintyVal.toFixed(3) : "—"}
          </div>
          <div className="v6-progress-track">
            <div
              className={`v6-progress-fill ${isGated ? "rose" : "emerald"}`}
              style={{ width: `${uncertaintyPct}%` }}
            />
          </div>
          <span className="v6-metric-sub">Safety Threshold Cutoff: {thresholdVal} ({thresholdPct}%)</span>
        </div>

        <div className="v6-metric-card">
          <span className="v6-metric-label">Consensus Directional Bias</span>
          <div className="v6-metric-val neutral-text">{finalBias}</div>
          <span className="v6-pill neutral">
            {rawConsensus ? `SCORE: ${Number(rawConsensus.consensus_score ?? 0).toFixed(2)}` : "AWAITING RUN"}
          </span>
          <span className="v6-metric-sub">Final Decision Arbiter Stance</span>
        </div>

        <div className="v6-metric-card">
          <span className="v6-metric-label">Active Risk Vetoes</span>
          <div className="v6-metric-val amber-text">
            {rawConsensus || effectiveReport ? `${triggeredVetoesCount} Triggered` : "—"}
          </div>
          <span className="v6-pill bad">{effectiveReport?.decision || "NO_TRADE"}</span>
          <span className="v6-metric-sub">{vetoList.length} Hard Safety Vetoes Evaluated</span>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="v6-tabs">
        <button
          type="button"
          className={`v6-tab-btn ${activeTab === "matrix" ? "active" : ""}`}
          onClick={() => setActiveTab("matrix")}
        >
          Specialist Voting Matrix (8 Agents)
        </button>
        <button
          type="button"
          className={`v6-tab-btn ${activeTab === "vetoes" ? "active" : ""}`}
          onClick={() => setActiveTab("vetoes")}
        >
          Deterministic Risk Vetoes ({vetoList.length} Gates)
        </button>
        <button
          type="button"
          className={`v6-tab-btn ${activeTab === "formula" ? "active" : ""}`}
          onClick={() => setActiveTab("formula")}
        >
          Mathematical Formulations
        </button>
      </div>

      {/* Tab 1: Specialist Voting Matrix */}
      {activeTab === "matrix" && (
        <div className="v6-agent-grid">
          {AGENT_ROLES.map((agent) => {
            const out = rawAgentOutputs[agent.id] || rawAgentOutputs[agent.legacyId] || {};
            const scoreEntry = specialistScoreMap[agent.id] || specialistScoreMap[agent.legacyId] || null;
            const dynWeight =
              scoreEntry?.effective_weight ??
              rawConsensus?.specialist_weights?.[agent.id] ??
              rawConsensus?.specialist_weights?.[agent.legacyId] ??
              null;
            const bias = out.directional_bias || "NOT_RUN";
            const biasClass = bias === "BULLISH" ? "emerald" : bias === "BEARISH" ? "rose" : "neutral";
            const execMode = out.execution_mode || (out.status ? "DETERMINISTIC_RULE" : "IDLE");

            return (
              <div key={agent.id} className="v6-agent-card">
                <div className="v6-agent-header">
                  <span className="v6-agent-icon">{agent.icon}</span>
                  <div>
                    <h4 className="v6-agent-name">{out.display_name || agent.name}</h4>
                    <span className="v6-agent-role">{agent.role}</span>
                  </div>
                  <span className={`v6-agent-bias ${biasClass}`}>{bias}</span>
                </div>

                <div className="v6-agent-details">
                  <div className="v6-agent-stat">
                    <span>Base Weight:</span>
                    <strong>{agent.baseWeight.toFixed(1)}</strong>
                  </div>
                  <div className="v6-agent-stat">
                    <span>Dynamic Weight:</span>
                    <strong className="cyan-text">{dynWeight !== null ? Number(dynWeight).toFixed(2) : "—"}</strong>
                  </div>
                  <div className="v6-agent-stat">
                    <span>Confidence:</span>
                    <strong>{out.confidence != null ? `${Math.round(out.confidence * 100)}%` : "N/A"}</strong>
                  </div>
                  <div className="v6-agent-stat">
                    <span>Latency:</span>
                    <span className="dim-text">{out.latency_ms != null ? `${out.latency_ms}ms` : "—"}</span>
                  </div>
                  <div className="v6-agent-stat">
                    <span>Execution Mode:</span>
                    <strong title={out.provider && out.model ? `${out.provider}/${out.model}` : ""}>{execMode}</strong>
                  </div>
                  <div className="v6-agent-stat">
                    <span>Engine / Model:</span>
                    <span className="dim-text">{out.provider ? `${out.provider}/${out.model}` : "—"}</span>
                  </div>
                </div>

                {out.findings && out.findings.length > 0 ? (
                  <p className="v6-agent-finding">{out.findings[0]}</p>
                ) : (
                  <p className="v6-agent-finding dim-text">Run Consensus Cycle to evaluate current specialist telemetry.</p>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Tab 2: Deterministic Risk Vetoes */}
      {activeTab === "vetoes" && (
        <div className="v6-veto-list">
          {vetoList.map((veto, idx) => (
            <div key={idx} className={`v6-veto-row ${veto.triggered ? "triggered" : "cleared"}`}>
              <div className="v6-veto-status-badge">
                {veto.triggered ? "⚠️ VETO ACTIVE" : "✓ CLEARED"}
              </div>
              <div className="v6-veto-content">
                <strong>{veto.code}</strong>
                <p>{veto.reason}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Tab 3: Mathematical Formulations */}
      {activeTab === "formula" && (
        <div className="v6-formula-panel">
          <h4>Consensus & Uncertainty Mathematical Framework</h4>
          <div className="v6-math-block">
            <strong>1. Dynamic Weight Adjustment:</strong>
            <code>{"W_i = w_i(base) × c_i × q_i"}</code>
            <p>where w_i(base) is the specialist architectural base weight, c_i is agent confidence, and q_i is data quality score.</p>
          </div>
          <div className="v6-math-block">
            <strong>2. Normalized Directional Dispersion Index (D):</strong>
            <code>{"D = 1 - (|Σ W_i · s_i|) / (Σ W_i) ∈ [0, 1]"}</code>
            <p>where s_i ∈ &#123;-1, 0, +1&#125; is the directional stance. D = 0 indicates unanimous consensus; D → 1 indicates maximum contradiction.</p>
          </div>
          <div className="v6-math-block">
            <strong>3. Composite Epistemic Uncertainty Gating:</strong>
            <code>{"U_total = α·D + β·(1 - c̄) + γ·(1 - q̄) ∈ [0, 1]"}</code>
            <p>Execution is deterministically gated to NO TRADE whenever U_total ≥ τ = 0.45 or when regime is choppy consolidation.</p>
          </div>
        </div>
      )}
    </div>
  );
}
