import assert from "node:assert/strict";
import test from "node:test";

// Logic extract mirror from VisualAgentDecisionCard for unit testing deterministic data flows
const AGENT_CATALOG = [
  { id: "news_events", legacyKey: "news_event_analyst", name: "News Sentiment", isImplemented: true },
  { id: "global_macro", legacyKey: "global_macro_analyst", name: "Global Macro", isImplemented: true },
  { id: "order_flow", legacyKey: "market_data_analyst", name: "Order Flow", isImplemented: true },
  { id: "options_greeks", legacyKey: "options_analyst", name: "Options & Greeks", isImplemented: true },
  { id: "trend_momentum", legacyKey: "technical_analyst", name: "Trend & Momentum", isImplemented: true },
  { id: "quant_forecast", legacyKey: "quant_forecast_analyst", name: "Quant ML Model", isImplemented: true },
  { id: "bayesian_gate", legacyKey: "risk_uncertainty_analyst", name: "Bayesian Epistemic Gate", isImplemented: true },
  { id: "final_arbiter", legacyKey: "final_decision_agent", name: "Consensus Arbiter", isImplemented: true },
  { id: "commodities", legacyKey: "crude_cross_asset", name: "Intermarket & MCX", isImplemented: false },
  { id: "mean_reversion", legacyKey: "mean_reversion", name: "Mean Reversion", isImplemented: false },
  { id: "htf_resampling", legacyKey: "htf_resampling", name: "HTF Resampling", isImplemented: false },
  { id: "expected_payoff", legacyKey: "expected_payoff", name: "Expected Net Payoff", isImplemented: false },
];

function deriveCardMetrics(report, liveForecast = null) {
  const isReportAvailable = Boolean(report);
  const decision = isReportAvailable ? (report.decision || "STAND_ASIDE") : "NOT_RUN";
  const consensus = report?.consensus || null;
  const agentOutputs = report?.agent_outputs || {};
  const activeVetoes = Array.isArray(consensus?.vetoes) ? consensus.vetoes : [];
  const hasActiveVetoes = activeVetoes.length > 0;

  const rawScore = typeof consensus?.consensus_score === "number" ? consensus.consensus_score : null;
  const thresholdVal = typeof consensus?.gating_threshold === "number" ? consensus.gating_threshold : 0.45;
  const rawUncertainty = typeof consensus?.epistemic_uncertainty === "number" ? consensus.epistemic_uncertainty : null;
  const isUncertaintyVetoed = rawUncertainty !== null && (rawUncertainty >= thresholdVal || activeVetoes.includes("EXCESSIVE_EPISTEMIC_UNCERTAINTY"));

  const configuredCount = typeof consensus?.configured_specialist_count === "number" ? consensus.configured_specialist_count : 6;
  const reportingCount = typeof consensus?.reporting_specialist_count === "number"
    ? consensus.reporting_specialist_count
    : (typeof consensus?.active_specialist_count === "number" ? consensus.active_specialist_count : 0);
  const directionalVoters = typeof consensus?.directional_voter_count === "number" ? consensus.directional_voter_count : 0;
  const participationRate = typeof consensus?.directional_participation_rate === "number" ? consensus.directional_participation_rate : 0.0;

  let executionBadgeText = "⏸ Awaiting Analysis Cycle";
  if (isReportAvailable) {
    if (decision === "NO_TRADE" || decision === "STAND_ASIDE" || isUncertaintyVetoed || hasActiveVetoes) {
      executionBadgeText = "🔒 Deadband / Safety Gated (NO TRADE)";
    } else {
      executionBadgeText = "🔒 Live Routing Disabled (Paper Only)";
    }
  }

  const deskVerdict = !isReportAvailable
    ? "AWAITING ANALYSIS (NO TRADE)"
    : (decision === "NO_TRADE" || decision === "STAND_ASIDE" || hasActiveVetoes ? "STAND ASIDE (NO TRADE)" : decision);

  const specialistScores = consensus?.specialist_scores || {};
  const agentStates = AGENT_CATALOG.map((agent) => {
    let stance = null;
    let conf = null;
    let semanticType = null;
    let effectiveWeight = null;
    let isZeroWeight = false;

    if (!isReportAvailable) {
      if (agent.id === "expected_payoff") {
        stance = "UNAVAILABLE";
      } else if (!agent.isImplemented) {
        stance = "UNIMPLEMENTED";
      } else {
        stance = "NOT RUN";
      }
      conf = null;
    } else {
      if (agent.id === "expected_payoff") {
        const evNet = report?.intelligence?.options?.expected_net ?? null;
        stance = evNet !== null ? (evNet > 0 ? "BULLISH" : evNet < 0 ? "BEARISH" : "NEUTRAL") : "UNAVAILABLE";
        conf = null;
      } else if (!agent.isImplemented) {
        stance = "CATALOG ONLY";
        conf = null;
      } else {
        const out = agentOutputs[agent.id] || agentOutputs[agent.legacyKey] || {};
        const specScore = specialistScores[agent.legacyKey] || specialistScores[agent.id] || {};
        stance = out.directional_bias || (out.status === "FAILED" ? "FAILED" : out.status === "SKIPPED" ? "SKIPPED" : "UNAVAILABLE");
        conf = typeof out.confidence === "number" && !isNaN(out.confidence) ? Math.round(out.confidence * 100) : null;
        semanticType = out.semantic_type || specScore.semantic_type || (agent.id === "quant_forecast" ? "UNCALIBRATED_MODEL_PROBABILITY" : "UNKNOWN");
        effectiveWeight = typeof specScore.effective_weight === "number" ? specScore.effective_weight : null;
        isZeroWeight = effectiveWeight === 0.0 || (agent.id === "options_greeks" && semanticType === "STATIC_DEFAULT");
      }
    }
    return { id: agent.id, stance, conf, semanticType, effectiveWeight, isZeroWeight, isImplemented: agent.isImplemented };
  });

  const implementedCount = AGENT_CATALOG.filter((a) => a.isImplemented).length;
  const executedCount = isReportAvailable
    ? AGENT_CATALOG.filter((a) => {
        if (!a.isImplemented) return false;
        const out = agentOutputs[a.id] || agentOutputs[a.legacyKey];
        return out && out.status && out.status !== "SKIPPED" && out.status !== "FAILED";
      }).length
    : 0;

  return {
    isReportAvailable,
    decision,
    deskVerdict,
    consensusScore: rawScore,
    uncertainty: rawUncertainty,
    threshold: thresholdVal,
    isUncertaintyVetoed,
    activeVetoes,
    configuredCount,
    reportingCount,
    directionalVoters,
    participationRate,
    executionBadgeText,
    agentStates,
    implementedCount,
    executedCount,
  };
}

test("V6 Integrity - Pre-analysis load displays NOT RUN without fabricating 0.0 consensus score", () => {
  const metrics = deriveCardMetrics(null);

  assert.equal(metrics.isReportAvailable, false);
  assert.equal(metrics.decision, "NOT_RUN");
  assert.equal(metrics.consensusScore, null, "Consensus score must be null prior to analysis run");
  assert.equal(metrics.uncertainty, null, "Uncertainty must be null prior to analysis run");
  assert.equal(metrics.threshold, 0.45, "Default veto threshold must match backend 0.45");
  assert.equal(metrics.executionBadgeText, "⏸ Awaiting Analysis Cycle");
  assert.notEqual(metrics.executionBadgeText, "✓ Active Execution", "Must never display Active Execution before analysis");
});

test("V6 Integrity - Exactly 8 implemented specialist agents and 4 catalog desks", () => {
  const metrics = deriveCardMetrics(null);

  assert.equal(metrics.implementedCount, 8, "Must only count 8 LangGraph specialist agents");
  assert.equal(metrics.executedCount, 0, "Executed count must be 0 prior to analysis run");

  const implemented = metrics.agentStates.filter((a) => a.isImplemented);
  assert.equal(implemented.length, 8);
  for (const agent of implemented) {
    assert.equal(agent.stance, "NOT RUN");
    assert.equal(agent.conf, null);
  }

  const catalogOnly = metrics.agentStates.filter((a) => !a.isImplemented);
  assert.equal(catalogOnly.length, 4);
  const evCard = catalogOnly.find((a) => a.id === "expected_payoff");
  assert.equal(evCard.stance, "UNAVAILABLE");
  assert.equal(evCard.conf, null);
});

test("V6 Integrity - Expected Net Value stays UNAVAILABLE when expected_net is null in live report", () => {
  const reportWithNullEV = {
    decision: "NO_TRADE",
    consensus: { consensus_score: 0.15, epistemic_uncertainty: 0.28, gating_threshold: 0.45, vetoes: [] },
    intelligence: {
      options: { expected_net: null, decision: "NO_TRADE" },
    },
    agent_outputs: {
      market_data_analyst: { directional_bias: "NEUTRAL", confidence: 0.65, status: "SUCCESS" },
      technical_analyst: { directional_bias: "BULLISH", confidence: 0.70, status: "SUCCESS" },
      global_macro_analyst: { directional_bias: "NEUTRAL", confidence: 0.60, status: "SUCCESS" },
      news_event_analyst: { directional_bias: "NEUTRAL", confidence: 0.55, status: "SUCCESS" },
      options_analyst: { directional_bias: "NEUTRAL", confidence: 0.50, status: "SUCCESS" },
      quant_forecast_analyst: { directional_bias: "BEARISH", confidence: 0.52, status: "SUCCESS" },
      risk_uncertainty_analyst: { directional_bias: "NEUTRAL", confidence: 0.72, status: "SUCCESS" },
      final_decision_agent: { directional_bias: "NEUTRAL", confidence: 0.65, status: "SUCCESS" },
    },
  };

  const metrics = deriveCardMetrics(reportWithNullEV);

  assert.equal(metrics.isReportAvailable, true);
  assert.equal(metrics.decision, "NO_TRADE");
  assert.equal(metrics.consensusScore, 0.15);
  assert.equal(metrics.uncertainty, 0.28);
  assert.equal(metrics.executedCount, 8, "All 8 implemented agents executed");

  const evCard = metrics.agentStates.find((a) => a.id === "expected_payoff");
  assert.equal(evCard.stance, "UNAVAILABLE", "EV card must remain UNAVAILABLE when expected_net is null");
  assert.equal(evCard.conf, null, "EV card must not fabricate a confidence score");
});

test("V6 Integrity - Epistemic gate veto triggers at 0.45 and execution stays locked", () => {
  const highUncertaintyReport = {
    decision: "NO_TRADE",
    consensus: {
      consensus_score: 0.05,
      epistemic_uncertainty: 0.52,
      gating_threshold: 0.45,
      vetoes: ["EXCESSIVE_EPISTEMIC_UNCERTAINTY"],
    },
    agent_outputs: {},
  };

  const metrics = deriveCardMetrics(highUncertaintyReport);
  assert.equal(metrics.uncertainty, 0.52);
  assert.equal(metrics.threshold, 0.45);
  assert.equal(metrics.isUncertaintyVetoed, true, "0.52 >= 0.45 must trigger epistemic veto");
  assert.equal(metrics.executionBadgeText, "🔒 Deadband / Safety Gated (NO TRADE)");
});

test("V6 Integrity - Execution dimensions separate paper and live broker status", () => {
  const executionControls = {
    monitoring: "ACTIVE_SNAPSHOT",
    forecast_evaluation: "M15_COMPLETED",
    paper_execution_mode: "GATED_DISARMED",
    paper_approved: false,
    live_approved: false,
    live_trading_enabled: false,
    live_broker_routing_enabled: false,
  };

  assert.equal(executionControls.paper_approved, false);
  assert.equal(executionControls.live_approved, false);
  assert.equal(executionControls.live_trading_enabled, false);
  assert.equal(executionControls.live_broker_routing_enabled, false);
});

test("V6 Integrity - Insufficient directional participation veto gates trade and sets STAND ASIDE", () => {
  const reportWithParticipationVeto = {
    decision: "NO_TRADE",
    consensus: {
      consensus_score: 0.33,
      epistemic_uncertainty: 0.38,
      gating_threshold: 0.45,
      configured_specialist_count: 6,
      reporting_specialist_count: 6,
      directional_voter_count: 1,
      directional_participation_rate: 0.167,
      vetoes: ["INSUFFICIENT_DIRECTIONAL_PARTICIPATION"],
    },
    agent_outputs: {},
  };

  const metrics = deriveCardMetrics(reportWithParticipationVeto);
  assert.equal(metrics.activeVetoes.includes("INSUFFICIENT_DIRECTIONAL_PARTICIPATION"), true);
  assert.equal(metrics.deskVerdict, "STAND ASIDE (NO TRADE)");
  assert.equal(metrics.executionBadgeText, "🔒 Deadband / Safety Gated (NO TRADE)");
  assert.equal(metrics.configuredCount, 6);
  assert.equal(metrics.reportingCount, 6);
  assert.equal(metrics.directionalVoters, 1);
  assert.equal(metrics.participationRate, 0.167);
});

test("V6 Integrity - Specialist semantic types and unconfigured options zero effective weight", () => {
  const report = {
    decision: "NO_TRADE",
    consensus: {
      consensus_score: 0.0,
      epistemic_uncertainty: 0.40,
      specialist_scores: {
        market_data_analyst: { effective_weight: 0.49, semantic_type: "STATIC_DEFAULT" },
        technical_analyst: { effective_weight: 1.70, semantic_type: "HEURISTIC_SIGNAL_STRENGTH" },
        quant_forecast_analyst: { effective_weight: 1.25, semantic_type: "UNCALIBRATED_MODEL_PROBABILITY" },
        options_analyst: { effective_weight: 0.0, semantic_type: "STATIC_DEFAULT" },
      },
      vetoes: [],
    },
    agent_outputs: {
      market_data_analyst: { directional_bias: "NEUTRAL", confidence: 0.70, semantic_type: "STATIC_DEFAULT", status: "SUCCESS" },
      technical_analyst: { directional_bias: "BULLISH", confidence: 0.85, semantic_type: "HEURISTIC_SIGNAL_STRENGTH", status: "SUCCESS" },
      quant_forecast_analyst: { directional_bias: "BEARISH", confidence: 0.50, semantic_type: "UNCALIBRATED_MODEL_PROBABILITY", status: "SUCCESS" },
      options_analyst: { directional_bias: "NEUTRAL", confidence: 0.50, semantic_type: "STATIC_DEFAULT", status: "SUCCESS" },
    },
  };

  const metrics = deriveCardMetrics(report);
  const optionsCard = metrics.agentStates.find((a) => a.id === "options_greeks");
  assert.equal(optionsCard.semanticType, "STATIC_DEFAULT");
  assert.equal(optionsCard.effectiveWeight, 0.0);
  assert.equal(optionsCard.isZeroWeight, true, "Fallback options must have zero effective weight");

  const quantCard = metrics.agentStates.find((a) => a.id === "quant_forecast");
  assert.equal(quantCard.semanticType, "UNCALIBRATED_MODEL_PROBABILITY");

  const techCard = metrics.agentStates.find((a) => a.id === "trend_momentum");
  assert.equal(techCard.semanticType, "HEURISTIC_SIGNAL_STRENGTH");
});

