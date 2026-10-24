import { test as base, expect } from "@playwright/test";

/** Real browser + the app's contract-shaped MSW handlers, not Playwright API stubs. */
export const test = base.extend({
  page: async ({ page }, runTest, testInfo) => {
    const errors: string[] = [];
    const knownResourceErrors: string[] = [];
    const mockedReads: string[] = [];
    page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
    page.on("console", (message) => {
      if (message.type() !== "error") return;
      // Headed Chromium requests a favicon; this app does not publish one yet.
      // Match both resource URL and exact 404 text, never arbitrary HTTP errors.
      if (
        message.location().url === new URL("/favicon.ico", testInfo.project.use.baseURL).href &&
        message.text() === "Failed to load resource: the server responded with a status of 404 (Not Found)"
      ) {
        knownResourceErrors.push(`Missing favicon: ${message.location().url}`);
        return;
      }
      errors.push(`console: ${message.text()}`);
    });
    page.on("response", (response) => {
      if (!new URL(response.url()).pathname.startsWith("/api/v1/")) return;
      if (!response.fromServiceWorker()) {
        errors.push(`API bypassed MSW: ${response.url()}`);
      }
      if (response.status() >= 400) {
        errors.push(`API ${response.status()}: ${response.url()}`);
      }
      if (response.fromServiceWorker() && response.request().method() === "GET") {
        mockedReads.push(response.url());
      }
    });
    page.on("requestfailed", (request) => {
      // Next navigation/unmount can intentionally cancel superseded reads.
      if (request.failure()?.errorText === "net::ERR_ABORTED") return;
      errors.push(`requestfailed: ${request.url()} ${request.failure()?.errorText}`);
    });

    await runTest(page);

    await testInfo.attach("browser-health", {
      body: JSON.stringify({ errors, knownResourceErrors, mockedReads }, null, 2),
      contentType: "application/json",
    });
    expect(errors, "No browser errors, failed requests or unmocked API responses").toEqual([]);
    expect(mockedReads.length, "The browser must actually read MSW fixture data").toBeGreaterThan(0);
  },
});

export { expect };
