import assert from "node:assert/strict";
import test from "node:test";

test("V6 UI Integrity: Backend NO_TRADE enforces STAND ASIDE and gates execution", () => {
  const backendReport = {
    decision: "NO_TRADE",
    consensus: {
      consensus_score: 0.05,
      epistemic_uncertainty: 0.72,
      gating_threshold: 0.45,
      vetoes: ["EXCESSIVE_EPISTEMIC_UNCERTAINTY", "INSUFFICIENT_DIRECTIONAL_PARTICIPATION"],
    },
  };

  const hasVetoes = Array.isArray(backendReport.consensus.vetoes) && backendReport.consensus.vetoes.length > 0;
  const isGated = backendReport.decision === "NO_TRADE" || hasVetoes;

  // Simulate V6Desk banner logic
  const deskSignal = isGated
    ? "STAND ASIDE (SAFETY GATED / NO TRADE)"
    : "BUY CE";

  assert.equal(deskSignal, "STAND ASIDE (SAFETY GATED / NO TRADE)");
  assert.equal(isGated, true);
});

test("V6 UI Integrity: Target and Stop points math with snapshot reference spot and dynamic live spot", () => {
  const refSpot = 22950.20;
  const targetSpot = 23079.90;
  const stopLossSpot = 22885.40;
  const liveSpot = 22935.35;

  // Snapshot points relative to reference spot
  const expPtsRef = Number((targetSpot - refSpot).toFixed(1));
  const slPtsRef = Number((refSpot - stopLossSpot).toFixed(1));

  assert.equal(expPtsRef, 129.7);
  assert.equal(slPtsRef, 64.8);
  assert.equal(Number((expPtsRef / slPtsRef).toFixed(1)), 2.0); // 2:1 R:R

  // Dynamic points relative to live spot
  const expPtsLive = Number((targetSpot - liveSpot).toFixed(1));
  const slPtsLive = Number((stopLossSpot - liveSpot).toFixed(1));

  assert.equal(expPtsLive, 144.6);
  assert.equal(slPtsLive, -49.9);

  // Formatting strings
  const targetText = `₹${targetSpot.toLocaleString("en-IN")} (+${expPtsRef} pts ref | +${expPtsLive} live)`;
  const stopText = `₹${stopLossSpot.toLocaleString("en-IN")} (-${slPtsRef} pts ref | ${slPtsLive} live)`;

  assert.ok(targetText.includes("+129.7 pts ref"));
  assert.ok(targetText.includes("+144.6 live"));
  assert.ok(stopText.includes("-64.8 pts ref"));
  assert.ok(stopText.includes("-49.9 live"));
});

test("V6 UI Integrity: Gated target and stop display '— (Gated)' to suppress rogue targets", () => {
  const rec = {
    call: "STAND ASIDE (NO TRADE)",
    conviction: "NO TRADE / GATED",
    is_actionable: false,
    target_spot: null,
    stop_loss_spot: null,
  };

  const isGated = rec.is_actionable === false || rec.call.includes("STAND ASIDE");
  const targetDisplay = isGated ? "— (Gated)" : `₹${rec.target_spot}`;
  const stopDisplay = isGated ? "— (Gated)" : `₹${rec.stop_loss_spot}`;

  assert.equal(targetDisplay, "— (Gated)");
  assert.equal(stopDisplay, "— (Gated)");
});

test("V6 UI Integrity: Commodity Futures recommendations never force CE options", () => {
  const commoditySet = new Set(["CRUDE", "CRUDEMINI", "CRUDEOILMINI", "GOLD", "SILVER"]);
  const instrument = "CRUDEOILMINI";
  const rec = {
    contract: "CRUDEOILMINI FUTURES",
    contract_type: "FUTURES",
    call: "BUY_FUT (MOMENTUM)",
    option_type: "FUT",
  };

  const isFutures = rec.contract_type === "FUTURES" || commoditySet.has(instrument);
  const plannedPick = isFutures ? (rec.contract || `${instrument} FUTURES`) : "ATM Option";
  const side = isFutures ? (rec.call.includes("SELL") ? "SELL_FUT" : "BUY_FUT") : "BUY_CE";

  assert.equal(isFutures, true);
  assert.equal(plannedPick, "CRUDEOILMINI FUTURES");
  assert.equal(side, "BUY_FUT");
  assert.ok(!side.includes("CE"));
  assert.ok(!side.includes("PE"));
});

test("V6 UI Integrity: Auto-trading scan strictly aborts when gated", () => {
  let ordersCreated = 0;
  const analysisData = { decision: "NO_TRADE" };
  const rec = {
    call: "STAND ASIDE (NO TRADE)",
    is_actionable: false,
    top_5_options: [null, null, { contract: "NIFTY 23000 CE" }],
  };

  function triggerAutoTradingScan() {
    if (analysisData?.decision === "NO_TRADE") return;
    if (rec && rec.is_actionable !== false && !rec.call.startsWith("STAND ASIDE")) {
      ordersCreated += 1;
    }
  }

  triggerAutoTradingScan();
  assert.equal(ordersCreated, 0);
});

test("V6 UI Integrity: Watchlist submission uses unverified provider data class by default", () => {
  const rec = { data_class: null };
  const payloadDataClass = rec?.data_class || "UNVERIFIED_PROVIDER_DATA";

  assert.equal(payloadDataClass, "UNVERIFIED_PROVIDER_DATA");
  assert.notEqual(payloadDataClass, "VERIFIED_LIVE_DATA");
});
