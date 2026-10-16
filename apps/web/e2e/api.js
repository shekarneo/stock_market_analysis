const status = {
  paper_trading_active: false,
  forecast_ready: false,
  paper_approved: false,
  live_approved: false,
  real_market_data_verified: false,
  live_trading_enabled: false,
  configured_live_trading_enabled: false,
  unattended_orders: false,
  mode: "PAPER",
  kill_switch: { read: true, enabled: false },
  risk_capital_inr: null,
  holiday_calendar_source_id: null,
  market_data: "unverified",
  fills_persisted: false,
  broker_called: false,
  blockers: [
    { code: "MISSING_RISK_CAPITAL", class: "operator" },
    { code: "MARKET_DATA_UNVERIFIED", class: "external" },
  ],
};

const snapshot = {
  ok: true,
  provider: "synthetic",
  origin: "SYNTHETIC",
  live_market_data: false,
  orders_enabled: false,
  as_of: "2026-10-15T09:15:00+05:30",
  quotes: [
    {
      underlying: "NIFTY",
      last_price: 11111.5,
      origin: "SYNTHETIC",
      quality: "WARN",
      event_timestamp: "2026-10-15T09:15:00+05:30",
      issues: [{ code: "STALE_QUOTE" }],
    },
  ],
  context: [{ code: "BRENT", value: null, unit: "USD" }],
  failures: [],
  readiness: { data_ready: false, proposal_blocked: true, reasons: ["STALE_INDEX_LTP"] },
};

const quarantine = {
  records: [
    {
      quarantine_id: "q-1",
      instrument: "NIFTY",
      interval: "M15",
      data_category: "UNVERIFIED_PROVIDER",
      trusted_dataset_created: false,
      candle_count: 4,
    },
  ],
  trusted_dataset_created: false,
  forecast_eligible: false,
  real_market_data_verified: false,
};

const proposal = {
  decision: "NO_TRADE",
  status: "INCOMPLETE",
  executable: false,
  order_connected: false,
  expected_net: null,
  gross_expected: null,
  live_trading_enabled: false,
  quote: { premium: null, bid: null, ask: null },
  modelled_value: { value: null, status: "UNAVAILABLE" },
  charges: { amount: null },
  scenarios: { status: "UNAVAILABLE" },
  identity: { underlying: null, expiry: null, strike: null, option_type: null, lot_size: null, tick_size: null, quantity: null },
  decision_reasons: ["INVALID_CONTRACT", "MISSING_ENTRY_TRIGGER"],
  approvals: { paper_approved: false, live_approved: false },
  risk: { gates: [{ name: "expected_net", state: "VETO", applied: true, detail: "EXPECTED_NET_UNAVAILABLE" }] },
};

const analysisReport = {
  status: "INSUFFICIENT_DATA",
  decision: "NO_TRADE",
  forecast_ready: false,
  paper_approved: false,
  live_approved: false,
  real_market_data_verified: false,
  directional_assessment: null,
  missing: ["news", "derivatives"],
  provider_errors: [{ code: "PROVIDER_UNAVAILABLE" }],
  contradictions: [],
  limitations: ["No probability was calculated."],
  intelligence: {
    stages: [
      { name: "Fresh verified news", status: "MISSING_DATA", detail: "No authorized article was supplied." },
      { name: "Final decision", status: "NO_TRADE", detail: "BUY, SELL, and WAIT are outside the enforced contract." },
    ],
    news: [],
    geopolitics: [],
    forecast: { probabilities: null, expected_move: null, reason: "No validated class-conditional return is configured." },
    decision: { decision: "NO_TRADE" },
  },
};

const accounting = {
  event_types: ["LOCKOUT_CLEAR", "LOCKOUT_SET", "RELEASE", "RESERVE"],
  fill_accepted: false,
  fills_persisted: false,
  paper_cash_rule: "equals_configured_capital_when_capital_is_set_otherwise_null",
  open_premium_rule: "must_remain_zero",
  position_count_rule: "must_remain_zero",
  partial_release: "PARTIAL_RELEASE_UNDEFINED",
  missing_charge: "unknown_not_zero",
  reconciliation_tolerance: null,
  broker_snapshot: null,
  paper_trading_active: false,
  live_trading_enabled: false,
  broker_called: false,
};

const models = {
  models: [
    {
      model_id: "last_return_sign",
      version: "v1",
      version_id: "last_return_sign:v1",
      status: "TRAINED",
      origin: "SYNTHETIC",
      training_dataset_id: "dataset-1",
      training_dataset_checksum: "abc",
      last_evaluated_at: null,
      forecast_ready: false,
      paper_approved: false,
      live_approved: false,
      real_market_data_verified: false,
    },
  ],
  forecast_ready: false,
  paper_approved: false,
  live_approved: false,
  real_market_data_verified: false,
};

const experiments = {
  holdout: [
    {
      ok: true,
      experiment_id: "hold-1",
      origin: "SYNTHETIC",
      dataset_id: "dataset-1",
      instrument: "NIFTY",
      horizon: "M15",
      selected_model: null,
      incomplete: false,
      aggregate: { log_loss: null },
    },
  ],
  walk_forward: [],
  forecast_ready: false,
};

const forecasts = { forecasts: [], forecast_ready: false, note: "NOT_AVAILABLE" };

const candidateResult = {
  ok: true,
  schema_version: "options-candidate-1",
  provenance: "EXPLICIT_LOCAL_FIXTURE",
  tradable: false,
  listed: null,
  decision: "NO_TRADE",
  expected_net: null,
  expected_return: null,
  forecast_ready: false,
  paper_approved: false,
  live_approved: false,
  real_market_data_verified: false,
  live_trading_enabled: false,
  decision_record: { schema_version: "research-decision-1", decision: "NO_TRADE", model_ids: ["last_return_sign"], holdout_ids: ["hold-1"], walk_forward_ids: [] },
  identity: [
    { field: "underlying", status: "supplied", value: "NIFTY", verified: false, reason: null },
    { field: "expiry", status: "missing", value: null, verified: false, reason: null },
    { field: "strike", status: "supplied", value: 25000, verified: false, reason: null },
    { field: "option_type", status: "supplied", value: "CE", verified: false, reason: null },
  ],
  evidence: [
    { name: "option_quote", status: "missing", reason: "MISSING_OPTION_QUOTE", premium: null, verified: false },
    { name: "charges", status: "unavailable", reason: "CHARGES_UNVERIFIED", premium: null, verified: false },
    { name: "index_observation", status: "observed", reason: "INDEX_PRICE_IS_NOT_AN_OPTION_PREMIUM", premium: null, verified: false },
  ],
  blockers: [
    { code: "TRADABILITY_NOT_ESTABLISHED", detail: "A local fixture does not establish that the contract is listed or tradable." },
    { code: "MISSING_EXPIRY", detail: "expiry was not supplied." },
    { code: "CHARGES_UNVERIFIED", detail: "charges" },
  ],
};

const replay = {
  intent_id: "intent-1",
  state: "VETOED",
  fill: null,
  simulated_fill: null,
  expected_net: null,
  snapshot_conflict: false,
  paper_trading_active: false,
  missing: ["quote", "charges_per_lot"],
  attempts: [{ audit_id: 1, code: "VETOED", reasons: ["MODEL_NOT_APPROVED"] }],
};

const unknownReplay = {
  intent_id: "missing-intent",
  state: null,
  fill: null,
  simulated_fill: null,
  expected_net: null,
  snapshot_conflict: false,
  paper_trading_active: false,
  missing: ["snapshot"],
  attempts: [],
};

function json(body, status = 200) {
  return { status, contentType: "application/json", body: JSON.stringify(body) };
}

function responseFor(pathname, overrides) {
  if (overrides[pathname]) return overrides[pathname];
  if (pathname === "/health") {
    return json({ status: "ok", database: true, mode: "PAPER", live_trading_enabled: false, live_order_server_flag: false, kill_switch: false });
  }
  if (pathname === "/api/research/status") return json(status);
  if (pathname === "/api/research/decision") {
    return json({
      schema_version: "research-decision-1",
      decision: "NO_TRADE",
      status: "INCOMPLETE",
      executable: false,
      expected_net: null,
      expected_return: null,
      paper_trading_active: false,
      forecast_ready: false,
      paper_approved: false,
      live_approved: false,
      real_market_data_verified: false,
      live_trading_enabled: false,
      broker_called: false,
      quarantine_promoted: false,
      underlying: "NIFTY",
      market: {
        status: "observed",
        provider: "synthetic",
        origin: "SYNTHETIC",
        data_class: "synthetic",
        stale: true,
        verified: false,
        quarantined: false,
        last_price: 11111.5,
        used_as_option_premium: false,
      },
      forecast_research: {
        forecast_ready: false,
        expected_return: null,
        used_as_expected_return: false,
        models: [{ model_id: "last_return_sign", version: "v1", origin: "SYNTHETIC" }],
        holdout_ids: ["hold-1"],
        walk_forward_ids: [],
      },
      missing_inputs: {
        contract: [{ field: "expiry", status: "missing", value: null }],
        quote: [{ field: "premium", status: "missing", value: null }],
        cost: [{ field: "charges", status: "unavailable", value: null, reason: "CHARGES_UNVERIFIED" }],
        risk: [{ code: "MISSING_RISK_CAPITAL", class: "operator" }],
        forecast: [{ field: "expected_return", status: "unavailable", value: null, reason: "NO_APPROVED_FORECAST" }],
      },
    });
  }
  if (pathname === "/api/market/snapshot") return json(snapshot);
  if (pathname === "/api/market/live-quotes") return json({ status: "NOT_READ", quotes: [], real_market_data_verified: false, message: "No Groww quote read is stored." });
  if (pathname === "/api/news") return json({ status: "NOT_READ", count: 0, items: [], feeds: [], directional_implication: "UNKNOWN", decision: "NO_TRADE" });
  if (pathname === "/api/history/quarantine") return json(quarantine);
  if (pathname === "/api/history/capabilities") return json({ status: "CANDLE_BOUNDARY_UNVERIFIED", real_market_data_verified: false, forecast_ready: false });
  if (pathname === "/api/history/datasets") return json({ datasets: [], real_market_data_verified: false, forecast_ready: false });
  if (pathname === "/api/options/research") return json(proposal);
  if (pathname === "/api/accounting/status") return json(accounting);
  if (pathname === "/api/models") return json(models);
  if (pathname === "/api/experiments") return json(experiments);
  if (pathname === "/api/forecasts") return json(forecasts);
  if (pathname === "/api/models/activations") return json({ research_selections: [], paper_slot: null, live_slot: null, forecast_ready: false, paper_approved: false, live_approved: false });
  if (pathname === "/api/paper/simulations/intent-1") return json(replay);
  if (pathname === "/api/paper/simulations/missing-intent") return json(unknownReplay);
  if (pathname === "/api/integrations") return json({ code: "UNAUTHENTICATED", message: "Sign in required." }, 401);
  if (pathname === "/api/session") return json({ code: "UNAUTHENTICATED", message: "Sign in required." }, 401);
  return json({ message: `Unmocked ${pathname}` }, 500);
}

async function installApi(page, overrides = {}) {
  const calls = [];
  let signedIn = false;
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname !== "/health" && !url.pathname.startsWith("/api/")) {
      await route.continue();
      return;
    }
    calls.push({ method: route.request().method(), path: url.pathname });
    if (route.request().method() === "POST" && url.pathname === "/api/session/login") {
      signedIn = true;
      await route.fulfill(overrides[url.pathname] || json({ actor: "operator" }));
      return;
    }
    if (route.request().method() === "POST" && url.pathname === "/api/session/logout") {
      signedIn = false;
      await route.fulfill(overrides[url.pathname] || json({ actor: null }));
      return;
    }
    if (route.request().method() === "POST" && url.pathname === "/api/account/signup") {
      signedIn = true;
      await route.fulfill(overrides[url.pathname] || json({ actor: "operator", username: "neo", display_name: "Neo", source: "database" }, 201));
      return;
    }
    if (route.request().method() === "GET" && url.pathname === "/api/account/status" && !overrides[url.pathname]) {
      await route.fulfill(json({ account_exists: false, signup_open: true, login_source: "environment" }));
      return;
    }
    if (route.request().method() === "GET" && url.pathname === "/api/session" && !overrides[url.pathname]) {
      await route.fulfill(signedIn
        ? json({ actor: "operator", username: "neo", display_name: "Neo", timezone: "Asia/Kolkata", stored: true, source: "database", created_at: "2026-10-15T00:00:00+00:00", last_login_at: null })
        : json({ code: "UNAUTHENTICATED", message: "Sign in required." }, 401));
      return;
    }
    if (route.request().method() !== "GET") {
      if (url.pathname === "/api/options/candidates") {
        await route.fulfill(overrides[url.pathname] || json(candidateResult));
        return;
      }
      if (url.pathname === "/api/market-analysis") {
        await route.fulfill(overrides[url.pathname] || json(analysisReport));
        return;
      }
      if (url.pathname === "/api/news/refresh") {
        await route.fulfill(overrides[url.pathname] || json({
          status: "READ",
          count: 1,
          decision: "NO_TRADE",
          directional_implication: "UNKNOWN",
          items: [{ claim: "Nifty ends flat", source_name: "Example", source_url: "https://news.example/nifty", published_at: "2026-10-15T03:30:00+00:00", summary: "" }],
          feeds: [],
        }));
        return;
      }
      if (url.pathname === "/api/market/live-quotes") {
        await route.fulfill(overrides[url.pathname] || json({
          status: "READ",
          real_market_data_verified: false,
          quotes: [
            { instrument: "NIFTY", last_price: 24500.5, data_class: "UNVERIFIED_PROVIDER_DATA", event_timestamp: "2026-10-15T04:00:00+00:00" },
            { instrument: "SENSEX", last_price: 80123.25, data_class: "UNVERIFIED_PROVIDER_DATA", event_timestamp: null },
          ],
        }));
        return;
      }
      await route.fulfill(json({ code: "REFUSED", message: "This test does not submit writes." }, 422));
      return;
    }
    await route.fulfill(responseFor(url.pathname, overrides));
  });
  return calls;
}

module.exports = { installApi, snapshot };
