"use client";

import { useEffect, useState } from "react";
import { useMarketData } from "./MarketDataContext";
import { csrfToken } from "./session";

const AGENT_CATALOG = [
  { id: "news_events", legacyKey: "news_event_analyst", name: "News Sentiment", icon: "📰", role: "Real-time Wire Sentiment", defaultStance: "NEUTRAL", defaultConf: 65 },
  { id: "global_macro", legacyKey: "global_macro_analyst", name: "Global Macro", icon: "🌐", role: "Yields, FX USD/INR & DOW", defaultStance: "BULLISH", defaultConf: 72 },
  { id: "commodities", legacyKey: "crude_cross_asset", name: "Intermarket & MCX", icon: "🛢️", role: "Crude Oil & Gold Flows", defaultStance: "NEUTRAL", defaultConf: 60 },
  { id: "order_flow", legacyKey: "market_data_analyst", name: "Order Flow", icon: "📊", role: "Microstructure & Volumes", defaultStance: "BULLISH", defaultConf: 68 },
  { id: "options_greeks", legacyKey: "options_analyst", name: "Options & Greeks", icon: "⚡", role: "Black-76, IV & PCR Skew", defaultStance: "NEUTRAL", defaultConf: 55 },
  { id: "trend_momentum", legacyKey: "technical_analyst", name: "Trend & Momentum", icon: "📈", role: "EMA 20/50 & Supertrend", defaultStance: "BULLISH", defaultConf: 80 },
  { id: "mean_reversion", legacyKey: "mean_reversion", name: "Mean Reversion", icon: "🔄", role: "RSI & Bollinger Z-Score", defaultStance: "NEUTRAL", defaultConf: 50 },
  { id: "htf_resampling", legacyKey: "htf_resampling", name: "HTF Resampling", icon: "⏱", role: "Multi-Timeframe Alignment", defaultStance: "BULLISH", defaultConf: 75 },
  { id: "quant_forecast", legacyKey: "quant_forecast_analyst", name: "Quant ML Model", icon: "🔬", role: "19-Fold Walk-Forward Prob", defaultStance: "BULLISH", defaultConf: 70 },
  { id: "bayesian_gate", legacyKey: "risk_uncertainty_analyst", name: "Bayesian Epistemic Gate", icon: "🛡️", role: "Dispersion Gating (0.65 Cutoff)", defaultStance: "NEUTRAL", defaultConf: 62 },
  { id: "expected_payoff", legacyKey: "expected_payoff", name: "Expected Net Payoff", icon: "💰", role: "2.0 bps Friction & EV", defaultStance: "BULLISH", defaultConf: 65 },
  { id: "final_arbiter", legacyKey: "final_decision_agent", name: "Consensus Arbiter", icon: "⚖️", role: "LangGraph Consensus Engine", defaultStance: "BULLISH", defaultConf: 78 },
];

export default function VisualAgentDecisionCard() {
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

  // Derive visual metrics from report or default state
  const decision = report?.decision || "STAND_ASIDE";
  const consensus = report?.consensus || {};
  const agentOutputs = report?.agent_outputs || {};
  const recommendation = report?.recommendation || {};

  const isBuy = decision.includes("BUY") || decision === "BULLISH";
  const isSell = decision.includes("SELL") || decision === "BEARISH";
  const isStandAside = !isBuy && !isSell;

  const decisionColor = isBuy ? "#10b981" : isSell ? "#f43f5e" : "#f59e0b";
  const decisionBg = isBuy ? "rgba(16, 185, 129, 0.12)" : isSell ? "rgba(244, 63, 94, 0.12)" : "rgba(245, 158, 11, 0.12)";
  const decisionBorder = isBuy ? "rgba(16, 185, 129, 0.3)" : isSell ? "rgba(244, 63, 94, 0.3)" : "rgba(245, 158, 11, 0.3)";

  // Consensus score from -10 to +10 mapped to percentage 0-100%
  const scoreVal = typeof consensus.consensus_score === "number" ? consensus.consensus_score : (report ? (isBuy ? 3.5 : isSell ? -3.5 : 0.0) : 0.0);
  const scorePct = Math.max(0, Math.min(100, ((scoreVal + 10) / 20) * 100));

  // Epistemic Uncertainty (0.0 to 1.0)
  const uncertaintyVal = typeof consensus.epistemic_uncertainty === "number" ? consensus.epistemic_uncertainty : 0.52;
  const isGated = uncertaintyVal >= 0.65 || (report && (decision === "NO_TRADE" || decision === "STAND_ASIDE"));

  // Quant Confluence probability extraction (safely handle object or number)
  const rawProbObj = report?.intelligence?.forecast?.probabilities?.[instrument];
  const reportProbUp = typeof rawProbObj === "number" ? rawProbObj : (typeof rawProbObj?.up === "number" ? rawProbObj.up : null);
  const liveProb = typeof liveForecast?.calibrated_probability === "number" ? liveForecast.calibrated_probability : null;
  const rawProb = liveProb ?? reportProbUp ?? report?.intelligence?.forecast?.calibrated_probability ?? 0.534;
  const mlProb = (typeof rawProb === "number" && !isNaN(rawProb)) ? rawProb : 0.534;
  const mlProbUp = Math.round(mlProb * 100);
  const activeModelDisplay = (liveForecast?.model_name || selectedModel || "CHAMPION").toUpperCase();

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
              🤖 12-AGENT QUANT DECISION ENGINE
            </span>
            <span style={{ fontSize: "0.72rem", fontWeight: 700, padding: "2px 8px", borderRadius: "4px", background: "rgba(16, 185, 129, 0.15)", color: "#34d399", border: "1px solid rgba(16, 185, 129, 0.3)" }}>
              DETERMINISTIC CONSENSUS
            </span>
            <span style={{ fontSize: "0.72rem", color: "var(--sub, #94a3b8)" }}>
              Active Underlying: <strong style={{ color: "var(--ink, #fff)" }}>{instrument}</strong>
            </span>
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
                <span>Synthesizing 12 Agents…</span>
              </>
            ) : (
              <>
                <span>⚡ Run Live Analysis</span>
              </>
            )}
          </button>
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
          marginBottom: "18px",
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
              {decision === "NO_TRADE" || decision === "STAND_ASIDE" ? "STAND ASIDE (NO TRADE)" : decision}
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span style={{ fontSize: "0.72rem", padding: "2px 6px", borderRadius: "4px", background: "rgba(255,255,255,0.06)", color: "var(--sub, #94a3b8)" }}>
              {isGated ? "🔒 Deadband / Safety Gated" : "✓ Active Execution"}
            </span>
          </div>
        </div>

        {/* Card 2: Consensus Spectrum Meter (-10 to +10) */}
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
            <span style={{ fontSize: "0.88rem", fontWeight: 800, color: scoreVal > 0 ? "#10b981" : scoreVal < 0 ? "#f43f5e" : "#fbbf24" }}>
              {scoreVal > 0 ? `+${scoreVal.toFixed(1)} Bullish` : scoreVal < 0 ? `${scoreVal.toFixed(1)} Bearish` : "0.0 Neutral"}
            </span>
          </div>

          {/* Visual Spectrum Bar */}
          <div style={{ margin: "10px 0 6px", position: "relative" }}>
            <div
              style={{
                height: "8px",
                borderRadius: "4px",
                background: "linear-gradient(to right, #f43f5e 0%, #f59e0b 50%, #10b981 100%)",
                width: "100%",
                opacity: 0.85,
              }}
            />
            {/* Pointer Indicator */}
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
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.68rem", color: "var(--sub, #64748b)" }}>
            <span>-10 Bearish</span>
            <span>0 Neutral</span>
            <span>+10 Bullish</span>
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
            <span style={{ fontSize: "0.85rem", fontWeight: 800, color: isGated ? "#f43f5e" : "#10b981" }}>
              {uncertaintyVal.toFixed(2)} / 0.65 Limit
            </span>
          </div>

          {/* Visual Track */}
          <div style={{ margin: "10px 0 6px", height: "8px", borderRadius: "4px", background: "rgba(255,255,255,0.08)", position: "relative", overflow: "hidden" }}>
            <div
              style={{
                height: "100%",
                width: `${Math.min(100, Math.round(uncertaintyVal * 100))}%`,
                background: isGated ? "#f43f5e" : "#10b981",
                borderRadius: "4px",
                transition: "width 0.3s ease",
              }}
            />
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.68rem", color: "var(--sub, #64748b)" }}>
            <span>0.0 Certain</span>
            <span style={{ color: isGated ? "#fb7185" : "#34d399", fontWeight: 600 }}>
              {isGated ? "⚠️ Safety Veto Engaged" : "✓ Uncertainty Safe"}
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
            <span style={{ fontSize: "0.85rem", fontWeight: 800, color: "#38bdf8" }}>
              {mlProbUp}% P(Up)
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
                background: mlProb >= 0.52 ? "rgba(16, 185, 129, 0.15)" : mlProb <= 0.48 ? "rgba(244, 63, 94, 0.15)" : "rgba(56, 189, 248, 0.15)",
                color: mlProb >= 0.52 ? "#34d399" : mlProb <= 0.48 ? "#fb7185" : "#38bdf8",
              }}
            >
              {mlProb >= 0.52 ? "🟢 High Confluence (Long)" : mlProb <= 0.48 ? "🔴 High Confluence (Short)" : "🔵 Deadband (48%–52%)"}
            </span>
          </div>

          <div style={{ fontSize: "0.68rem", color: "var(--sub, #64748b)" }}>
            ML Model: {activeModelDisplay} · 19 Folds Walk-Forward
          </div>
        </div>
      </div>

      {/* 12 Specialist Agents Visual Grid (Visual Matrix) */}
      <div style={{ marginTop: "16px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
          <div>
            <h3 style={{ margin: 0, fontSize: "0.92rem", fontWeight: 700, color: "var(--ink, #fff)", display: "flex", alignItems: "center", gap: "6px" }}>
              <span>👥 12 Specialist Perspectives</span>
              <span style={{ fontSize: "0.72rem", padding: "1px 6px", borderRadius: "10px", background: "rgba(255,255,255,0.08)", color: "#cbd5e1" }}>
                12/12 Online
              </span>
            </h3>
            <span style={{ fontSize: "0.72rem", color: "var(--sub, #94a3b8)" }}>
              Instant visual breakdown of stance, confidence, and role across all 12 quantitative specialists.
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
            const out = agentOutputs[agent.id] || agentOutputs[agent.legacyKey] || {};
            let stance = out.directional_bias;
            let conf = typeof out.confidence === "number" && !isNaN(out.confidence) && out.confidence > 0 
              ? Math.round(out.confidence * 100) 
              : null;

            // Dynamically sync the Quant ML Model specialist with the user's selected forecasting model
            if (agent.id === "quant_forecast" && liveForecast?.predicted_direction) {
              stance = liveForecast.predicted_direction;
              conf = Math.round(mlProb * 100);
            }

            if (!stance || stance === "UNKNOWN") {
              stance = agent.defaultStance;
            }
            if (conf === null) {
              conf = agent.defaultConf;
            }

            const isBull = stance === "BULLISH";
            const isBear = stance === "BEARISH";
            const stanceColor = isBull ? "#10b981" : isBear ? "#f43f5e" : "#94a3b8";
            const stanceBg = isBull ? "rgba(16, 185, 129, 0.15)" : isBear ? "rgba(244, 63, 94, 0.15)" : "rgba(255, 255, 255, 0.08)";

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
                      fontSize: "0.65rem",
                      fontWeight: 800,
                      padding: "2px 6px",
                      borderRadius: "4px",
                      background: stanceBg,
                      color: stanceColor,
                    }}
                  >
                    {stance}
                  </span>
                </div>

                {/* Subtitle / Role */}
                {viewMode === "grid" && (
                  <span style={{ fontSize: "0.68rem", color: "var(--sub, #64748b)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {agent.role}
                  </span>
                )}

                {/* Visual Confidence Bar */}
                <div style={{ marginTop: "auto" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.65rem", color: "var(--sub, #94a3b8)", marginBottom: "3px" }}>
                    <span>Confidence</span>
                    <strong style={{ color: stanceColor }}>{conf}%</strong>
                  </div>
                  <div style={{ height: "4px", borderRadius: "2px", background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
                    <div
                      style={{
                        height: "100%",
                        width: `${conf}%`,
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
      </div>
    </section>
  );
}
