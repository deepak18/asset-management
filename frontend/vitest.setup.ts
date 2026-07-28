import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "@/mocks/server";

/**
 * Global test harness.
 *
 * MSW intercepts fetch at the network layer, so components exercise the real
 * typed API client while the responses come from OpenAPI-shaped fixtures. We
 * reset handlers between tests so a per-test override never leaks into the next.
 *
 * jsdom does not implement ResizeObserver, which Recharts' responsive container
 * relies on; we install a no-op stub so charts render in tests without crashing.
 */
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
});
afterAll(() => server.close());
