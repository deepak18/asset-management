import { defineConfig, devices } from "@playwright/test";

// This suite has no live-URL override: every run owns a mock-only loopback server.
const origin = "http://127.0.0.1:3100";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["html", { open: "never" }]],
  outputDir: "test-results",
  use: {
    baseURL: origin,
    serviceWorkers: "allow",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    {
      name: "chromium-narrow",
      use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } },
    },
  ],
  webServer: {
    command:
      "npx msw init public --no-save && npm run dev -- --hostname 127.0.0.1 --port 3100",
    url: origin,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      FRONTEND_E2E: "1",
      NEXT_PUBLIC_API_MOCKING: "enabled",
      // Same-origin mocks cannot fall through to a user's real API/account.
      NEXT_PUBLIC_API_BASE_URL: origin,
      NEXT_TELEMETRY_DISABLED: "1",
    },
  },
});
