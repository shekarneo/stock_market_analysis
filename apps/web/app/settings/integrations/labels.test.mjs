import assert from "node:assert/strict";
import test from "node:test";

import {
  connectionLabel,
  credentialLabel,
  diagnosticPreview,
  diagnosticSubmitAllowed,
  expiryLabel,
  growwSavePlan,
  historicalLabel,
  integrationLabel,
  lifecycleKind,
  lifecycleLabel,
  maskedSecret,
  openaiSavePlan,
  safetySummary,
  secretIndicator,
  wallSpanMinutes,
} from "./labels.mjs";

test("lifecycle states accurately distinguish all lifecycle phases", () => {
  assert.equal(lifecycleLabel("CONNECTED"), "Connected");
  assert.equal(lifecycleKind("CONNECTED"), "ok");

  assert.equal(lifecycleLabel("CONFIGURED"), "Configured (Not Tested)");
  assert.equal(lifecycleKind("CONFIGURED"), "wait");

  assert.equal(lifecycleLabel("CONNECTION_FAILED"), "Connection Failed");
  assert.equal(lifecycleKind("CONNECTION_FAILED"), "bad");

  assert.equal(lifecycleLabel("EXPIRED_OR_REAUTH_REQUIRED"), "Token Expired (Reauth Required)");
  assert.equal(lifecycleKind("EXPIRED_OR_REAUTH_REQUIRED"), "bad");

  assert.equal(lifecycleLabel("DISCONNECTED"), "Disconnected");
  assert.equal(lifecycleKind("DISCONNECTED"), "idle");

  assert.equal(lifecycleLabel("NOT_CONFIGURED"), "Not Configured");
  assert.equal(lifecycleKind("NOT_CONFIGURED"), "idle");
});

test("connection success is separate from integration enablement", () => {
  assert.equal(connectionLabel(true), "Connection Successful");
  assert.equal(connectionLabel(false), "Connection Failed");
  assert.equal(connectionLabel(null), "Not Tested");
  assert.equal(integrationLabel(false), "Disabled");
  assert.equal(integrationLabel(true), "Enabled");
  assert.equal(credentialLabel(true), "Credentials Saved");
  assert.equal(credentialLabel(false), "Credentials Missing");
  assert.notEqual(connectionLabel(true), integrationLabel(true));
});

test("token and historical badges do not treat unknown as verified", () => {
  assert.equal(expiryLabel("VALID"), "Token Valid");
  assert.equal(expiryLabel("EXPIRED"), "Token Expired");
  assert.equal(expiryLabel("UNVERIFIABLE"), "Token Unverifiable");
  assert.equal(historicalLabel("verified"), "Historical Data Verified");
  assert.equal(historicalLabel("quarantined_unverified"), "Historical Data Unverified");
  assert.equal(historicalLabel("unverified"), "Historical Data Unverified");
  assert.equal(historicalLabel("not_tested"), "Historical Data Not Tested");
  assert.equal(historicalLabel(undefined), "Historical Data Not Tested");
});

test("saved secrets stay masked and empty in the draft", () => {
  assert.equal(secretIndicator(true), "Saved");
  assert.equal(secretIndicator(false), "Missing");
  assert.equal(maskedSecret(true), "••••••••");
  assert.equal(maskedSecret(false), "");
  assert.equal(maskedSecret(true).includes("sk-"), false);
});

test("opening configuration does not save until an explicit confirmed action", () => {
  const opened = growwSavePlan({
    method: "api_key_secret",
    savedMethod: "api_key_secret",
    enabled: false,
    savedEnabled: false,
    secretsEntered: false,
    confirmEnable: false,
  });
  assert.deepEqual(opened.steps, []);
  assert.equal(opened.blocked, "UNCHANGED");
  const unconfirmed = growwSavePlan({
    method: "api_key_secret",
    savedMethod: "api_key_secret",
    enabled: true,
    savedEnabled: false,
    secretsEntered: false,
    confirmEnable: false,
  });
  assert.equal(unconfirmed.blocked, "CONFIRMATION_REQUIRED");
  assert.deepEqual(unconfirmed.steps, []);
  const confirmed = growwSavePlan({
    method: "api_key_secret",
    savedMethod: "api_key_secret",
    enabled: true,
    savedEnabled: false,
    secretsEntered: false,
    confirmEnable: true,
  });
  assert.deepEqual(confirmed.steps, ["set-enabled"]);
  const modelOnly = openaiSavePlan({
    model: "gpt-6-luna",
    savedModel: "gpt-4.1-mini",
    label: "openai",
    savedLabel: "openai",
    enabled: true,
    savedEnabled: true,
    keyEntered: false,
    confirmEnable: false,
  });
  assert.deepEqual(modelOnly.steps, ["save-profile"]);
  assert.equal(modelOnly.blocked, null);
});

test("diagnostic stays blocked until the integration is enabled and the request is confirmed", () => {
  const preview = diagnosticPreview({
    exchange: "NSE",
    segment: "CASH",
    groww_symbol: "NSE-NIFTY",
    candle_interval: "1minute",
    start: "2026-10-13T09:15",
    end: "2026-10-13T09:45",
  });
  assert.match(preview, /GET \/v1\/historical\/candles/);
  assert.equal(wallSpanMinutes("2026-10-13T09:15", "2026-10-13T09:45"), 30);
  assert.equal(diagnosticSubmitAllowed({ enabled: false, confirmed: true, span: 30 }).code, "INTEGRATION_DISABLED");
  assert.equal(diagnosticSubmitAllowed({ enabled: true, confirmed: false, span: 30 }).code, "CONFIRMATION_REQUIRED");
  assert.equal(diagnosticSubmitAllowed({ enabled: true, confirmed: true, span: 45 }).code, "RANGE");
  assert.equal(diagnosticSubmitAllowed({ enabled: true, confirmed: true, span: 30 }).ok, true);
});

test("safety flags stay off unless the server says otherwise", () => {
  const flags = safetySummary({ live_trading_enabled: false, paper_approved: false, real_market_data_verified: false });
  assert.equal(flags.liveTrading, "Off");
  assert.equal(flags.paper, "Not approved");
  assert.equal(flags.marketData, "Unverified");
});
