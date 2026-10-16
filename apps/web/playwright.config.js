const { defineConfig, devices } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: 0,
  timeout: 30000,
  use: {
    ...devices["Desktop Chrome"],
    channel: "chrome",
    baseURL: "http://127.0.0.1:3100",
  },
  webServer: {
    command: "npx next start --hostname 127.0.0.1 --port 3100",
    url: "http://127.0.0.1:3100",
    reuseExistingServer: false,
    timeout: 120000,
    env: {
      API_URL: "http://127.0.0.1:9",
    },
  },
});
