/** @type {import('@playwright/test').PlaywrightTestConfig} */
module.exports = {
  testDir: "./tests/e2e",
  timeout: 30000,
  retries: 0,
  use: {
    baseURL: "http://127.0.0.1:8787",
    trace: "on-first-retry",
  },
  webServer: {
    command: "python3 -m http.server 8787 --directory .",
    port: 8787,
    reuseExistingServer: true,
    timeout: 15000,
  },
};
