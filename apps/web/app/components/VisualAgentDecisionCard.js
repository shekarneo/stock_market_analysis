"use client";

import { useEffect, useState } from "react";
import { useMarketData } from "./MarketDataContext";
import { csrfToken } from "./session";

// How an agent's track record set its consensus weight (consensus specialist_scores[].evidence_status)
const TRACK_RECORD_LABEL = {
  MEASURED_HISTORY: { text: "Track record: replayed history", bg: "rgba(16, 185, 129, 0.12)", color: "#34d399" },
  PROVEN_FORWARD: { text: "Track record: PROVEN", bg: "rgba(16, 185, 129, 0.18)", color: "#34d399" },
  UNMEASURED: { text: "Track record: none yet · 10% weight", bg: "rgba(245, 158, 11, 0.12)", color: "#fbbf24" },
  NO_EDGE_YET: { text: "Track record: no edge · no weight", bg: "rgba(244, 63, 94, 0.12)", color: "#fb7185" },
  WORSE_THAN_CHANCE: { text: "Track record: worse than chance · no weight", bg: "rgba(244, 63, 94, 0.15)", color: "#fb7185" },
};

// Distinctly catalog 8 implemented LangGraph agents vs 4 research/catalog reference desks
const AGENT_CATALOG = [
  // 8 Implemented LangGraph Specialist Agents
  { id: "news_events", legacyKey: "news_event_analyst", name: "News Sentiment", icon: "📰", role: "Headline tone for the instrument", isImplemented: true },
  { id: "global_macro", legacyKey: "global_macro_analyst", name: "Global Macro", icon: "🌐", role: "FII/DII flows, yields, FX (fresh releases only)", isImplemented: true },
  { id: "order_flow", legacyKey: "market_data_analyst", name: "Data Quality", icon: "📊", role: "Feed coverage & provenance", isImplemented: true },
  { id: "options_greeks", legacyKey: "options_analyst", name: "Options & Greeks", icon: "⚡", role: "Option chain (when a verified feed exists)", isImplemented: true },
  { id: "trend_momentum", legacyKey: "technical_analyst", name: "Trend & Momentum", icon: "📈", role: "Move vs previous close (scored on 6y history)", isImplemented: true },
  { id: "quant_forecast", legacyKey: "quant_forecast_analyst", name: "Quant ML Model", icon: "🔬", role: "Registered 15m model (if any)", isImplemented: true },
  { id: "bayesian_gate", legacyKey: "risk_uncertainty_analyst", name: "Risk & Uncertainty", icon: "🛡️", role: "Disagreement gate (0.45 cutoff)", isImplemented: true },
  { id: "final_arbiter", legacyKey: "final_decision_agent", name: "Final Decision", icon: "⚖️", role: "Weighted consensus + safety vetoes", isImplemented: true },

  // 4 Research & Catalog Reference Desks (No standalone LangGraph agent node)
  { id: "commodities", legacyKey: "crude_cross_asset", name: "Intermarket & MCX", icon: "🛢️", role: "Crude Oil & Gold Flows", isImplemented: false, catalogType: "Catalog Reference" },
  { id: "mean_reversion", legacyKey: "mean_reversion", name: "Mean Reversion", icon: "🔄", role: "RSI & Bollinger Z-Score", isImplemented: false, catalogType: "Catalog Reference" },
  { id: "htf_resampling", legacyKey: "htf_resampling", name: "HTF Resampling", icon: "⏱", role: "Multi-Timeframe Alignment", isImplemented: false, catalogType: "Catalog Reference" },
  { id: "expected_payoff", legacyKey: "expected_payoff", name: "Expected Net Payoff", icon: "💰", role: "2.0 bps Friction Ref", isImplemented: false, catalogType: "Payoff Model" },
];

export default function VisualAgentDecisionCard({ onExpandDetailed }) {
  const { selectedInstrument, selectInstrument, spots, selectedModel } = useMarketData();
  const [instrument, setInstrument] = useState(selectedInstrument || "NIFTY");
  const [report, setReport] = useState(null);
  const [liveForecast, setLiveForecast] = useState(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [viewMode, setViewMode] = useState("grid"); // "grid" | "compact"

  useEffect(() => {
    if (selectedInstrument && selectedInstrument !== instrument) {
      setInstrument(selectedInstrument);
    }
  }, [selectedInstrument]);

  // Sync live statistical forecast for active instrument and chosen model
  useEffect(() => {
    let active = true;
    async function fetchForecast() {
      try {
        const query = new URLSearchParams({
          instrument,
          model: selectedModel || "champion",
        });
        const res = await fetch(`/api/forecasting/live-trend-chart?${query.toString()}`);
        if (res.ok) {
          const data = await res.json();
          if (active && data.ok) {
            setLiveForecast(data);
          }
        }
      } catch {
        // graceful fallback to market analysis report
      }
    }
    fetchForecast();
    return () => {
      active = false;
    };
  }, [instrument, selectedModel]);

  // Execute on-demand live multi-agent analysis and refresh model prediction
  async function runLiveAnalysis() {
    setRunning(true);
    setError("");
    try {
      const [resAnalysis, resChart] = await Promise.all([
        fetch("/api/market-analysis", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
          body: JSON.stringify({
            instruments: [instrument],
            horizon: "INTRADAY",
            include_news: true,
            include_macro: true,
            include_derivatives: true,
            include_forecast: true,
          }),
        }),
        fetch(`/api/forecasting/live-trend-chart?instrument=${encodeURIComponent(instrument)}&model=${encodeURIComponent(selectedModel || "champion")}`).catch(() => null),
      ]);
      const data = await resAnalysis.json().catch(() => ({}));
      if (!resAnalysis.ok) {
        throw new Error(data.message || `Analysis failed (${resAnalysis.status})`);
      }
      setReport(data);
      if (resChart && resChart.ok) {
        const chartData = await resChart.json().catch(() => null);
        if (chartData?.ok) {
          setLiveForecast(chartData);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  // Analysis Lifecycle & Integrity States
  const isReportAvailable = Boolean(report);
  const decision = isReportAvailable ? (report.decision || "STAND_ASIDE") : "NOT_RUN";
  const consensus = report?.consensus || null;
  const agentOutputs = report?.agent_outputs || {};

  const activeVetoes = Array.isArray(consensus?.vetoes) ? consensus.vetoes : [];
  const hasActiveVetoes = activeVetoes.length > 0;

  const isBuy = isReportAvailable && !hasActiveVetoes && decision !== "NO_TRADE" && decision !== "STAND_ASIDE" && (decision.includes("BUY") || decision === "BULLISH");
  const isSell = isReportAvailable && !hasActiveVetoes && decision !== "NO_TRADE" && decision !== "STAND_ASIDE" && (decision.includes("SELL") || decision === "BEARISH");
  const isStandAside = isReportAvailable && !isBuy && !isSell;

  const decisionColor = !isReportAvailable
    ? "#94a3b8"
    : (isBuy ? "#10b981" : isSell ? "#f43f5e" : "#f59e0b");
  const decisionBg = !isReportAvailable
    ? "rgba(148, 163, 184, 0.08)"
    : (isBuy ? "rgba(16, 185, 129, 0.12)" : isSell ? "rgba(244, 63, 94, 0.12)" : "rgba(245, 158, 11, 0.12)");
  const decisionBorder = !isReportAvailable
    ? "rgba(148, 163, 184, 0.2)"
    : (isBuy ? "rgba(16, 185, 129, 0.3)" : isSell ? "rgba(244, 63, 94, 0.3)" : "rgba(245, 158, 11, 0.3)");

  // Consensus score: strictly [-1.0, +1.0] from backend consensus_engine
  const rawScore = typeof consensus?.consensus_score === "number" ? consensus.consensus_score : null;
  const hasScore = rawScore !== null;
  const scoreVal = hasScore ? rawScore : 0.0;
  // Map [-1.0, +1.0] to [0%, 100%]
  const scorePct = hasScore ? Math.max(0, Math.min(100, ((scoreVal + 1.0) / 2.0) * 100)) : 50;

  // Epistemic Uncertainty (0.0 to 1.0) with genuine backend veto threshold (0.45)
  const thresholdVal = typeof consensus?.gating_threshold === "number" ? consensus.gating_threshold : 0.45;
  const rawUncertainty = typeof consensus?.epistemic_uncertainty === "number" ? consensus.epistemic_uncertainty : null;
  const hasUncertainty = rawUncertainty !== null;
  const uncertaintyVal = hasUncertainty ? rawUncertainty : null;
  const isUncertaintyVetoed = hasUncertainty && (uncertaintyVal >= thresholdVal || activeVetoes.includes("EXCESSIVE_EPISTEMIC_UNCERTAINTY"));

  // Quorum & Directional Participation Metrics
  const configuredCount = typeof consensus?.configured_specialist_count === "number" ? consensus.configured_specialist_count : 6;
  const reportingCount = typeof consensus?.reporting_specialist_count === "number"
    ? consensus.reporting_specialist_count
    : (typeof consensus?.active_specialist_count === "number" ? consensus.active_specialist_count : 0);
  const directionalVoters = typeof consensus?.directional_voter_count === "number" ? consensus.directional_voter_count : 0;
  const participationRate = typeof consensus?.directional_participation_rate === "number" ? consensus.directional_participation_rate : 0.0;
  const missingCount = typeof consensus?.missing_specialist_count === "number" ? consensus.missing_specialist_count : 0;
  const failedCount = typeof consensus?.failed_specialist_count === "number" ? consensus.failed_specialist_count : 0;
  const fallbackCount = typeof consensus?.fallback_only_specialist_count === "number" ? consensus.fallback_only_specialist_count : 0;
  const totalWeight = typeof consensus?.total_effective_weight === "number" ? consensus.total_effective_weight : null;

  // Execution Gating Status: Strictly prevent false "Active Execution" claims
  let executionBadgeText = "⏸ Awaiting Analysis Cycle";
  let executionBadgeBg = "rgba(148, 163, 184, 0.1)";
  let executionBadgeColor = "#94a3b8";

  if (isReportAvailable) {
    if (decision === "NO_TRADE" || decision === "STAND_ASIDE" || isUncertaintyVetoed || hasActiveVetoes) {
      executionBadgeText = "🔒 Deadband / Safety Gated (NO TRADE)";
      executionBadgeBg = "rgba(245, 158, 11, 0.15)";
      executionBadgeColor = "#fbbf24";
    } else {
      // Live broker routing is hard locked to blocked state across the repository
      executionBadgeText = "🔒 Live Routing Disabled (Paper Only)";
      executionBadgeBg = "rgba(56, 189, 248, 0.15)";
      executionBadgeColor = "#38bdf8";
    }
  }

  // Quant Confluence probability extraction
  const rawProbObj = report?.intelligence?.forecast?.probabilities?.[instrument];
  const reportProbUp = typeof rawProbObj === "number" ? rawProbObj : (typeof rawProbObj?.up === "number" ? rawProbObj.up : null);
  const liveProb = typeof liveForecast?.calibrated_probability === "number" ? liveForecast.calibrated_probability : null;
  const rawProb = isReportAvailable ? (reportProbUp ?? liveProb ?? null) : (liveProb ?? null);
  const hasMlProb = typeof rawProb === "number" && !isNaN(rawProb);
  const mlProb = hasMlProb ? rawProb : null;
  const mlProbUp = hasMlProb ? Math.round(mlProb * 100) : null;
  const activeModelDisplay = (liveForecast?.model_name || selectedModel || "CHAMPION").toUpperCase();

  // Agent Count breakdown
  const implementedCount = AGENT_CATALOG.filter((a) => a.isImplemented).length; // 8
  const catalogCount = AGENT_CATALOG.filter((a) => !a.isImplemented).length; // 4
  const executedCount = isReportAvailable
    ? AGENT_CATALOG.filter((a) => {
        if (!a.isImplemented) return false;
        const out = agentOutputs[a.id] || agentOutputs[a.legacyKey];
        return out && out.status && out.status !== "SKIPPED" && out.status !== "FAILED";
      }).length
    : 0;

  return (
    <section
      aria-labelledby="agent-visual-heading"
      style={{
        background: "var(--card-subtle, #131c31)",
        border: "1px solid var(--line, #334155)",
        borderRadius: "12px",
        padding: "20px",
        marginBottom: "20px",
      }}
    >
      {/* Top Header & Execution Bar */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px", marginBottom: "16px" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
            <span style={{ fontSize: "0.72rem", fontWeight: 700, padding: "2px 8px", borderRadius: "4px", background: "rgba(56, 189, 248, 0.15)", color: "#38bdf8", border: "1px solid rgba(56, 189, 248, 0.3)" }}>
              🤖 8 SPECIALIST AGENTS · 4 RESEARCH DESKS
            </span>
            <span style={{ fontSize: "0.72rem", fontWeight: 700, padding: "2px 8px", borderRadius: "4px", background: "rgba(16, 185, 129, 0.15)", color: "#34d399", border: "1px solid rgba(16, 185, 129, 0.3)" }}>
              DETERMINISTIC CONSENSUS
            </span>
            <span style={{ fontSize: "0.72rem", color: "var(--sub, #94a3b8)" }}>
              Active Underlying: <strong style={{ color: "var(--ink, #fff)" }}>{instrument}</strong>
            </span>
            {isReportAvailable && report?.created_at && (
              <span
                style={{
                  fontSize: "0.72rem",
                  color: "#38bdf8",
                  background: "rgba(56, 189, 248, 0.1)",
                  padding: "2px 8px",
                  borderRadius: "4px",
                  border: "1px solid rgba(56, 189, 248, 0.25)",
                }}
                title={`Cycle ID: ${report.analysis_id || "N/A"}`}
              >
                🕒 Cycle: {report.analysis_id ? `${report.analysis_id.slice(0, 8)} · ` : ""}{new Date(report.created_at).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit" })} IST
              </span>
            )}
          </div>
          <h2 id="agent-visual-heading" style={{ margin: 0, fontSize: "1.2rem", fontWeight: 800, color: "var(--ink, #fff)" }}>
            Visual Multi-Agent Consensus &amp; Trade Signal
          </h2>
        </div>

        <div style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" }}>
          {/* Instrument Selector Chips */}
          <div style={{ display: "flex", gap: "4px", background: "rgba(0,0,0,0.3)", padding: "3px", borderRadius: "8px", border: "1px solid var(--line, #334155)" }}>
            {["NIFTY", "SENSEX", "CRUDEOILMINI"].map((sym) => (
              <button
                key={sym}
                type="button"
                onClick={() => {
                  setInstrument(sym);
                  if (selectInstrument) selectInstrument(sym);
                }}
                style={{
                  padding: "4px 10px",
                  borderRadius: "6px",
                  border: "none",
                  background: instrument === sym ? "var(--accent, #38bdf8)" : "transparent",
                  color: instrument === sym ? "#0f172a" : "var(--sub, #94a3b8)",
                  fontWeight: instrument === sym ? 700 : 500,
                  fontSize: "0.75rem",
                  cursor: "pointer",
                }}
              >
                {sym === "CRUDEOILMINI" ? "CRUDE" : sym}
              </button>
            ))}
          </div>

          {/* Run Analysis Action Button */}
          <button
            type="button"
            onClick={runLiveAnalysis}
            disabled={running}
            style={{
              padding: "7px 16px",
              borderRadius: "8px",
              border: "1px solid rgba(56, 189, 248, 0.4)",
              background: running ? "rgba(56, 189, 248, 0.2)" : "linear-gradient(135deg, #0284c7 0%, #0369a1 100%)",
              color: "#fff",
              fontWeight: 700,
              fontSize: "0.82rem",
              cursor: running ? "wait" : "pointer",
              boxShadow: "0 2px 8px rgba(2, 132, 199, 0.3)",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
          >
            {running ? (
              <>
                <span className="spinner" style={{ display: "inline-block", width: "12px", height: "12px", border: "2px solid #fff", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
                <span>Synthesizing Specialists…</span>
              </>
            ) : (
              <>
                <span>⚡ Run Live Analysis</span>
              </>
            )}
          </button>
          {onExpandDetailed && (
            <button
              type="button"
              onClick={onExpandDetailed}
              style={{
                padding: "7px 14px",
                borderRadius: "8px",
                border: "1px solid rgba(56, 189, 248, 0.35)",
                background: "rgba(56, 189, 248, 0.12)",
                color: "#38bdf8",
                fontWeight: 650,
                fontSize: "0.8rem",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: "6px",
              }}
              title="Expand to detailed multi-agent analysis desk with full institutional dossier"
            >
              <span>🔬 Detailed Desk ▾</span>
            </button>
          )}
        </div>
      </div>

      {error && (
        <div style={{ padding: "8px 12px", background: "rgba(244, 63, 94, 0.15)", border: "1px solid rgba(244, 63, 94, 0.3)", borderRadius: "8px", color: "#fb7185", fontSize: "0.82rem", marginBottom: "14px" }}>
          ⚠️ {error}
        </div>
      )}

      {/* Visual Verdict Banner & Key Telemetry Deck */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: "12px",
          marginBottom: "12px",
        }}
      >
        {/* Card 1: Core Trade Decision */}
        <div
          style={{
            background: decisionBg,
            border: `1px solid ${decisionBorder}`,
            borderRadius: "10px",
            padding: "14px",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
          }}
        >
          <span style={{ fontSize: "0.72rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--sub, #94a3b8)" }}>
            Institutional Desk Verdict
          </span>
          <div style={{ margin: "6px 0" }}>
            <span
              style={{
                fontSize: "1.25rem",
                fontWeight: 900,
                color: decisionColor,
                letterSpacing: "-0.02em",
                display: "inline-block",
              }}
            >
              {!isReportAvailable
                ? "AWAITING ANALYSIS (NO TRADE)"
                : (decision === "NO_TRADE" || decision === "STAND_ASIDE" || hasActiveVetoes ? "STAND ASIDE (NO TRADE)" : decision)}
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span style={{ fontSize: "0.72rem", padding: "3px 8px", borderRadius: "4px", background: executionBadgeBg, color: executionBadgeColor, fontWeight: 650 }}>
              {executionBadgeText}
            </span>
          </div>
        </div>

        {/* Card 2: Consensus Spectrum Meter (-1.0 to +1.0) */}
        <div
          style={{
            background: "rgba(18, 26, 43, 0.65)",
            border: "1px solid rgba(255, 255, 255, 0.08)",
            borderRadius: "10px",
            padding: "14px",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <span style={{ fontSize: "0.72rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--sub, #94a3b8)" }}>
              Consensus Score
            </span>
            <span style={{ fontSize: "0.88rem", fontWeight: 800, color: !hasScore ? "#94a3b8" : (scoreVal > 0 ? "#10b981" : scoreVal < 0 ? "#f43f5e" : "#fbbf24") }}>
              {!hasScore
                ? "— Not Run"
                : (scoreVal > 0 ? `+${scoreVal.toFixed(2)} Bullish` : scoreVal < 0 ? `${scoreVal.toFixed(2)} Bearish` : "0.00 Neutral")}
            </span>
          </div>

          {/* Visual Spectrum Bar */}
          <div style={{ margin: "10px 0 6px", position: "relative" }}>
            <div
              style={{
                height: "8px",
                borderRadius: "4px",
                background: hasScore
                  ? "linear-gradient(to right, #f43f5e 0%, #f59e0b 50%, #10b981 100%)"
                  : "rgba(255, 255, 255, 0.08)",
                width: "100%",
                opacity: hasScore ? 0.85 : 0.4,
              }}
            />
            {/* Pointer Indicator */}
            {hasScore ? (
              <div
                style={{
                  position: "absolute",
                  top: "-4px",
                  left: `${scorePct}%`,
                  transform: "translateX(-50%)",
                  width: "16px",
                  height: "16px",
                  borderRadius: "50%",
                  background: "#fff",
                  boxShadow: "0 0 6px rgba(255,255,255,0.9), 0 2px 4px rgba(0,0,0,0.5)",
                  border: "2px solid #0f172a",
                }}
              />
            ) : null}
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.68rem", color: "var(--sub, #64748b)" }}>
            <span>-1.0 Bearish</span>
            <span>0.0 Neutral</span>
            <span>+1.0 Bullish</span>
          </div>
        </div>

        {/* Card 3: Bayesian Epistemic Uncertainty */}
        <div
          style={{
            background: "rgba(18, 26, 43, 0.65)",
            border: "1px solid rgba(255, 255, 255, 0.08)",
            borderRadius: "10px",
            padding: "14px",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <span style={{ fontSize: "0.72rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--sub, #94a3b8)" }}>
              Epistemic Gate
            </span>
            <span style={{ fontSize: "0.85rem", fontWeight: 800, color: !hasUncertainty ? "#94a3b8" : (isUncertaintyVetoed ? "#f43f5e" : "#10b981") }}>
              {hasUncertainty
                ? `${uncertaintyVal.toFixed(2)} / ${thresholdVal.toFixed(2)} Limit`
                : `UNAVAILABLE / ${thresholdVal.toFixed(2)} Limit`}
            </span>
          </div>

          {/* Visual Track */}
          <div style={{ margin: "10px 0 6px", height: "8px", borderRadius: "4px", background: "rgba(255,255,255,0.08)", position: "relative", overflow: "hidden" }}>
            <div
              style={{
                height: "100%",
                width: hasUncertainty ? `${Math.min(100, Math.round(uncertaintyVal * 100))}%` : "0%",
                background: isUncertaintyVetoed ? "#f43f5e" : "#10b981",
                borderRadius: "4px",
                transition: "width 0.3s ease",
              }}
            />
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.68rem", color: "var(--sub, #64748b)" }}>
            <span>0.0 Certain</span>
            <span style={{ color: !hasUncertainty ? "#94a3b8" : (isUncertaintyVetoed ? "#fb7185" : "#34d399"), fontWeight: 600 }}>
              {!hasUncertainty
                ? "Awaiting Analysis"
                : (isUncertaintyVetoed ? "⚠️ Safety Veto Engaged" : "✓ Uncertainty Safe")}
            </span>
            <span>1.0 High Noise</span>
          </div>
        </div>

        {/* Card 4: Quant ML HTF Confluence */}
        <div
          style={{
            background: "rgba(18, 26, 43, 0.65)",
            border: "1px solid rgba(255, 255, 255, 0.08)",
            borderRadius: "10px",
            padding: "14px",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <span style={{ fontSize: "0.72rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--sub, #94a3b8)" }}>
              Quant-Agent Confluence
            </span>
            <span style={{ fontSize: "0.85rem", fontWeight: 800, color: hasMlProb ? "#38bdf8" : "#94a3b8" }}>
              {hasMlProb ? `${mlProbUp}% P(Up)` : "— P(Up)"}
            </span>
          </div>

          <div style={{ margin: "8px 0" }}>
            <span
              style={{
                display: "inline-block",
                padding: "2px 8px",
                borderRadius: "4px",
                fontSize: "0.74rem",
                fontWeight: 700,
                background: !hasMlProb
                  ? "rgba(148, 163, 184, 0.15)"
                  : (mlProb >= 0.52 ? "rgba(16, 185, 129, 0.15)" : mlProb <= 0.48 ? "rgba(244, 63, 94, 0.15)" : "rgba(56, 189, 248, 0.15)"),
                color: !hasMlProb
                  ? "#94a3b8"
                  : (mlProb >= 0.52 ? "#34d399" : mlProb <= 0.48 ? "#fb7185" : "#38bdf8"),
              }}
            >
              {!hasMlProb
                ? "⏸ Awaiting Forecast Data"
                : (mlProb >= 0.52 ? "🟢 High Confluence (Long)" : mlProb <= 0.48 ? "🔴 High Confluence (Short)" : "🔵 Neutral Deadband (48%–52%)")}
            </span>
          </div>

          <div style={{ fontSize: "0.68rem", color: "var(--sub, #64748b)" }}>
            ML Model: {activeModelDisplay} · 15m Horizon
          </div>
        </div>
      </div>

      {/* Active Deterministic Risk & Quorum Vetoes Banner */}
      {isReportAvailable && hasActiveVetoes && (
        <div
          style={{
            background: "rgba(244, 63, 94, 0.12)",
            border: "1px solid rgba(244, 63, 94, 0.35)",
            borderRadius: "8px",
            padding: "10px 14px",
            marginBottom: "12px",
            display: "flex",
            flexDirection: "column",
            gap: "6px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ fontSize: "0.85rem" }}>🛡️</span>
            <span style={{ fontSize: "0.76rem", fontWeight: 800, color: "#fb7185", letterSpacing: "0.04em", textTransform: "uppercase" }}>
              Active Gating Vetoes ({activeVetoes.length} Triggered — All Trades Blocked)
            </span>
          </div>
          <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
            {activeVetoes.map((veto) => (
              <span
                key={veto}
                style={{
                  padding: "2px 8px",
                  borderRadius: "4px",
                  background: "rgba(244, 63, 94, 0.2)",
                  color: "#fecdd3",
                  fontSize: "0.72rem",
                  fontWeight: 700,
                  fontFamily: "monospace",
                  border: "1px solid rgba(244, 63, 94, 0.4)",
                }}
              >
                ⛔ {veto}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Execution Dimensions Truth Strip */}
      <div
        style={{
          display: "flex",
          gap: "8px",
          alignItems: "center",
          flexWrap: "wrap",
          padding: "8px 12px",
          background: "rgba(0, 0, 0, 0.25)",
          borderRadius: "8px",
          border: "1px solid rgba(255, 255, 255, 0.05)",
          marginBottom: "16px",
          fontSize: "0.7rem",
          color: "var(--sub, #94a3b8)",
        }}
      >
        <span style={{ fontWeight: 700, color: "var(--ink, #fff)", marginRight: "4px" }}>System State:</span>
        <span style={{ padding: "2px 6px", borderRadius: "4px", background: "rgba(16, 185, 129, 0.1)", color: "#34d399" }}>
          ● Ingestion: Active
        </span>
        <span style={{ padding: "2px 6px", borderRadius: "4px", background: isReportAvailable ? "rgba(56, 189, 248, 0.1)" : "rgba(148, 163, 184, 0.1)", color: isReportAvailable ? "#38bdf8" : "#94a3b8" }}>
          {isReportAvailable ? "● Forecast: Evaluated (M15)" : (liveForecast ? "● Forecast: Snapshot Ready" : "○ Forecast: Pending")}
        </span>
        <span style={{ padding: "2px 6px", borderRadius: "4px", background: "rgba(245, 158, 11, 0.1)", color: "#fbbf24" }}>
          ● Paper Execution: Disarmed / Gated
        </span>
        <span style={{ padding: "2px 6px", borderRadius: "4px", background: "rgba(244, 63, 94, 0.1)", color: "#fb7185" }}>
          🔒 Live Broker: Hard Locked (Blocked)
        </span>
        <span style={{ padding: "2px 6px", borderRadius: "4px", background: "rgba(56, 189, 248, 0.1)", color: "#38bdf8" }}>
          ● Quorum: {isReportAvailable ? `${reportingCount}/${configuredCount} Reporting` : "6 Configured"}
        </span>
        <span style={{ padding: "2px 6px", borderRadius: "4px", background: isReportAvailable && participationRate >= 0.33 ? "rgba(16, 185, 129, 0.1)" : "rgba(245, 158, 11, 0.1)", color: isReportAvailable && participationRate >= 0.33 ? "#34d399" : "#fbbf24" }}>
          ● Participation: {isReportAvailable ? `${directionalVoters} Voters (${Math.round(participationRate * 100)}% / Min 33%)` : "—"}
        </span>
        {isReportAvailable && fallbackCount > 0 && (
          <span style={{ padding: "2px 6px", borderRadius: "4px", background: "rgba(148, 163, 184, 0.12)", color: "#94a3b8" }}>
            ○ Fallback: {fallbackCount}
          </span>
        )}
        {isReportAvailable && missingCount > 0 && (
          <span style={{ padding: "2px 6px", borderRadius: "4px", background: "rgba(244, 63, 94, 0.12)", color: "#fb7185" }}>
            ⚠️ Missing: {missingCount}
          </span>
        )}
        {isReportAvailable && totalWeight !== null && (
          <span style={{ padding: "2px 6px", borderRadius: "4px", background: "rgba(255, 255, 255, 0.05)", color: "#cbd5e1" }}>
            Σ W_eff: {totalWeight.toFixed(2)}
          </span>
        )}
        {isReportAvailable && report?.created_at && (
          <span style={{ padding: "2px 6px", borderRadius: "4px", background: "rgba(56, 189, 248, 0.1)", color: "#38bdf8" }} title={`Analysis Cycle ID: ${report.analysis_id || "N/A"}`}>
            ● Cycle: {report.analysis_id ? `${report.analysis_id.slice(0, 8)}…` : "Live"} ({new Date(report.created_at).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit" })} IST)
          </span>
        )}
      </div>

      {/* Specialist Perspectives Grid */}
      <div style={{ marginTop: "12px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
          <div>
            <h3 style={{ margin: 0, fontSize: "0.92rem", fontWeight: 700, color: "var(--ink, #fff)", display: "flex", alignItems: "center", gap: "6px" }}>
              <span>👥 8 Specialist Agents · 4 Research Desks</span>
              <span style={{ fontSize: "0.72rem", padding: "1px 6px", borderRadius: "10px", background: "rgba(255,255,255,0.08)", color: "#cbd5e1" }}>
                {isReportAvailable ? `${executedCount}/${implementedCount} Implemented Online` : `0/${implementedCount} Online · Awaiting Run`}
              </span>
            </h3>
            <span style={{ fontSize: "0.72rem", color: "var(--sub, #94a3b8)" }}>
              Point-in-time stance and confidence across 8 LangGraph specialist agents and 4 research reference desks.
            </span>
          </div>

          <button
            type="button"
            onClick={() => setViewMode((prev) => (prev === "grid" ? "compact" : "grid"))}
            style={{
              padding: "3px 8px",
              borderRadius: "6px",
              background: "rgba(255,255,255,0.05)",
              border: "1px solid var(--line, #334155)",
              color: "var(--sub, #94a3b8)",
              fontSize: "0.72rem",
              cursor: "pointer",
            }}
          >
            {viewMode === "grid" ? "Compact View ⊞" : "Grid View ▦"}
          </button>
        </div>

        {/* Visual Cards Grid */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: viewMode === "grid" ? "repeat(auto-fill, minmax(185px, 1fr))" : "repeat(auto-fill, minmax(140px, 1fr))",
            gap: "10px",
          }}
        >
          {AGENT_CATALOG.map((agent) => {
            let stance = null;
            let conf = null;
            let categoryLabel = agent.isImplemented ? "Specialist Agent" : (agent.id === "expected_payoff" ? "Payoff Model" : "Catalog Ref");

            if (!isReportAvailable) {
              // Pre-analysis run state: strictly no mock stances or fake confidences
              if (agent.id === "expected_payoff") {
                stance = "UNAVAILABLE";
              } else if (!agent.isImplemented) {
                stance = "UNIMPLEMENTED";
              } else {
                stance = "NOT RUN";
              }
              conf = null;
            } else {
              // Live analysis run state
              if (agent.id === "expected_payoff") {
                // Expected net payoff options engine check
                const evNet = report?.intelligence?.options?.expected_net ?? null;
                stance = evNet !== null ? (evNet > 0 ? "BULLISH" : evNet < 0 ? "BEARISH" : "NEUTRAL") : "UNAVAILABLE";
                conf = null;
              } else if (!agent.isImplemented) {
                // Catalog-only entries without standalone LangGraph nodes
                stance = "CATALOG ONLY";
                conf = null;
              } else {
                // Implemented LangGraph specialist agents
                const out = agentOutputs[agent.id] || agentOutputs[agent.legacyKey] || {};
                stance = out.directional_bias;
                conf = typeof out.confidence === "number" && !isNaN(out.confidence) && out.confidence > 0
                  ? Math.round(out.confidence * 100)
                  : null;

                // Sync the Quant ML Model specialist with model forecast if present
                if (agent.id === "quant_forecast" && !stance) {
                  if (liveForecast?.predicted_direction) {
                    stance = liveForecast.predicted_direction;
                    conf = mlProb !== null ? Math.round(mlProb * 100) : null;
                  }
                }

                if (!stance || stance === "UNKNOWN") {
                  stance = out.status === "FAILED" ? "FAILED" : out.status === "SKIPPED" ? "SKIPPED" : "UNAVAILABLE";
                }
              }
            }

            const isBull = stance === "BULLISH";
            const isBear = stance === "BEARISH";
            const isUnavail = stance === "UNAVAILABLE" || stance === "UNIMPLEMENTED" || stance === "CATALOG ONLY";
            const stanceColor = isBull ? "#10b981" : isBear ? "#f43f5e" : isUnavail ? "#64748b" : "#94a3b8";
            const stanceBg = isBull
              ? "rgba(16, 185, 129, 0.15)"
              : isBear
              ? "rgba(244, 63, 94, 0.15)"
              : "rgba(255, 255, 255, 0.05)";

            const specialistScores = consensus?.specialist_scores || {};
            const specScore = specialistScores[agent.legacyKey] || specialistScores[agent.id] || {};
            const out = agent.isImplemented ? (agentOutputs[agent.id] || agentOutputs[agent.legacyKey] || {}) : {};
            const semanticType = out.semantic_type || specScore.semantic_type || (agent.id === "quant_forecast" ? "UNCALIBRATED_MODEL_PROBABILITY" : (agent.id === "order_flow" ? "STATIC_DEFAULT" : "HEURISTIC_SIGNAL_STRENGTH"));
            const isProb = Boolean(out.is_probability || specScore.is_probability || agent.id === "quant_forecast");
            const isCalibrated = Boolean(out.is_calibrated || specScore.is_calibrated);
            const effectiveWeight = typeof specScore.effective_weight === "number" ? specScore.effective_weight : (typeof out.effective_weight === "number" ? out.effective_weight : null);
            const isZeroWeight = effectiveWeight === 0.0 || (agent.id === "options_greeks" && semanticType === "STATIC_DEFAULT");

            let semanticPillText = null;
            let semanticPillBg = "rgba(255, 255, 255, 0.05)";
            let semanticPillColor = "#94a3b8";

            if (agent.isImplemented && isReportAvailable) {
              if (semanticType === "UNCALIBRATED_MODEL_PROBABILITY" || (isProb && !isCalibrated)) {
                semanticPillText = "Uncalibrated ML Prob";
                semanticPillBg = "rgba(168, 85, 247, 0.12)";
                semanticPillColor = "#c084fc";
              } else if (semanticType === "MEASURED_HIT_RATE") {
                semanticPillText = "Measured Hit Rate";
                semanticPillBg = "rgba(16, 185, 129, 0.12)";
                semanticPillColor = "#34d399";
              } else if (semanticType === "HEURISTIC_SIGNAL_STRENGTH") {
                semanticPillText = "Unmeasured Heuristic";
                semanticPillBg = "rgba(56, 189, 248, 0.12)";
                semanticPillColor = "#38bdf8";
              } else if (semanticType === "STATIC_DEFAULT") {
                semanticPillText = "Static Default";
                semanticPillBg = "rgba(148, 163, 184, 0.12)";
                semanticPillColor = "#94a3b8";
              } else if (semanticType && semanticType !== "UNKNOWN") {
                semanticPillText = semanticType;
              }
            }

            return (
              <div
                key={agent.id}
                style={{
                  background: "rgba(18, 26, 43, 0.65)",
                  border: `1px solid ${isBull ? "rgba(16, 185, 129, 0.25)" : isBear ? "rgba(244, 63, 94, 0.25)" : "rgba(255, 255, 255, 0.08)"}`,
                  borderRadius: "8px",
                  padding: "10px",
                  display: "flex",
                  flexDirection: "column",
                  gap: "6px",
                  opacity: agent.isImplemented ? 1 : 0.8,
                  transition: "transform 0.15s ease",
                }}
              >
                {/* Agent Header */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    <span style={{ fontSize: "1rem" }}>{agent.icon}</span>
                    <span style={{ fontSize: "0.78rem", fontWeight: 700, color: "var(--ink, #fff)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "90px" }}>
                      {agent.name}
                    </span>
                  </div>
                  <span
                    style={{
                      fontSize: "0.62rem",
                      fontWeight: 800,
                      padding: "2px 5px",
                      borderRadius: "4px",
                      background: stanceBg,
                      color: stanceColor,
                      letterSpacing: "0.02em",
                    }}
                  >
                    {stance}
                  </span>
                </div>

                {/* Subtitle / Role & Category Badge */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "0.65rem", color: "var(--sub, #64748b)" }}>
                  <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "115px" }}>
                    {agent.id === "expected_payoff" && isReportAvailable ? "Options EV Unavailable" : agent.role}
                  </span>
                  <span style={{ fontSize: "0.58rem", padding: "1px 4px", borderRadius: "3px", background: "rgba(255,255,255,0.04)", color: "#94a3b8" }}>
                    {categoryLabel}
                  </span>
                </div>

                {/* Semantic Type & Weight Pill */}
                {agent.isImplemented && isReportAvailable && semanticPillText && (
                  <div style={{ display: "flex", gap: "4px", alignItems: "center", flexWrap: "wrap", margin: "2px 0 4px" }}>
                    <span style={{ fontSize: "0.58rem", padding: "1px 5px", borderRadius: "3px", background: semanticPillBg, color: semanticPillColor, fontWeight: 700 }}>
                      {semanticPillText}
                    </span>
                    {isZeroWeight ? (
                      <span style={{ fontSize: "0.58rem", padding: "1px 4px", borderRadius: "3px", background: "rgba(244, 63, 94, 0.15)", color: "#fb7185", fontWeight: 700 }} title="Zero effective weight in consensus aggregation">
                        W_eff: 0.0 ({["NO_EDGE_YET", "WORSE_THAN_CHANCE"].includes(specScore.evidence_status) ? "no proven edge" : "Fallback"})
                      </span>
                    ) : effectiveWeight !== null ? (
                      <span style={{ fontSize: "0.58rem", padding: "1px 4px", borderRadius: "3px", background: "rgba(255, 255, 255, 0.05)", color: "#94a3b8" }} title="Effective quality-weighted consensus weight">
                        W_eff: {effectiveWeight.toFixed(2)}
                      </span>
                    ) : null}
                    {TRACK_RECORD_LABEL[specScore.evidence_status] ? (
                      <span
                        data-testid={`track-record-${agent.id}`}
                        style={{ fontSize: "0.58rem", padding: "1px 4px", borderRadius: "3px", background: TRACK_RECORD_LABEL[specScore.evidence_status].bg, color: TRACK_RECORD_LABEL[specScore.evidence_status].color, fontWeight: 700 }}
                        title="How this agent's track record set its consensus weight"
                      >
                        {TRACK_RECORD_LABEL[specScore.evidence_status].text}
                      </span>
                    ) : null}
                  </div>
                )}

                {/* Visual Confidence Bar */}
                <div style={{ marginTop: "auto", paddingTop: "4px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.65rem", color: "var(--sub, #94a3b8)", marginBottom: "3px" }}>
                    <span>{isProb ? "Probability" : "Confidence / Score"}</span>
                    <strong style={{ color: conf !== null ? stanceColor : "#64748b" }}>
                      {conf !== null ? `${conf}%` : "—"}
                    </strong>
                  </div>
                  <div style={{ height: "4px", borderRadius: "2px", background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
                    <div
                      style={{
                        height: "100%",
                        width: conf !== null ? `${conf}%` : "0%",
                        background: stanceColor,
                        borderRadius: "2px",
                      }}
                    />
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {onExpandDetailed && (
          <div style={{ textAlign: "center", marginTop: "16px", borderTop: "1px dashed var(--line, rgba(255,255,255,0.08))", paddingTop: "14px" }}>
            <button
              type="button"
              onClick={onExpandDetailed}
              style={{
                padding: "8px 18px",
                borderRadius: "8px",
                background: "rgba(56, 189, 248, 0.08)",
                border: "1px solid rgba(56, 189, 248, 0.3)",
                color: "#38bdf8",
                fontWeight: 650,
                fontSize: "0.82rem",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: "8px",
              }}
            >
              <span>🔬 Expand Detailed 8-Agent Analysis Desk &amp; Full Audit Dossier (Stages 0–14) ▾</span>
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
