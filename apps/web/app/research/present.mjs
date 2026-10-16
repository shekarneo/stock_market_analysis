export function valueText(value) {
  if (value === undefined) return "not returned";
  if (value === null) return "not set";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "not a number";
  if (typeof value === "string") return value.trim() ? value : "not set";
  return "not a scalar";
}

export function observationClass(input) {
  if (!input || typeof input !== "object" || input.present === false) {
    return { code: "unavailable", label: "Unavailable" };
  }
  const issues = Array.isArray(input.issues) ? input.issues : [];
  const stale = issues.some((item) => item && (item.code === "STALE_QUOTE" || item.code === "STALE_INDEX_LTP"));
  if (input.quarantined === true || input.data_category === "UNVERIFIED_PROVIDER" || (input.quarantine_id && input.trusted_dataset_created === false)) {
    return { code: "quarantined", label: "Quarantined" };
  }
  if (stale) return { code: "stale", label: "Stale" };
  if (input.real_market_data_verified === true && input.live_market_data === true) {
    return { code: "verified", label: "Verified" };
  }
  if (input.origin === "SYNTHETIC") return { code: "synthetic", label: "Synthetic" };
  if (input.origin === "DOCUMENTED_SAMPLE") return { code: "documented-sample", label: "Documented sample" };
  if (input.quality === "FAIL" || (input.origin == null && input.last_price == null && input.value == null)) {
    return { code: "unavailable", label: "Unavailable" };
  }
  return { code: "unverified", label: "Unverified" };
}

export function intentIdProblem(value) {
  const text = String(value ?? "");
  if (!text) return "Enter an intent id.";
  if (text !== text.trim() || /\s/.test(text) || text.length > 200 || text.includes("/")) {
    return "That intent id is malformed.";
  }
  return "";
}
