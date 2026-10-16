export function killSwitchLabel(value) {
  if (value == null) return "Not read";
  if (value.enabled === true) return "ON";
  if (value.enabled === false) return "OFF";
  return "Unknown";
}

export function flagLabel(value) {
  if (value === true) return "True";
  if (value === false) return "False";
  return "Unknown";
}

export function paperLabel(value) {
  if (value === true) return "Active";
  if (value === false) return "Disabled";
  return "Unknown";
}

export function fillLabel(value) {
  if (value === true) return "Persisted";
  if (value === false) return "None persisted";
  if (value === null) return "not set";
  return "not returned";
}
