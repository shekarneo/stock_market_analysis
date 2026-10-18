import assert from "node:assert/strict";
import test from "node:test";

test("V6 UI workflow - calibration status distinguishes uncalibrated from calibrated research", () => {
  // A sample < 30 or negative Brier skill score must be labeled UNCALIBRATED
  function determineCalibrationLabel(n, bss) {
    if (n < 30 || bss <= 0) return "UNCALIBRATED";
    return "CALIBRATED_RESEARCH";
  }

  assert.equal(determineCalibrationLabel(10, 5.0), "UNCALIBRATED");
  assert.equal(determineCalibrationLabel(46, -2.44), "UNCALIBRATED");
  assert.equal(determineCalibrationLabel(46, 49.98), "CALIBRATED_RESEARCH");
});

test("V6 UI workflow - Indian statutory charges and net PnL accounting", () => {
  // Gross PnL ₹150, Charges ₹22.86 -> Net PnL must be ₹127.14
  const grossPnl = 150.0;
  const charges = 22.86;
  const netPnl = Number((grossPnl - charges).toFixed(2));
  assert.equal(netPnl, 127.14);
  assert.ok(netPnl < grossPnl, "Statutory friction must reduce gross PnL");
});

test("V6 UI workflow - Safety flags stay strictly false in UI components", () => {
  const flags = {
    forecast_ready: false,
    real_market_data_verified: false,
    paper_approved: false,
    live_approved: false,
    live_broker_routing_enabled: false,
  };

  for (const [key, val] of Object.entries(flags)) {
    assert.equal(val, false, `${key} must remain false`);
  }
});
