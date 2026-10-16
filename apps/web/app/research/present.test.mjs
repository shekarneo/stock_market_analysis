import assert from "node:assert/strict";
import test from "node:test";

import { intentIdProblem, observationClass, valueText } from "./present.mjs";

test("null and missing values stay distinct from zero", () => {
  assert.equal(valueText(null), "not set");
  assert.equal(valueText(undefined), "not returned");
  assert.equal(valueText(0), "0");
  assert.equal(valueText(false), "false");
  assert.equal(valueText(""), "not set");
});

test("observations use the payload class and do not invent a price", () => {
  assert.equal(observationClass({ origin: "SYNTHETIC", last_price: 10, live_market_data: false }).code, "synthetic");
  assert.equal(observationClass({ origin: "SYNTHETIC", issues: [{ code: "STALE_QUOTE" }] }).code, "stale");
  assert.equal(observationClass({ data_category: "UNVERIFIED_PROVIDER", trusted_dataset_created: false }).code, "quarantined");
  assert.equal(observationClass({ quarantine_id: "abc", trusted_dataset_created: false }).code, "quarantined");
  assert.equal(observationClass({ origin: "PROVIDER", live_market_data: false, real_market_data_verified: false }).code, "unverified");
  assert.equal(observationClass({ origin: "PROVIDER", live_market_data: true, real_market_data_verified: true }).code, "verified");
  assert.equal(observationClass({ origin: "DOCUMENTED_SAMPLE" }).code, "documented-sample");
  assert.equal(observationClass({}).code, "unavailable");
  assert.equal(observationClass(null).code, "unavailable");
});

test("intent lookup rejects an empty or spaced id before a request", () => {
  assert.equal(intentIdProblem(""), "Enter an intent id.");
  assert.match(intentIdProblem("bad id"), /malformed/);
  assert.match(intentIdProblem("a/b"), /malformed/);
  assert.equal(intentIdProblem("intent-1"), "");
});
