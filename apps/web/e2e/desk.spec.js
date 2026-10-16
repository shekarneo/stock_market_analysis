const { test, expect } = require("@playwright/test");

const { installApi } = require("./api");

const PAGES = [
  ["/", "Sign in"],
  ["/signup", "Create account"],
  ["/settings", "Profile"],
  ["/dashboard", "Trade desk"],
  ["/history", "Historical data"],
  ["/analysis", "Analysis"],
  ["/forecast", "Forecasts"],
  ["/studio", "Forecast Model Studio"],
  ["/backtest", "Walk-forward"],
  ["/options", "Options strategy"],
  ["/risk", "Portfolio"],
  ["/paper", "Paper trading"],
  ["/registry", "Model registry"],
  ["/system", "Health"],
  ["/settings/integrations", "API Integrations"],
];

test("every research page renders its heading from local fixtures", async ({ page }) => {
  const calls = await installApi(page);
  for (const [path, heading] of PAGES) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Research pages" })).toBeVisible();
  }
  expect(calls.filter((call) => call.method !== "GET")).toEqual([]);
  expect(calls.map((call) => call.path)).not.toContain("/api/orders/live");
  expect(calls.map((call) => call.path)).not.toContain("/api/paper/executions");
  expect(calls.map((call) => call.path)).not.toContain("/api/paper/simulations");
});

test("dashboard labels synthetic, stale, and quarantined data", async ({ page }) => {
  await installApi(page);
  await page.goto("/dashboard");
  await expect(page.getByTestId("snapshot")).toContainText("SYNTHETIC");
  await expect(page.getByTestId("snapshot")).toContainText("Stale");
  await expect(page.getByTestId("snapshot")).toContainText("11111.5");
  await expect(page.getByTestId("snapshot")).toContainText("not set");
  await expect(page.getByTestId("quarantine")).toContainText("Quarantined");
  await expect(page.getByTestId("quarantine")).toContainText("UNVERIFIED_PROVIDER");
  await expect(page.getByTestId("market-board")).toContainText("Unavailable");
  await expect(page.getByTestId("market-board")).toContainText("S&P 500");
  await expect(page.getByText("MISSING_RISK_CAPITAL")).toBeVisible();
});

test("a snapshot failure does not invent a price", async ({ page }) => {
  await installApi(page, {
    "/api/market/snapshot": { status: 503, contentType: "application/json", body: JSON.stringify({ message: "Snapshot unavailable." }) },
  });
  await page.goto("/dashboard");
  await expect(page.locator(".error")).toContainText("Snapshot unavailable.");
  await expect(page.getByTestId("snapshot")).not.toContainText("11111.5");
  await page.getByRole("button", { name: "Retry" }).first().click();
});

test("forecasts keep research results separate from approved forecasts", async ({ page }) => {
  await installApi(page);
  await page.goto("/forecast");
  await expect(page.getByTestId("approved-forecasts")).toContainText("No approved forecast was returned.");
  await expect(page.getByTestId("forecast-models")).toContainText("last_return_sign");
  await expect(page.getByTestId("forecast-models")).toContainText("Synthetic");
  await expect(page.getByTestId("forecast-models")).toContainText("dataset-1");
  await expect(page.getByTestId("experiments")).toContainText("hold-1");
  await expect(page.getByTestId("experiments")).toContainText("log_loss: not set");
  await expect(page.getByTestId("experiments")).toContainText("No walk-forward rows were returned.");
});

test("an empty model registry stays empty", async ({ page }) => {
  await installApi(page, {
    "/api/models": { status: 200, contentType: "application/json", body: JSON.stringify({ models: [], forecast_ready: false, paper_approved: false, live_approved: false, real_market_data_verified: false }) },
    "/api/experiments": { status: 200, contentType: "application/json", body: JSON.stringify({ holdout: [], walk_forward: [], forecast_ready: false }) },
  });
  await page.goto("/forecast");
  await expect(page.getByText("No model rows were returned. That is not an approval.")).toBeVisible();
  await expect(page.getByText("No saved experiments were returned.")).toBeVisible();
});

test("the options decision record cites the snapshot without pricing the contract", async ({ page }) => {
  await installApi(page);
  await page.goto("/options");
  await expect(page.getByTestId("record-decision")).toHaveText("NO_TRADE");
  await expect(page.getByTestId("snapshot-class")).toHaveText("synthetic");
  await expect(page.getByTestId("index-last")).toHaveText("11111.5");
  await expect(page.getByTestId("record-expected-net")).toContainText("not set");
  await expect(page.getByTestId("decision-record")).toContainText("last_return_sign");
  await expect(page.getByTestId("decision-record")).toContainText("hold-1");
  await expect(page.getByTestId("decision-record")).toContainText("CHARGES_UNVERIFIED");
  await expect(page.getByTestId("record-blockers")).toContainText("MISSING_RISK_CAPITAL");
  await expect(page.getByTestId("decision-record")).toContainText("Used as option premium");
  await expect(page.getByTestId("decision-record")).toContainText("False");
});

test("an option fixture stays empty until submitted and then stays NO_TRADE", async ({ page }) => {
  await installApi(page);
  await page.goto("/options");
  await page.getByText("Research fixture").click();
  await expect(page.getByTestId("candidate-empty")).toContainText("No candidate fixture has been submitted.");
  await page.getByLabel("Underlying").fill("NIFTY");
  await page.getByLabel("Strike").fill("25000");
  await page.getByLabel("Option type").fill("CE");
  await page.getByRole("button", { name: "Assess fixture" }).click();
  await expect(page.getByTestId("candidate-decision")).toHaveText("NO_TRADE");
  await expect(page.getByTestId("candidate-expected-net")).toContainText("not set");
  await expect(page.getByTestId("candidate-tradable")).toHaveText("False");
  await expect(page.getByTestId("candidate-evidence")).toContainText("MISSING_OPTION_QUOTE");
  await expect(page.getByTestId("candidate-blockers")).toContainText("MISSING_EXPIRY");
  await expect(page.getByTestId("candidate-blockers")).toContainText("CHARGES_UNVERIFIED");
  await expect(page.getByTestId("candidate")).not.toContainText("11111.5");
});

test("a malformed option fixture shows the validation error", async ({ page }) => {
  await installApi(page, {
    "/api/options/candidates": { status: 422, contentType: "application/json", body: JSON.stringify({ ok: false, decision: "NO_TRADE", errors: [{ code: "INVALID_STRIKE", detail: "strike must be a positive finite number." }] }) },
  });
  await page.goto("/options");
  await page.getByText("Research fixture").click();
  await page.getByLabel("Strike").fill("-1");
  await page.getByRole("button", { name: "Assess fixture" }).click();
  await expect(page.locator(".error")).toContainText("INVALID_STRIKE");
  await expect(page.getByTestId("candidate")).not.toContainText("NO_TRADE");
});

test("options show NO_TRADE, every reason, and a null expected net", async ({ page }) => {
  await installApi(page);
  await page.goto("/options");
  await expect(page.getByTestId("decision")).toHaveText("NO_TRADE");
  await expect(page.getByTestId("decision-reasons")).toContainText("INVALID_CONTRACT");
  await expect(page.getByTestId("decision-reasons")).toContainText("MISSING_ENTRY_TRIGGER");
  await expect(page.getByTestId("expected-net")).toContainText("not set");
  await expect(page.getByTestId("expected-net")).not.toContainText("0");
  await expect(page.getByText("Not executable")).toBeVisible();
  await expect(page.getByText("underlying: not set")).toBeVisible();
});

test("an options failure does not invent a decision or a profit", async ({ page }) => {
  await installApi(page, {
    "/api/options/research": { status: 500, contentType: "application/json", body: JSON.stringify({ message: "Proposal unavailable." }) },
  });
  await page.goto("/options");
  await expect(page.locator(".error")).toContainText("Proposal unavailable.");
  await expect(page.getByTestId("proposal")).not.toContainText("NO_TRADE");
  await expect(page.getByTestId("proposal")).not.toContainText("profitable");
});

test("paper lookup shows a veto, an unknown intent, and a malformed id", async ({ page }) => {
  const calls = await installApi(page);
  await page.goto("/paper");
  await page.getByLabel("Intent id").fill("bad id");
  await page.getByRole("button", { name: "Read stored decision" }).click();
  await expect(page.locator(".error")).toContainText("malformed");
  expect(calls.map((call) => call.path)).not.toContain("/api/paper/simulations/bad id");

  await page.getByLabel("Intent id").fill("missing-intent");
  await page.getByRole("button", { name: "Read stored decision" }).click();
  await expect(page.getByTestId("replay")).toContainText("none stored");
  await expect(page.getByTestId("fill")).toContainText("not set");

  await page.getByLabel("Intent id").fill("intent-1");
  await page.getByRole("button", { name: "Read stored decision" }).click();
  await expect(page.getByTestId("replay")).toContainText("VETOED");
  await expect(page.getByTestId("fill")).toContainText("not set");
  await expect(page.getByTestId("replay-expected-net")).toContainText("not set");
  await expect(page.getByText("MODEL_NOT_APPROVED")).toBeVisible();
  await expect(page.getByRole("button", { name: /submit|execute|place order/i })).toHaveCount(0);
});

test("a paper lookup failure does not invent a fill", async ({ page }) => {
  await installApi(page, {
    "/api/paper/simulations/intent-1": { status: 500, contentType: "application/json", body: JSON.stringify({ message: "Replay unavailable." }) },
  });
  await page.goto("/paper");
  await page.getByLabel("Intent id").fill("intent-1");
  await page.getByRole("button", { name: "Read stored decision" }).click();
  await expect(page.locator(".error")).toContainText("Replay unavailable.");
  await expect(page.getByTestId("fill")).toHaveCount(0);
});

test("risk keeps a null tolerance and a missing broker snapshot unset", async ({ page }) => {
  await installApi(page);
  await page.goto("/risk");
  await expect(page.getByRole("definition").filter({ hasText: /^OFF$/ })).toBeVisible();
  await expect(page.getByTestId("tolerance")).toHaveText("not set");
  await expect(page.getByTestId("broker-snapshot")).toHaveText("not set");
  await expect(page.getByTestId("accounting")).toContainText("unknown_not_zero");
  await expect(page.getByTestId("accounting")).not.toContainText("FILL");
  await expect(page.getByTestId("risk-gates")).toContainText("VETO");
  await expect(page.getByTestId("capital-config")).toBeVisible();
  await expect(page.getByRole("button", { name: "Set risk capital" })).toBeVisible();
});

test("an accounting failure does not show zero balances", async ({ page }) => {
  await installApi(page, {
    "/api/accounting/status": { status: 503, contentType: "application/json", body: JSON.stringify({ message: "Accounting unavailable." }) },
  });
  await page.goto("/risk");
  await expect(page.locator(".error")).toContainText("Accounting unavailable.");
  await expect(page.getByTestId("accounting")).not.toContainText("₹");
  await expect(page.getByTestId("tolerance")).toHaveCount(0);
});

test("a Groww quote read stays unverified", async ({ page }) => {
  await installApi(page);
  await page.goto("/dashboard");
  await expect(page.getByTestId("live-quotes")).toContainText("No Groww quote is stored.");
  await page.getByRole("button", { name: "Read Groww quotes" }).click();
  await expect(page.getByTestId("live-quotes")).toContainText("UNVERIFIED_PROVIDER_DATA");
  await expect(page.getByTestId("live-quotes")).toContainText("24500.5");
  await expect(page.getByTestId("live-quotes")).toContainText("false");
});

test("the analyst shows missing news without a trade", async ({ page }) => {
  await installApi(page);
  await page.goto("/analysis");
  await page.getByRole("button", { name: "Run analysis" }).click();
  await expect(page.getByTestId("intelligence")).toContainText("MISSING_DATA");
  await expect(page.getByTestId("intelligence")).toContainText("NO_TRADE");
  await expect(page.getByTestId("intelligence")).toContainText("not set");
  await expect(page.getByRole("button", { name: /place order|execute/i })).toHaveCount(0);
});

test("the analyst and portfolio stay blank before an assessment", async ({ page }) => {
  await installApi(page);
  await page.goto("/analysis");
  await expect(page.getByTestId("perspectives")).toContainText("Not run.");
  await expect(page.getByRole("button", { name: /place order|execute/i })).toHaveCount(0);
  await page.goto("/risk");
  await expect(page.getByText("Session P&L", { exact: true })).toBeVisible();
  await expect(page.getByText("not set").first()).toBeVisible();
});

test("sign in and log out use the operator session", async ({ page }) => {
  await installApi(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Create the operator account" })).toBeVisible();
  await page.getByLabel("Password").fill("operator-secret");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Profile" })).toBeVisible();
  await expect(page.getByTestId("profile")).toContainText("neo");
  await expect(page.getByLabel("Display name")).toHaveValue("Neo");
  await expect(page.getByRole("link", { name: "Set up API keys" })).toBeVisible();
  await page.locator("main").getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByLabel("Password")).toBeVisible();
});

test("signup creates the stored operator account", async ({ page }) => {
  await installApi(page);
  await page.goto("/signup");
  await page.getByLabel("Username").fill("neo");
  await page.getByLabel("Display name").fill("Neo");
  await page.getByLabel("Password", { exact: true }).fill("longenough1");
  await page.getByLabel("Confirm password").fill("different1");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.locator("main").getByRole("alert")).toContainText("do not match");
  await page.getByLabel("Confirm password").fill("longenough1");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByTestId("profile")).toContainText("yes");
});

test("the desk stays usable on a narrow viewport and exposes names", async ({ page }) => {
  await installApi(page);
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/dashboard");
  await expect(page.getByRole("navigation", { name: "Research pages" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Overview" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await expect(page.getByRole("table", { name: "Snapshot quotes and their source class" })).toBeVisible();
  await page.goto("/");
  await expect(page.getByLabel("Password")).toBeVisible();
});
