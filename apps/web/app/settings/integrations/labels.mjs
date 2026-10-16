export function connectionLabel(lastTestOk) {
  if (lastTestOk === true) return "Connection Successful";
  if (lastTestOk === false) return "Connection Failed";
  return "Not Tested";
}

export function credentialLabel(configured) {
  return configured ? "Credentials Saved" : "Credentials Missing";
}

export function integrationLabel(enabled) {
  return enabled === true ? "Enabled" : "Disabled";
}

export function expiryLabel(status) {
  if (status === "VALID") return "Token Valid";
  if (status === "EXPIRED") return "Token Expired";
  return "Token Unverifiable";
}

export function historicalLabel(status) {
  if (status === "verified") return "Historical Data Verified";
  if (status === "unverified" || status === "quarantined_unverified") return "Historical Data Unverified";
  return "Historical Data Not Tested";
}

export function secretIndicator(saved) {
  return saved ? "Saved" : "Missing";
}

export function maskedSecret(saved) {
  return saved ? "••••••••" : "";
}

export function safetySummary(status) {
  return {
    liveTrading: status?.live_trading_enabled === true ? "On" : "Off",
    paper: status?.paper_approved === true ? "Approved" : "Not approved",
    marketData: status?.real_market_data_verified === true ? "Verified" : "Unverified",
  };
}

export function growwSavePlan({ method, savedMethod, enabled, savedEnabled, secretsEntered, confirmEnable }) {
  const replacingCredentials = Boolean(secretsEntered) || method !== savedMethod;
  const enableChanged = enabled !== savedEnabled;
  if (!replacingCredentials && !enableChanged) return { steps: [], blocked: "UNCHANGED" };
  if (method !== savedMethod && !secretsEntered) return { steps: [], blocked: "CREDENTIALS_REQUIRED" };
  if (enableChanged && !confirmEnable) return { steps: [], blocked: "CONFIRMATION_REQUIRED" };
  const steps = [];
  if (secretsEntered) steps.push("save-credentials");
  if (enableChanged) steps.push("set-enabled");
  return { steps, blocked: null };
}

export function openaiSavePlan({ model, savedModel, label, savedLabel, enabled, savedEnabled, keyEntered, confirmEnable }) {
  const profileChanged = model !== savedModel || label !== savedLabel;
  const enableChanged = enabled !== savedEnabled;
  if (!profileChanged && !enableChanged && !keyEntered) return { steps: [], blocked: "UNCHANGED" };
  if (enableChanged && !confirmEnable) return { steps: [], blocked: "CONFIRMATION_REQUIRED" };
  const steps = [];
  if (keyEntered) steps.push("save-credentials");
  else if (profileChanged) steps.push("save-profile");
  if (enableChanged) steps.push("set-enabled");
  return { steps, blocked: null };
}

export function diagnosticSubmitAllowed({ enabled, confirmed, span }) {
  if (enabled !== true) return { ok: false, code: "INTEGRATION_DISABLED" };
  if (span === null || span <= 0 || span > 30) return { ok: false, code: "RANGE" };
  if (!confirmed) return { ok: false, code: "CONFIRMATION_REQUIRED" };
  return { ok: true, code: "READY" };
}

export function wallSpanMinutes(start, end) {
  const left = wall(start);
  const right = wall(end);
  if (left === null || right === null) return null;
  return (right - left) / 60000;
}

export function diagnosticPreview(fields) {
  return [
    "GET /v1/historical/candles",
    `exchange=${fields.exchange}`,
    `segment=${fields.segment}`,
    `groww_symbol=${fields.groww_symbol}`,
    `candle_interval=${fields.candle_interval}`,
    `start_time=${fields.start.replace("T", " ")}`,
    `end_time=${fields.end.replace("T", " ")}`,
  ].join("\n");
}

function wall(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value || "");
  if (!match) return null;
  return Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(match[4]), Number(match[5]));
}
