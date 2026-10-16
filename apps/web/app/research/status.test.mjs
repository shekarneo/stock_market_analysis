import assert from "node:assert/strict";
import test from "node:test";

import { fillLabel, flagLabel, killSwitchLabel, paperLabel } from "./status.mjs";

test("a missing kill switch is not labelled off", () => {
  assert.equal(killSwitchLabel(null), "Not read");
  assert.equal(killSwitchLabel(undefined), "Not read");
  assert.equal(killSwitchLabel({ read: true, enabled: false }), "OFF");
  assert.equal(killSwitchLabel({ read: true, enabled: true }), "ON");
  assert.equal(flagLabel(false), "False");
  assert.equal(flagLabel(null), "Unknown");
  assert.equal(paperLabel(false), "Disabled");
  assert.equal(paperLabel(null), "Unknown");
  assert.equal(fillLabel(false), "None persisted");
  assert.equal(fillLabel(null), "not set");
  assert.equal(fillLabel(undefined), "not returned");
});
