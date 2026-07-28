/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

/**
 * Vitest config for the UI suite.
 *
 * - `jsdom` gives React Testing Library a DOM to render into (no real browser).
 * - `setupFiles` registers jest-dom matchers and starts the MSW mock server so
 *   every test runs against the OpenAPI-shaped mock layer, never a live backend.
 * - The `@` alias mirrors tsconfig paths so imports resolve identically in tests.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    css: false,
  },
});
